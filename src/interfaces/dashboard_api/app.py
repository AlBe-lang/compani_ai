"""FastAPI app factory — Part 8 Stage 2.

Assembles HTTP routes, WebSocket endpoint, CORS, and auth-token printing
into a single ``FastAPI`` instance. The factory is dependency-injected via
:class:`DashboardDeps` so tests can swap in mocks without a full Ollama stack.

Token is printed to **stderr** (not stdout) so it doesn't pollute piped
output — mirrors Jupyter Notebook's startup banner behaviour.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from observability.logger import get_logger

from .routes import create_router
from .websocket import DashboardBroadcaster, dashboard_websocket_endpoint

if TYPE_CHECKING:
    from application.agent_factory import SystemConfig
    from application.concurrency import LLMConcurrencyLimiter
    from application.dna_manager import DNAManager
    from domain.ports import EventBusPort, WorkSpacePort
    from observability.metrics import MetricsCollector

    from .runner import RunManager

log = get_logger(__name__)

_DEFAULT_POLL_INTERVAL_SEC = 5.0
_DEFAULT_CORS_ORIGINS = (
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    # Flutter dev server defaults to any ephemeral port — wildcard via regex
    # below so we don't forbid it.
)
_DEFAULT_CORS_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1)(:[0-9]+)?$"


@dataclass
class DashboardDeps:
    """Dependency container injected into routes/WebSocket/snapshot.

    Only ``config`` is required; the rest are optional so tests and minimal
    demos can stand up a bare dashboard without full pipeline wiring.
    """

    config: "SystemConfig"
    auth_token: str = field(default_factory=lambda: uuid.uuid4().hex)
    workspace: "WorkSpacePort | None" = None
    dna_manager: "DNAManager | None" = None
    metrics: "MetricsCollector | None" = None
    event_bus: "EventBusPort | None" = None
    limiter: "LLMConcurrencyLimiter | None" = None
    # v1.1 demo entry — POST /api/run lifecycle. Optional so unit tests and
    # observation-only deployments don't need a running pipeline.
    run_manager: "RunManager | None" = None
    poll_interval_sec: float = _DEFAULT_POLL_INTERVAL_SEC
    # Internal — assigned by create_app() so websocket endpoint can reach it.
    broadcaster: "DashboardBroadcaster" = field(init=False)

    def __post_init__(self) -> None:
        self.broadcaster = DashboardBroadcaster(self)


def create_app(
    deps: DashboardDeps,
    *,
    print_banner: bool = True,
) -> FastAPI:
    """Produce a configured FastAPI application.

    The ``print_banner`` switch emits the Jupyter-style token URL to stderr
    on startup (disabled in tests so output stays clean).
    """
    app = FastAPI(
        title="CompaniAI CEO Dashboard",
        version="0.8.2",
        description=(
            "Part 8 Stage 2 — runtime observation + settings UI " "for the multi-agent pipeline."
        ),
    )

    # CORS — localhost only (Q5 decision)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_DEFAULT_CORS_ORIGINS),
        allow_origin_regex=_DEFAULT_CORS_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(create_router(deps))

    @app.websocket("/ws/dashboard")
    async def _dashboard_ws(websocket: WebSocket) -> None:
        await dashboard_websocket_endpoint(websocket, deps)

    @app.get("/healthz")
    async def _healthz() -> dict[str, str]:
        return {"status": "ok", "run_id": deps.config.run_id}

    # Token URL banner
    host = getattr(deps.config, "dashboard_host", "127.0.0.1")
    port = getattr(deps.config, "dashboard_port", 8000)
    if print_banner:
        _emit_banner(host, port, deps.auth_token)

    return app


def _emit_banner(host: str, port: int, token: str) -> None:
    url = f"http://{host}:{port}/?token={token}"
    # stderr so it doesn't pollute programmatic stdout consumers
    print(file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print("  CompaniAI CEO Dashboard ready", file=sys.stderr)
    print(f"  {url}", file=sys.stderr)
    print("  (Bookmark this URL — the token regenerates each run.)", file=sys.stderr)
    print("=" * 66, file=sys.stderr)
    print(file=sys.stderr)
