"""Wiring all five services together in one process for tests.

Service-to-service HTTP calls go through ASGI transports instead of sockets,
Claude is replaced by the offline fake, and every store is in memory.
"""
import os

os.environ.update({
    "APP_ENV": "test",
    "MOCK_LLM": "true",
    "REDIS_URL": "",
    "ADMIN_TOKEN": "test-admin",
    "INTERNAL_TOKEN": "test-internal",
    "RATE_LIMIT_PER_HOUR": "5",
    "RATE_LIMIT_PER_DAY": "8",
    "EDGE_REQUESTS_PER_MINUTE": "1000",
    "GUIDE_REFRESH_SECONDS": "0",
    "LLM_EFFORT": "low",
    "LLM_THINKING": "disabled",
    "DAILY_SPEND_CAP_USD": "25",
    "MONTHLY_SPEND_CAP_USD": "150",
})

import httpx2 as httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from sixstar.analytics import app as analytics_mod  # noqa: E402
from sixstar.answer import app as answer_mod  # noqa: E402
from sixstar.answer import llm  # noqa: E402
from sixstar.answer.mock_llm import FakeAsyncAnthropic  # noqa: E402
from sixstar.common.config import get_settings  # noqa: E402
from sixstar.common.store import MemoryStore  # noqa: E402
from sixstar.common.web import set_transport  # noqa: E402
from sixstar.content import app as content_mod  # noqa: E402
from sixstar.gateway import app as gateway_mod  # noqa: E402
from sixstar.guard import app as guard_mod  # noqa: E402


@pytest.fixture
def fake_llm():
    fake = FakeAsyncAnthropic()
    llm.set_client(fake)
    yield fake
    llm.set_client(None)


@pytest_asyncio.fixture
async def gateway(fake_llm):
    get_settings.cache_clear()
    for name, mod in (("answer", answer_mod), ("guard", guard_mod), ("content", content_mod),
                      ("analytics", analytics_mod)):
        set_transport(name, httpx.ASGITransport(app=mod.app))
    answer_mod.reset_state(MemoryStore("t:answer:"))
    guard_mod.reset_store(MemoryStore("t:guard:"))
    analytics_mod.reset_store(MemoryStore("t:analytics:"))
    gateway_mod.reset_store(MemoryStore("t:gateway:"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway_mod.app),
                                 base_url="http://gateway.test") as client:
        yield client
    for name in ("answer", "guard", "content", "analytics"):
        set_transport(name, None)


async def drain_background() -> None:
    """Waiting for the answer service's fire-and-forget calls (settle, analytics)."""
    import asyncio

    while answer_mod._bg_tasks:
        await asyncio.gather(*list(answer_mod._bg_tasks), return_exceptions=True)
