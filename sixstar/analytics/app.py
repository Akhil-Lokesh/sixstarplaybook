"""Analytics service: question log, trending questions, thumbs up/down, wrong-answer
reports and a small admin stats view. Raw IPs are never stored, only salted hashes.

Owns keys: trend:*, qmeta:*, log:*, stats:*, fb:*, reports.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends
from pydantic import BaseModel, Field

from ..common.config import get_settings
from ..common.store import Store, make_store
from ..common.web import make_app, require_admin, require_internal

_store: dict[str, Store] = {}
TRENDING_STATUSES = {"answered", "not_confirmed"}


def store() -> Store:
    if "s" not in _store:
        _store["s"] = make_store(namespace="analytics")
    return _store["s"]


def reset_store(s: Store | None = None) -> None:
    _store.clear()
    if s is not None:
        _store["s"] = s


async def _health() -> dict[str, Any]:
    return {"store": "ok" if await store().ping() else "down"}


app = make_app("analytics", _health)


def _day(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=offset)).strftime("%Y%m%d")


def _hash_ip(ip: str) -> str:
    return hashlib.sha256((get_settings().analytics_salt + ip).encode()).hexdigest()[:16]


class QuestionEvent(BaseModel):
    question: str = Field(max_length=400)
    slug: str = Field(max_length=120)
    status: str
    cached: bool
    latency_ms: int = 0
    cost_usd: float = 0.0
    ip: str | None = None


class FeedbackIn(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    helpful: bool
    client_id: str | None = Field(default=None, max_length=64)


class ReportIn(BaseModel):
    slug: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)


@app.post("/internal/events/question", dependencies=[Depends(require_internal)])
async def question_event(ev: QuestionEvent) -> dict[str, Any]:
    s = store()
    day = _day()
    await s.incrby(f"stats:{day}:questions", 1, ttl=90 * 86400)
    if ev.cached:
        await s.incrby(f"stats:{day}:cached", 1, ttl=90 * 86400)
    if ev.cost_usd:
        await s.incrby(f"stats:{day}:cost_micro", int(ev.cost_usd * 1_000_000), ttl=90 * 86400)
    if ev.status in TRENDING_STATUSES:
        await s.zincrby(f"trend:{day}", ev.slug, 1, ttl=3 * 86400)
        await s.set(f"qmeta:{ev.slug}", ev.question, ttl=30 * 86400)
    record = {
        "t": int(time.time()), "q": ev.question, "slug": ev.slug, "status": ev.status,
        "cached": ev.cached, "ms": ev.latency_ms, "cost": ev.cost_usd,
        "ip": _hash_ip(ev.ip) if ev.ip else None,
    }
    await s.lpush_trim("log:questions", json.dumps(record), maxlen=2000)
    return {"ok": True}


@app.get("/trending")
async def trending(limit: int = 10) -> dict[str, Any]:
    """Most-asked answered questions over today and yesterday (UTC)."""
    limit = max(1, min(limit, 50))
    scores: dict[str, float] = {}
    for offset in (0, 1):
        for slug, score in await store().ztop(f"trend:{_day(offset)}", limit * 3):
            scores[slug] = scores.get(slug, 0) + score
    top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    items = []
    for slug, count in top:
        question = await store().get(f"qmeta:{slug}")
        if question:
            items.append({"slug": slug, "question": question, "count": int(count)})
    return {"items": items}


@app.post("/feedback")
async def feedback(body: FeedbackIn) -> dict[str, Any]:
    s = store()
    if body.client_id:
        first = await s.set(f"fbseen:{body.slug}:{body.client_id}", "1", ttl=30 * 86400, nx=True)
        if not first:
            return {"ok": True, "duplicate": True}
    field = "up" if body.helpful else "down"
    await s.incrby(f"fb:{body.slug}:{field}", 1, ttl=90 * 86400)
    await s.incrby(f"stats:{_day()}:fb_{field}", 1, ttl=90 * 86400)
    return {"ok": True}


@app.get("/feedback/{slug}")
async def feedback_counts(slug: str) -> dict[str, Any]:
    up = int(await store().get(f"fb:{slug}:up") or 0)
    down = int(await store().get(f"fb:{slug}:down") or 0)
    return {"slug": slug, "up": up, "down": down}


@app.post("/report")
async def report(body: ReportIn) -> dict[str, Any]:
    entry = {"t": int(time.time()), "slug": body.slug, "note": body.note.strip()}
    await store().lpush_trim("reports", json.dumps(entry), maxlen=500)
    await store().incrby(f"stats:{_day()}:reports", 1, ttl=90 * 86400)
    return {"ok": True}


@app.get("/admin/stats", dependencies=[Depends(require_admin)])
async def admin_stats(days: int = 7) -> dict[str, Any]:
    s = store()
    out = []
    for offset in range(max(1, min(days, 30))):
        day = _day(offset)
        row = {"day": day}
        for name in ("questions", "cached", "cost_micro", "fb_up", "fb_down", "reports"):
            row[name] = int(await s.get(f"stats:{day}:{name}") or 0)
        row["cost_usd"] = round(row.pop("cost_micro") / 1_000_000, 4)
        votes = row["fb_up"] + row["fb_down"]
        row["thumbs_up_rate"] = round(row["fb_up"] / votes, 3) if votes else None
        out.append(row)
    recent = [json.loads(x) for x in await s.lrange("log:questions", 0, 49)]
    reports = [json.loads(x) for x in await s.lrange("reports", 0, 49)]
    return {"days": out, "recent_questions": recent, "recent_reports": reports}
