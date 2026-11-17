"""Key-value store used for caches, counters and leaderboards.

`RedisStore` works with any Redis, including Upstash (use its rediss:// URL).
`MemoryStore` is the local-dev fallback when REDIS_URL is empty. Each service
owns its own keys, so the in-memory fallback still behaves correctly when the
services run as separate processes.
"""
from __future__ import annotations

import logging
import time
from typing import Protocol

from .config import Settings, get_settings

log = logging.getLogger(__name__)


class Store(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool: ...
    async def delete(self, key: str) -> None: ...
    async def incrby(self, key: str, amount: int = 1, ttl: int | None = None) -> int: ...
    async def zincrby(self, key: str, member: str, amount: float = 1, ttl: int | None = None) -> float: ...
    async def ztop(self, key: str, n: int) -> list[tuple[str, float]]: ...
    async def lpush_trim(self, key: str, value: str, maxlen: int, ttl: int | None = None) -> None: ...
    async def lrange(self, key: str, start: int, stop: int) -> list[str]: ...
    async def ping(self) -> bool: ...


class MemoryStore:
    """In-process store with expiry; for local development and tests only."""

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix
        self._data: dict[str, object] = {}
        self._expiry: dict[str, float] = {}

    def _k(self, key: str) -> str:
        return self.prefix + key

    def _alive(self, k: str) -> bool:
        exp = self._expiry.get(k)
        if exp is not None and exp <= time.time():
            self._data.pop(k, None)
            self._expiry.pop(k, None)
            return False
        return k in self._data

    def _touch(self, k: str, ttl: int | None, only_if_new: bool) -> None:
        if ttl and (not only_if_new or k not in self._expiry):
            self._expiry[k] = time.time() + ttl

    async def get(self, key: str) -> str | None:
        k = self._k(key)
        return self._data[k] if self._alive(k) else None  # type: ignore[return-value]

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        k = self._k(key)
        if nx and self._alive(k):
            return False
        self._data[k] = value
        self._expiry.pop(k, None)
        self._touch(k, ttl, only_if_new=False)
        return True

    async def delete(self, key: str) -> None:
        k = self._k(key)
        self._data.pop(k, None)
        self._expiry.pop(k, None)

    async def incrby(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        k = self._k(key)
        current = int(self._data[k]) if self._alive(k) else 0  # type: ignore[arg-type]
        self._data[k] = current + amount
        self._touch(k, ttl, only_if_new=True)
        return current + amount

    async def zincrby(self, key: str, member: str, amount: float = 1, ttl: int | None = None) -> float:
        k = self._k(key)
        zset = self._data[k] if self._alive(k) else {}
        assert isinstance(zset, dict)
        zset[member] = zset.get(member, 0) + amount
        self._data[k] = zset
        self._touch(k, ttl, only_if_new=True)
        return zset[member]

    async def ztop(self, key: str, n: int) -> list[tuple[str, float]]:
        k = self._k(key)
        if not self._alive(k):
            return []
        zset = self._data[k]
        assert isinstance(zset, dict)
        return sorted(zset.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    async def lpush_trim(self, key: str, value: str, maxlen: int, ttl: int | None = None) -> None:
        k = self._k(key)
        items = self._data[k] if self._alive(k) else []
        assert isinstance(items, list)
        items.insert(0, value)
        del items[maxlen:]
        self._data[k] = items
        self._touch(k, ttl, only_if_new=True)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        k = self._k(key)
        if not self._alive(k):
            return []
        items = self._data[k]
        assert isinstance(items, list)
        return items[start : (None if stop == -1 else stop + 1)]

    async def ping(self) -> bool:
        return True


# Incrementing and setting a TTL only when the key has none, in one round trip.
_INCR_LUA = """
local v = redis.call('INCRBY', KEYS[1], ARGV[1])
if tonumber(ARGV[2]) > 0 and redis.call('TTL', KEYS[1]) == -1 then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return v
"""

_ZINCR_LUA = """
local v = redis.call('ZINCRBY', KEYS[1], ARGV[1], ARGV[2])
if tonumber(ARGV[3]) > 0 and redis.call('TTL', KEYS[1]) == -1 then
  redis.call('EXPIRE', KEYS[1], ARGV[3])
end
return v
"""


class RedisStore:
    def __init__(self, url: str, prefix: str = "") -> None:
        import redis.asyncio as redis  # imported lazily so tests without Redis still run

        self.prefix = prefix
        self.r = redis.from_url(url, decode_responses=True, health_check_interval=30)

    def _k(self, key: str) -> str:
        return self.prefix + key

    async def get(self, key: str) -> str | None:
        return await self.r.get(self._k(key))

    async def set(self, key: str, value: str, ttl: int | None = None, nx: bool = False) -> bool:
        result = await self.r.set(self._k(key), value, ex=ttl or None, nx=nx)
        return bool(result)

    async def delete(self, key: str) -> None:
        await self.r.delete(self._k(key))

    async def incrby(self, key: str, amount: int = 1, ttl: int | None = None) -> int:
        return int(await self.r.eval(_INCR_LUA, 1, self._k(key), amount, ttl or 0))

    async def zincrby(self, key: str, member: str, amount: float = 1, ttl: int | None = None) -> float:
        return float(await self.r.eval(_ZINCR_LUA, 1, self._k(key), amount, member, ttl or 0))

    async def ztop(self, key: str, n: int) -> list[tuple[str, float]]:
        rows = await self.r.zrevrange(self._k(key), 0, n - 1, withscores=True)
        return [(m, float(s)) for m, s in rows]

    async def lpush_trim(self, key: str, value: str, maxlen: int, ttl: int | None = None) -> None:
        k = self._k(key)
        async with self.r.pipeline(transaction=True) as pipe:
            pipe.lpush(k, value)
            pipe.ltrim(k, 0, maxlen - 1)
            if ttl:
                pipe.expire(k, ttl)
            await pipe.execute()

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        return await self.r.lrange(self._k(key), start, stop)

    async def ping(self) -> bool:
        try:
            return bool(await self.r.ping())
        except Exception:  # noqa: BLE001 - health checks report, never raise
            return False


def make_store(settings: Settings | None = None, namespace: str = "") -> Store:
    settings = settings or get_settings()
    prefix = settings.key_prefix + (f"{namespace}:" if namespace else "")
    if settings.redis_url:
        return RedisStore(settings.redis_url, prefix)
    if settings.is_prod:
        raise RuntimeError("REDIS_URL is required when APP_ENV=production")
    log.warning("REDIS_URL not set: using the in-memory store (local development only)")
    return MemoryStore(prefix)
