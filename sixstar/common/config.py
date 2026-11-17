"""Settings shared by every service, read from environment variables.

Every value has a safe local default, so `python -m sixstar.run_all` works with
no .env at all (mock Claude client, in-memory store). See .env.example.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Environment and wiring
    env: str = field(default_factory=lambda: _str("APP_ENV", "dev"))
    redis_url: str = field(default_factory=lambda: _str("REDIS_URL"))
    key_prefix: str = field(default_factory=lambda: _str("REDIS_KEY_PREFIX", "ssp:"))
    gateway_url: str = field(default_factory=lambda: _str("GATEWAY_URL", "http://127.0.0.1:8000"))
    answer_url: str = field(default_factory=lambda: _str("ANSWER_URL", "http://127.0.0.1:8001"))
    guard_url: str = field(default_factory=lambda: _str("GUARD_URL", "http://127.0.0.1:8002"))
    content_url: str = field(default_factory=lambda: _str("CONTENT_URL", "http://127.0.0.1:8003"))
    analytics_url: str = field(default_factory=lambda: _str("ANALYTICS_URL", "http://127.0.0.1:8004"))
    internal_token: str = field(default_factory=lambda: _str("INTERNAL_TOKEN", "dev-internal-token"))
    admin_token: str = field(default_factory=lambda: _str("ADMIN_TOKEN"))
    cors_origins: list[str] = field(
        default_factory=lambda: _list(
            "CORS_ORIGINS",
            ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:8080"],
        )
    )
    trust_proxy_headers: bool = field(default_factory=lambda: _bool("TRUST_PROXY_HEADERS", False))

    # Claude
    model: str = field(default_factory=lambda: _str("ANTHROPIC_MODEL", "claude-haiku-5-5"))
    effort: str = field(default_factory=lambda: _str("LLM_EFFORT", "low"))
    thinking: str = field(default_factory=lambda: _str("LLM_THINKING", "disabled"))
    max_output_tokens: int = field(default_factory=lambda: _int("MAX_OUTPUT_TOKENS", 700))
    prompt_cache_ttl: str = field(default_factory=lambda: _str("PROMPT_CACHE_TTL", "1h"))
    mock_llm: bool = field(default_factory=lambda: _bool("MOCK_LLM", False))
    llm_timeout_s: float = field(default_factory=lambda: _float("LLM_TIMEOUT_SECONDS", 30.0))

    # Per-user and global limits
    rate_per_hour: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_HOUR", 10))
    rate_per_day: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_DAY", 30))
    global_ai_rpm: int = field(default_factory=lambda: _int("GLOBAL_AI_REQUESTS_PER_MINUTE", 300))
    edge_rpm: int = field(default_factory=lambda: _int("EDGE_REQUESTS_PER_MINUTE", 120))

    # Spend caps (US dollars)
    daily_cap_usd: float = field(default_factory=lambda: _float("DAILY_SPEND_CAP_USD", 25.0))
    monthly_cap_usd: float = field(default_factory=lambda: _float("MONTHLY_SPEND_CAP_USD", 150.0))
    cost_estimate_usd: float = field(default_factory=lambda: _float("COST_ESTIMATE_PER_CALL_USD", 0.002))

    # Prices per million tokens (Claude Haiku 5.5, prompts up to 100K tokens)
    price_input: float = field(default_factory=lambda: _float("PRICE_INPUT_PER_MTOK", 0.10))
    price_output: float = field(default_factory=lambda: _float("PRICE_OUTPUT_PER_MTOK", 0.50))
    price_cache_read: float = field(default_factory=lambda: _float("PRICE_CACHE_READ_PER_MTOK", 0.01))
    price_cache_write_5m: float = field(default_factory=lambda: _float("PRICE_CACHE_WRITE_5M_PER_MTOK", 0.125))
    price_cache_write_1h: float = field(default_factory=lambda: _float("PRICE_CACHE_WRITE_1H_PER_MTOK", 0.20))

    # Answers
    answer_cache_ttl_s: int = field(default_factory=lambda: _int("ANSWER_CACHE_TTL_SECONDS", 86400))
    answer_page_ttl_s: int = field(default_factory=lambda: _int("ANSWER_PAGE_TTL_SECONDS", 30 * 86400))
    question_max_chars: int = field(default_factory=lambda: _int("QUESTION_MAX_CHARS", 300))

    # Content
    guide_path: str = field(default_factory=lambda: _str("GUIDE_PATH", str(ROOT / "guide" / "guide.md")))
    data_dir: str = field(default_factory=lambda: _str("DATA_DIR", str(ROOT / "data")))
    exclude_sections: list[str] = field(default_factory=lambda: _list("GUIDE_EXCLUDE_SECTIONS", ["site-name-ideas"]))
    guide_refresh_s: int = field(default_factory=lambda: _int("GUIDE_REFRESH_SECONDS", 60))
    site_url: str = field(default_factory=lambda: _str("SITE_URL", "https://sixstarplaybook.com"))

    # Analytics
    analytics_salt: str = field(default_factory=lambda: _str("ANALYTICS_SALT", "dev-salt-change-me"))

    @property
    def is_prod(self) -> bool:
        return self.env.lower() in ("prod", "production")

    def __post_init__(self) -> None:
        if self.is_prod and (not self.internal_token or self.internal_token == "dev-internal-token"):
            raise RuntimeError("Set INTERNAL_TOKEN to a long random value when APP_ENV=production")
        if self.is_prod and self.analytics_salt == "dev-salt-change-me":
            raise RuntimeError("Set ANALYTICS_SALT to a random value when APP_ENV=production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
