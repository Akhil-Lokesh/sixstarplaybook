"""Answer service: turns a question into a streamed, sourced answer.

Per question: clean and normalize -> answer cache -> (single-flight wait if the same
question is already being answered) -> guard authorize -> Claude stream -> save to
the answer cache and the answer page -> settle the real cost -> log to analytics.

Owns keys: ans:* (answer cache, keyed by guide version), page:* (answer pages).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import anthropic
from fastapi import Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..common.config import get_settings
from ..common.store import Store, make_store
from ..common.text import clean_question, normalize_question, question_hash, slugify
from ..common.web import ApiError, make_app, raise_for_error, require_internal, service_client
from .llm import cost_usd, get_client, request_params, stream_answer
from .prompt import answer_schema, system_blocks, user_message

log = logging.getLogger(__name__)

_store: dict[str, Store] = {}
_guide: dict[str, Any] = {"data": None, "checked": 0.0}
_inflight: dict[str, tuple[asyncio.Event, float]] = {}
_bg_tasks: set[asyncio.Task] = set()
PAGE_STATUSES = {"answered", "not_confirmed"}


def store() -> Store:
    if "s" not in _store:
        _store["s"] = make_store(namespace="answer")
    return _store["s"]


def reset_state(s: Store | None = None) -> None:
    _store.clear()
    if s is not None:
        _store["s"] = s
    _guide.update({"data": None, "checked": 0.0})
    _inflight.clear()


async def _health() -> dict[str, Any]:
    s = get_settings()
    import os

    llm = "mock" if s.mock_llm else ("ok" if os.environ.get("ANTHROPIC_API_KEY") else "missing_api_key")
    g = _guide["data"]
    return {"store": "ok" if await store().ping() else "down", "llm": llm, "model": s.model,
            "guide_version": g["version"] if g else None}


app = make_app("answer", _health)


# Guide ------------------------------------------------------------------------------

async def current_guide() -> dict[str, Any]:
    """The guide from the content service, re-checked every GUIDE_REFRESH_SECONDS."""
    settings = get_settings()
    now = time.time()
    cached = _guide["data"]
    if cached and now - _guide["checked"] < settings.guide_refresh_s:
        return cached
    try:
        content = service_client("content")
        resp = await content.get("/guide/version")
        await raise_for_error(resp)
        version = resp.json()["version"]
        if not cached or cached["version"] != version:
            resp = await content.get("/internal/guide")
            await raise_for_error(resp)
            g = resp.json()
            section_ids = [s["id"] for s in g["sections"]]
            cached = {
                "version": g["version"],
                "sections": {s["id"]: s["title"] for s in g["sections"]},
                "system": system_blocks(g["title"], g["prompt_text"], settings.prompt_cache_ttl),
                "schema": answer_schema(section_ids),
            }
            _guide["data"] = cached
            log.info("using guide version %s", cached["version"])
        _guide["checked"] = now
    except Exception as exc:  # noqa: BLE001
        if not cached:
            raise ApiError(503, "unavailable", "The guide isn't loaded yet. Try again shortly.") from exc
        log.warning("guide refresh failed, keeping %s: %s", cached["version"], exc)
        _guide["checked"] = now
    return cached


# Records ----------------------------------------------------------------------------

def build_record(question: str, slug: str, data: dict[str, Any], guide: dict[str, Any],
                 model: str, truncated: bool = False) -> dict[str, Any]:
    sections = guide["sections"]
    seen: list[str] = []
    for sid in data.get("sources") or []:
        if sid in sections and sid not in seen:
            seen.append(sid)
    return {
        "slug": slug,
        "question": question,
        "answer": (data.get("answer") or "").strip(),
        "status": data.get("status") or "answered",
        "claims": [
            {"text": c.get("text", ""), "label": c.get("label", "confirmed")}
            for c in (data.get("claims") or []) if isinstance(c, dict)
        ],
        "sources": [{"id": sid, "title": sections[sid], "url": f"/topics/{sid}"} for sid in seen],
        "related_questions": [q for q in (data.get("related_questions") or []) if isinstance(q, str)][:3],
        "spoiler": bool(data.get("spoiler")),
        "truncated": truncated,
        "guide_version": guide["version"],
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def _slug_for(question: str, normalized: str, qhash: str) -> str:
    slug = slugify(normalized)
    existing = await store().get(f"page:{slug}")
    if existing and json.loads(existing).get("normalized") != normalized:
        slug = f"{slug}-{qhash[:6]}"
    return slug


async def _save(cache_key: str, record: dict[str, Any], normalized: str) -> None:
    s = get_settings()
    payload = json.dumps(record)
    await store().set(cache_key, payload, ttl=s.answer_cache_ttl_s)
    if record["status"] in PAGE_STATUSES and not record["truncated"]:
        await store().set(f"page:{record['slug']}", json.dumps({**record, "normalized": normalized}),
                          ttl=s.answer_page_ttl_s)


# Side calls -------------------------------------------------------------------------

def _background(coro: Any) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _log_event(**event: Any) -> None:
    try:
        await service_client("analytics").post("/internal/events/question", json=event)
    except Exception as exc:  # noqa: BLE001 - analytics must never break answers
        log.warning("analytics event failed: %s", exc)


async def _settle(reserved: float, actual: float) -> None:
    try:
        await service_client("guard").post("/internal/settle", json={"reserved_usd": reserved, "actual_usd": actual})
    except Exception as exc:  # noqa: BLE001
        log.error("spend settle failed (reserved %.4f, actual %.6f): %s", reserved, actual, exc)


# SSE --------------------------------------------------------------------------------

def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _cached_stream(record: dict[str, Any]) -> AsyncIterator[str]:
    yield sse("meta", {"slug": record["slug"], "cached": True, "guide_version": record["guide_version"]})
    yield sse("delta", {"text": record["answer"]})
    yield sse("answer", {**record, "cached": True})
    yield sse("done", {})


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    ip: str = Field(default="unknown", max_length=64)
    client_id: str | None = Field(default=None, max_length=64)
    bypass_user_limits: bool = False


@app.post("/internal/ask", dependencies=[Depends(require_internal)])
async def ask(body: AskIn) -> StreamingResponse:
    settings = get_settings()
    started = time.monotonic()
    question = clean_question(body.question, settings.question_max_chars)
    normalized = normalize_question(question)
    if len(normalized) < 3:
        raise ApiError(400, "invalid_question", "Type a question about GTA 6.")

    guide = await current_guide()
    qhash = question_hash(normalized)
    cache_key = f"ans:{guide['version']}:{qhash}"

    async def from_cache() -> StreamingResponse | None:
        hit = await store().get(cache_key)
        if not hit:
            return None
        record = json.loads(hit)
        _background(_log_event(question=question, slug=record["slug"], status=record["status"], cached=True,
                               latency_ms=int((time.monotonic() - started) * 1000), cost_usd=0.0, ip=body.ip))
        return _sse_response(_cached_stream(record))

    if (resp := await from_cache()) is not None:
        return resp

    # Single flight: if this exact question is being answered right now, wait for it.
    # A claim older than the LLM timeout is stale (its stream never ran) and is ignored.
    claim = _inflight.get(cache_key)
    if claim and time.monotonic() - claim[1] < settings.llm_timeout_s:
        try:
            await asyncio.wait_for(claim[0].wait(), timeout=settings.llm_timeout_s)
        except asyncio.TimeoutError:
            pass
        if (resp := await from_cache()) is not None:
            return resp

    # Claiming this question so identical concurrent requests wait instead of paying again.
    done_event = asyncio.Event()
    _inflight[cache_key] = (done_event, time.monotonic())
    try:
        # Spend caps and rate limits, before any money is spent.
        auth = await service_client("guard").post("/internal/authorize", json={
            "ip": body.ip, "client_id": body.client_id, "bypass_user_limits": body.bypass_user_limits,
        })
        await raise_for_error(auth)
        reserved = float(auth.json().get("reserved_usd", 0.0))
        slug = await _slug_for(question, normalized, qhash)
    except BaseException:
        done_event.set()
        _inflight.pop(cache_key, None)
        raise

    params = request_params(settings, guide["system"], user_message(question), guide["schema"])

    async def generate() -> AsyncIterator[str]:
        actual = 0.0
        status = "error"
        try:
            yield sse("meta", {"slug": slug, "cached": False, "guide_version": guide["version"]})
            client = get_client(settings)
            async with asyncio.timeout(settings.llm_timeout_s):
                async for kind, payload in stream_answer(client, params):
                    if kind == "delta":
                        yield sse("delta", {"text": payload})
                        continue
                    final, streamed_text = payload
                    actual = cost_usd(getattr(final, "usage", None), settings)
                    if final.stop_reason == "refusal":
                        status = "refused"
                        yield sse("error", {"code": "refused",
                                            "message": "I can't help with that one. Try another GTA 6 question."})
                        return
                    raw = "".join(b.text for b in final.content if getattr(b, "type", "") == "text")
                    truncated = final.stop_reason == "max_tokens"
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        if not streamed_text:
                            raise
                        data = {"answer": streamed_text, "status": "answered"}
                        truncated = True
                    record = build_record(question, slug, data, guide, settings.model, truncated)
                    status = record["status"]
                    await _save(cache_key, record, normalized)
                    yield sse("answer", {**record, "cached": False})
            yield sse("done", {})
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            log.warning("claude busy: %s", exc)
            yield sse("error", {"code": "busy", "message": "The answer engine is busy. Try again in a minute.",
                                "retry_after": 60})
        except (anthropic.APIError, TimeoutError, json.JSONDecodeError) as exc:
            log.error("claude call failed: %s", exc)
            yield sse("error", {"code": "upstream_error", "message": "Something went wrong getting that answer. "
                                                                    "Try again."})
        except Exception as exc:  # noqa: BLE001
            log.exception("answer failed: %s", exc)
            yield sse("error", {"code": "internal_error", "message": "Something went wrong. Try again."})
        finally:
            done_event.set()
            if _inflight.get(cache_key, (None, 0))[0] is done_event:
                _inflight.pop(cache_key, None)
            _background(_settle(reserved, actual))
            _background(_log_event(question=question, slug=slug, status=status, cached=False,
                                   latency_ms=int((time.monotonic() - started) * 1000), cost_usd=actual,
                                   ip=body.ip))

    return _sse_response(generate())


def _sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/internal/answers/{slug}", dependencies=[Depends(require_internal)])
async def answer_page(slug: str) -> dict[str, Any]:
    raw = await store().get(f"page:{slug}")
    if not raw:
        raise ApiError(404, "not_found", "No answer page for that question yet.")
    record = json.loads(raw)
    record.pop("normalized", None)
    return record
