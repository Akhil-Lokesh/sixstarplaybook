"""Guard service: per-user rate limits, the global AI-call limit, and the daily and
monthly spend caps. The answer service asks it before every Claude call
(/internal/authorize) and reports the real cost afterwards (/internal/settle).

Owns keys: rl:*, global:*, spend:*. Spend is stored in micro-dollars.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends
from pydantic import BaseModel, Field

from ..common.config import get_settings
from ..common.store import Store, make_store
from ..common.web import ApiError, make_app, require_admin, require_internal

MICRO = 1_000_000

_store: dict[str, Store] = {}


def store() -> Store:
    if "s" not in _store:
        _store["s"] = make_store(namespace="guard")
    return _store["s"]


def reset_store(s: Store | None = None) -> None:
    _store.clear()
    if s is not None:
        _store["s"] = s


async def _health() -> dict[str, Any]:
    return {"store": "ok" if await store().ping() else "down"}


app = make_app("guard", _health)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _windows(now: datetime) -> dict[str, tuple[str, int]]:
    """Fixed windows (UTC): name -> (key suffix, seconds until the window ends)."""
    epoch = int(now.timestamp())
    return {
        "minute": (now.strftime("%Y%m%d%H%M"), 60 - now.second),
        "hour": (now.strftime("%Y%m%d%H"), 3600 - (epoch % 3600)),
        "day": (now.strftime("%Y%m%d"), 86400 - (epoch % 86400)),
        "month": (now.strftime("%Y%m"), 0),
    }


def _spend_keys(now: datetime) -> tuple[str, str]:
    return f"spend:day:{now.strftime('%Y%m%d')}", f"spend:month:{now.strftime('%Y%m')}"


class AuthorizeIn(BaseModel):
    ip: str = Field(min_length=1, max_length=64)
    client_id: str | None = Field(default=None, max_length=64)
    bypass_user_limits: bool = False


class SettleIn(BaseModel):
    reserved_usd: float = Field(ge=0)
    actual_usd: float = Field(ge=0)


async def _hit(key: str, limit: int, ttl: int, retry_after: int, code: str, message: str) -> str:
    """Counting one request against a window; rolling back and raising when over."""
    count = await store().incrby(key, 1, ttl=ttl + 5)
    if count > limit:
        await store().incrby(key, -1)
        raise ApiError(429 if code == "rate_limited" else 503, code, message, retry_after=max(retry_after, 1))
    return key


@app.post("/internal/authorize", dependencies=[Depends(require_internal)])
async def authorize(body: AuthorizeIn) -> dict[str, Any]:
    s = get_settings()
    now = _now()
    win = _windows(now)
    taken: list[str] = []
    try:
        # 1. Spend caps: refuse before anything is counted.
        day_key, month_key = _spend_keys(now)
        reserve = int(s.cost_estimate_usd * MICRO)
        day_spend = await store().incrby(day_key, reserve, ttl=2 * 86400)
        month_spend = await store().incrby(month_key, reserve, ttl=40 * 86400)
        taken += [day_key, month_key]
        if day_spend > s.daily_cap_usd * MICRO or month_spend > s.monthly_cap_usd * MICRO:
            raise ApiError(
                503,
                "budget_exhausted",
                "We've hit today's answer budget. Cached answers still work.",
                retry_after=win["day"][1],
            )

        # 2. Global calls per minute, so a spike queues instead of melting the budget.
        await _hit(
            f"global:rpm:{win['minute'][0]}", s.global_ai_rpm, 60, win["minute"][1],
            "busy", "Lots of people are asking right now. Try again in a minute.",
        )
        taken.append(f"global:rpm:{win['minute'][0]}")

        # 3. Per IP and per browser id, hourly and daily.
        if not body.bypass_user_limits:
            subjects = [f"ip:{body.ip}"] + ([f"cid:{body.client_id}"] if body.client_id else [])
            for subject in subjects:
                for window, limit in (("hour", s.rate_per_hour), ("day", s.rate_per_day)):
                    suffix, retry = win[window]
                    key = f"rl:{subject}:{window}:{suffix}"
                    await _hit(
                        key, limit, 3600 if window == "hour" else 86400, retry,
                        "rate_limited",
                        f"You've reached the limit of {limit} new questions per {window}. "
                        "Popular answers below still work.",
                    )
                    taken.append(key)
    except ApiError:
        # Undoing whatever this request already counted, except the failed counter
        # (which _hit rolled back itself).
        for key in taken:
            if key.startswith("spend:"):
                await store().incrby(key, -int(s.cost_estimate_usd * MICRO))
            else:
                await store().incrby(key, -1)
        raise

    return {"ok": True, "reserved_usd": s.cost_estimate_usd}


@app.post("/internal/settle", dependencies=[Depends(require_internal)])
async def settle(body: SettleIn) -> dict[str, Any]:
    """Replacing the reserved estimate with the real cost of the call."""
    delta = int(round((body.actual_usd - body.reserved_usd) * MICRO))
    day_key, month_key = _spend_keys(_now())
    if delta:
        await store().incrby(day_key, delta, ttl=2 * 86400)
        await store().incrby(month_key, delta, ttl=40 * 86400)
    return {"ok": True}


async def _count(key: str) -> int:
    return int(await store().get(key) or 0)


@app.get("/internal/status", dependencies=[Depends(require_internal)])
async def status(ip: str, client_id: str | None = None) -> dict[str, Any]:
    """How many new questions this visitor has left (both IP and browser count)."""
    s = get_settings()
    win = _windows(_now())
    subjects = [f"ip:{ip}"] + ([f"cid:{client_id}"] if client_id else [])
    left_hour = min([s.rate_per_hour - await _count(f"rl:{x}:hour:{win['hour'][0]}") for x in subjects])
    left_day = min([s.rate_per_day - await _count(f"rl:{x}:day:{win['day'][0]}") for x in subjects])
    return {
        "remaining_hour": max(0, left_hour),
        "remaining_day": max(0, left_day),
        "limit_hour": s.rate_per_hour,
        "limit_day": s.rate_per_day,
        "resets_in_seconds": win["hour"][1],
    }


@app.get("/admin/spend", dependencies=[Depends(require_admin)])
async def spend() -> dict[str, Any]:
    s = get_settings()
    day_key, month_key = _spend_keys(_now())
    return {
        "today_usd": round(await _count(day_key) / MICRO, 4),
        "month_usd": round(await _count(month_key) / MICRO, 4),
        "daily_cap_usd": s.daily_cap_usd,
        "monthly_cap_usd": s.monthly_cap_usd,
        "as_of": int(time.time()),
    }
