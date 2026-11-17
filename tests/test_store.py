"""The same behavior checks against the in-memory store and a real Redis (if installed)."""
import asyncio
import shutil
import socket
import subprocess
import time

import pytest
import pytest_asyncio

from sixstar.common.store import MemoryStore, RedisStore


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def redis_url():
    if not shutil.which("redis-server"):
        pytest.skip("redis-server not installed")
    port = _free_port()
    proc = subprocess.Popen(["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()


@pytest_asyncio.fixture(params=["memory", "redis"])
async def store(request):
    if request.param == "memory":
        yield MemoryStore("test:")
    else:
        s = RedisStore(request.getfixturevalue("redis_url"), f"test{time.time_ns()}:")
        yield s
        await s.r.aclose()


async def test_get_set_nx_delete(store):
    assert await store.get("a") is None
    assert await store.set("a", "1") is True
    assert await store.set("a", "2", nx=True) is False
    assert await store.get("a") == "1"
    await store.delete("a")
    assert await store.get("a") is None


async def test_incr_with_ttl_and_expiry(store):
    assert await store.incrby("c", 5, ttl=1) == 5
    assert await store.incrby("c", -2, ttl=1) == 3
    await asyncio.sleep(1.2)
    assert await store.get("c") is None


async def test_sorted_set_and_list(store):
    await store.zincrby("z", "a", 1, ttl=60)
    await store.zincrby("z", "b", 3, ttl=60)
    await store.zincrby("z", "a", 1, ttl=60)
    assert await store.ztop("z", 5) == [("b", 3.0), ("a", 2.0)]
    for i in range(5):
        await store.lpush_trim("l", str(i), maxlen=3)
    assert await store.lrange("l", 0, -1) == ["4", "3", "2"]
    assert await store.ping()
