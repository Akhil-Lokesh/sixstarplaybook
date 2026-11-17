"""Running all five services in one process, each on its own port.

    python -m sixstar.run_all

Good for local development and for a single small always-on host. In
docker-compose each service runs in its own container instead.
"""
from __future__ import annotations

import asyncio
import os

import uvicorn

SERVICES = {
    "gateway": ("sixstar.gateway.app:app", int(os.environ.get("GATEWAY_PORT", 8000))),
    "answer": ("sixstar.answer.app:app", int(os.environ.get("ANSWER_PORT", 8001))),
    "guard": ("sixstar.guard.app:app", int(os.environ.get("GUARD_PORT", 8002))),
    "content": ("sixstar.content.app:app", int(os.environ.get("CONTENT_PORT", 8003))),
    "analytics": ("sixstar.analytics.app:app", int(os.environ.get("ANALYTICS_PORT", 8004))),
}


async def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    servers = []
    for name, (target, port) in SERVICES.items():
        # Only the gateway listens publicly when HOST is 0.0.0.0; the rest stay on loopback.
        bind = host if name == "gateway" else "127.0.0.1"
        config = uvicorn.Config(target, host=bind, port=port, log_level="info", proxy_headers=False)
        servers.append(uvicorn.Server(config))
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
