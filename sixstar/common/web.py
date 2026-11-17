"""FastAPI helpers shared by every service: errors, health, internal auth, HTTP clients."""
from __future__ import annotations

import hmac
import logging
from typing import Any, Callable

import httpx2 as httpx
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import get_settings

log = logging.getLogger(__name__)


class ApiError(Exception):
    """An error with a stable machine-readable code, returned as {"error": {...}}."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}

    def response(self) -> JSONResponse:
        headers = {}
        if "retry_after" in self.extra:
            headers["Retry-After"] = str(int(self.extra["retry_after"]))
        return JSONResponse(self.body(), status_code=self.status, headers=headers)


def make_app(name: str, health: Callable[[], Any] | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s {name} %(levelname)s %(message)s")
    app = FastAPI(title=f"Six Star Playbook {name}", version="1.0.0")

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return exc.response()

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(str(e.get("msg")) for e in exc.errors()[:3])
        return ApiError(422, "invalid_request", detail or "Invalid request").response()

    @app.exception_handler(httpx.TransportError)
    async def _downstream_unreachable(_: Request, exc: httpx.TransportError) -> JSONResponse:
        # Another service is down or timed out. New questions stop (fail closed);
        # the player gets a plain retry message instead of a 500.
        log.error("downstream service unreachable: %r", exc)
        return ApiError(503, "unavailable", "Answers are briefly unavailable. Try again in a minute.",
                        retry_after=30).response()

    @app.get("/health")
    async def _health() -> dict[str, Any]:
        extra = await health() if health else {}
        return {"service": name, "status": "ok", **(extra or {})}

    return app


async def require_internal(x_internal_token: str | None = Header(default=None)) -> None:
    """Rejecting calls to /internal routes that don't carry the shared service token."""
    expected = get_settings().internal_token
    if not expected or not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise ApiError(403, "forbidden", "Internal endpoint")


async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_token
    if not expected or not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise ApiError(403, "forbidden", "Admin token required")


def is_admin(token: str | None) -> bool:
    expected = get_settings().admin_token
    return bool(expected and token and hmac.compare_digest(token, expected))


# Service-to-service HTTP clients. Tests swap in ASGI transports so all five
# services run in one process without opening ports.
_transports: dict[str, httpx.AsyncBaseTransport] = {}
_clients: dict[str, httpx.AsyncClient] = {}


def set_transport(service: str, transport: httpx.AsyncBaseTransport | None) -> None:
    if transport is None:
        _transports.pop(service, None)
    else:
        _transports[service] = transport
    _clients.pop(service, None)


def service_client(service: str) -> httpx.AsyncClient:
    if service not in _clients:
        settings = get_settings()
        base = {
            "answer": settings.answer_url,
            "guard": settings.guard_url,
            "content": settings.content_url,
            "analytics": settings.analytics_url,
        }[service]
        _clients[service] = httpx.AsyncClient(
            base_url=base,
            headers={"X-Internal-Token": settings.internal_token},
            timeout=httpx.Timeout(10.0, read=settings.llm_timeout_s + 15),
            transport=_transports.get(service),
        )
    return _clients[service]


async def raise_for_error(resp: httpx.Response) -> None:
    """Turning a downstream {"error": ...} response back into an ApiError."""
    if resp.status_code < 400:
        return
    try:
        await resp.aread()
        err = resp.json().get("error", {})
    except Exception:  # noqa: BLE001
        err = {}
    code = err.pop("code", "unavailable")
    message = err.pop("message", "Answers are briefly unavailable. Try again in a minute.")
    raise ApiError(resp.status_code, code, message, **err)
