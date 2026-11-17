"""Calling Claude Haiku 5.5 with streaming, prompt caching and structured outputs."""
from __future__ import annotations

from typing import Any, AsyncIterator

import anthropic

from ..common.config import Settings
from .extract import AnswerStreamExtractor

_client: dict[str, Any] = {}


def get_client(settings: Settings) -> Any:
    """The Anthropic client, or the offline fake when MOCK_LLM=true."""
    if "c" not in _client:
        if settings.mock_llm:
            from .mock_llm import FakeAsyncAnthropic

            _client["c"] = FakeAsyncAnthropic()
        else:
            # Reads ANTHROPIC_API_KEY from the environment; never hardcode a key.
            _client["c"] = anthropic.AsyncAnthropic(max_retries=1, timeout=settings.llm_timeout_s)
    return _client["c"]


def set_client(client: Any | None) -> None:
    _client.clear()
    if client is not None:
        _client["c"] = client


def request_params(
    settings: Settings, system: list[dict[str, Any]], user_text: str, schema: dict[str, Any]
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": settings.max_output_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
        "output_config": {"effort": settings.effort, "format": {"type": "json_schema", "schema": schema}},
    }
    # Haiku 5.5 thinks by default; for short lookups thinking off at low effort is
    # cheaper and faster. LLM_THINKING=adaptive turns it back on.
    if settings.thinking == "disabled":
        params["thinking"] = {"type": "disabled"}
    return params


async def stream_answer(client: Any, params: dict[str, Any]) -> AsyncIterator[tuple[str, Any]]:
    """Yielding ("delta", text) for answer text as it arrives, then ("final", message)."""
    extractor = AnswerStreamExtractor()
    async with client.messages.stream(**params) as stream:
        async for chunk in stream.text_stream:
            piece = extractor.feed(chunk)
            if piece:
                yield "delta", piece
        final = await stream.get_final_message()
    yield "final", (final, extractor.text)


def cost_usd(usage: Any, settings: Settings) -> float:
    """Dollar cost of one call from its usage block."""
    if usage is None:
        return 0.0
    write_price = settings.price_cache_write_1h if settings.prompt_cache_ttl == "1h" else settings.price_cache_write_5m
    total = (
        (getattr(usage, "input_tokens", 0) or 0) * settings.price_input
        + (getattr(usage, "cache_read_input_tokens", 0) or 0) * settings.price_cache_read
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * write_price
        + (getattr(usage, "output_tokens", 0) or 0) * settings.price_output
    )
    return round(total / 1_000_000, 8)
