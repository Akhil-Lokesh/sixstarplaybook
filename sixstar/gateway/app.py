"""Gateway: the only public service. Everything the frontend calls is under /api.

It handles CORS, works out the visitor's IP and browser id, applies a coarse
per-IP request limit to every route, and forwards to the internal services.
Owns keys: edge:* (per-IP requests per minute).
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from fastapi import Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ..common.config import get_settings
from ..common.store import Store, make_store
from ..common.web import ApiError, is_admin, make_app, raise_for_error, service_client

_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_SLUG = re.compile(r"^[a-z0-9-]{1,120}$")
LIMIT_CODES = {"rate_limited", "busy", "budget_exhausted"}
_store: dict[str, Store] = {}


def store() -> Store:
    if "s" not in _store:
        _store["s"] = make_store(namespace="gateway")
    return _store["s"]


def reset_store(s: Store | None = None) -> None:
    _store.clear()
    if s is not None:
        _store["s"] = s


app = make_app("gateway")
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Client-Id"],
    expose_headers=["Retry-After", "X-RateLimit-Remaining-Hour"],
    max_age=600,
)


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def client_id(value: str | None) -> str | None:
    return value if value and _CLIENT_ID.match(value) else None


@app.middleware("http")
async def edge_limit(request: Request, call_next: Any) -> Response:
    """A coarse per-IP cap on all /api traffic, separate from the per-question limits."""
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        minute = time.strftime("%Y%m%d%H%M", time.gmtime())
        count = await store().incrby(f"edge:{client_ip(request)}:{minute}", 1, ttl=70)
        if count > get_settings().edge_rpm:
            return ApiError(429, "rate_limited", "Too many requests. Slow down a little.",
                            retry_after=60 - time.gmtime().tm_sec).response()
    return await call_next(request)


async def _forward_json(service: str, method: str, path: str, *, cache_seconds: int = 0,
                        **kwargs: Any) -> JSONResponse:
    resp = await service_client(service).request(method, path, **kwargs)
    await raise_for_error(resp)
    headers = {"Cache-Control": f"public, max-age={cache_seconds}"} if cache_seconds else {"Cache-Control": "no-store"}
    return JSONResponse(resp.json(), status_code=resp.status_code, headers=headers)


async def _top_questions(limit: int = 8) -> list[dict[str, Any]]:
    try:
        resp = await service_client("analytics").get("/trending", params={"limit": limit})
        return resp.json().get("items", []) if resp.status_code == 200 else []
    except Exception:  # noqa: BLE001
        return []


# Health ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> JSONResponse:
    async def check(name: str) -> tuple[str, Any]:
        try:
            resp = await service_client(name).get("/health", timeout=3.0)
            return name, resp.json() if resp.status_code == 200 else {"status": "down"}
        except Exception:  # noqa: BLE001
            return name, {"status": "down"}

    results = dict(await asyncio.gather(*(check(n) for n in ("answer", "guard", "content", "analytics"))))
    ok = all(r.get("status") == "ok" for r in results.values())
    return JSONResponse({"status": "ok" if ok else "degraded", "services": results}, status_code=200 if ok else 503)


# Ask ------------------------------------------------------------------------------

class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


async def _ask(request: Request, question: str, cid: str | None, admin_token: str | None) -> Response:
    payload = {
        "question": question,
        "ip": client_ip(request),
        "client_id": client_id(cid),
        "bypass_user_limits": is_admin(admin_token),
    }
    client = service_client("answer")
    upstream = await client.send(client.build_request("POST", "/internal/ask", json=payload), stream=True)
    if upstream.status_code != 200:
        try:
            await raise_for_error(upstream)
        except ApiError as err:
            if err.code in LIMIT_CODES:
                err.extra["top_questions"] = await _top_questions()
            return err.response()
        finally:
            await upstream.aclose()
    return StreamingResponse(
        upstream.aiter_raw(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        background=BackgroundTask(upstream.aclose),
    )


@app.post("/api/ask")
async def ask_post(body: AskBody, request: Request, x_client_id: str | None = Header(default=None),
                   x_admin_token: str | None = Header(default=None)) -> Response:
    return await _ask(request, body.question, x_client_id, x_admin_token)


@app.get("/api/ask")
async def ask_get(request: Request, q: str = Query(min_length=1, max_length=2000),
                  client_id_param: str | None = Query(default=None, alias="client_id")) -> Response:
    """For EventSource, which can only send GET without custom headers."""
    return await _ask(request, q, client_id_param, None)


@app.get("/api/q/{slug}")
async def answer_page(slug: str) -> JSONResponse:
    if not _SLUG.match(slug):
        raise ApiError(404, "not_found", "No answer page for that question yet.")
    return await _forward_json("answer", "GET", f"/internal/answers/{slug}", cache_seconds=300)


@app.get("/api/limits")
async def limits(request: Request, x_client_id: str | None = Header(default=None)) -> JSONResponse:
    params = {"ip": client_ip(request)}
    if cid := client_id(x_client_id):
        params["client_id"] = cid
    return await _forward_json("guard", "GET", "/internal/status", params=params)


# Content --------------------------------------------------------------------------

@app.get("/api/starters")
async def starters() -> JSONResponse:
    return await _forward_json("content", "GET", "/starters", cache_seconds=300)


@app.get("/api/topics")
async def topics() -> JSONResponse:
    return await _forward_json("content", "GET", "/topics", cache_seconds=300)


@app.get("/api/topics/{topic_id}")
async def topic(topic_id: str) -> JSONResponse:
    if not _SLUG.match(topic_id):
        raise ApiError(404, "not_found", "No such topic")
    return await _forward_json("content", "GET", f"/topics/{topic_id}", cache_seconds=300)


@app.get("/api/cheat-codes")
async def cheat_codes() -> JSONResponse:
    return await _forward_json("content", "GET", "/cheat-codes", cache_seconds=120)


@app.get("/api/whats-new")
async def whats_new() -> JSONResponse:
    return await _forward_json("content", "GET", "/whats-new", cache_seconds=120)


@app.get("/api/guide/version")
async def guide_version() -> JSONResponse:
    return await _forward_json("content", "GET", "/guide/version", cache_seconds=60)


# Analytics ------------------------------------------------------------------------

class FeedbackBody(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    helpful: bool


class ReportBody(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)


@app.get("/api/trending")
async def trending(limit: int = Query(default=10, ge=1, le=50)) -> JSONResponse:
    return await _forward_json("analytics", "GET", "/trending", params={"limit": limit}, cache_seconds=60)


@app.post("/api/feedback")
async def feedback(body: FeedbackBody, x_client_id: str | None = Header(default=None)) -> JSONResponse:
    return await _forward_json("analytics", "POST", "/feedback",
                               json={"slug": body.slug, "helpful": body.helpful, "client_id": client_id(x_client_id)})


@app.post("/api/report")
async def report(body: ReportBody) -> JSONResponse:
    return await _forward_json("analytics", "POST", "/report", json=body.model_dump())
