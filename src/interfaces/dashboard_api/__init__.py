"""CEO Dashboard HTTP + WebSocket API (Part 8 Stage 2).

Entry points:
  * ``create_app(config, deps)`` — FastAPI app factory. Returns ``FastAPI``
    instance configured with routes, WebSocket endpoint, CORS, and token
    authentication middleware.
  * ``DashboardDeps`` — dependency container shared between routes, the
    snapshot builder, and the WebSocket bridge.

Runtime entry is ``main.py --dashboard`` which spins up uvicorn with the
composed app. When the user only runs ``main.py <request>`` (no flag) the
dashboard API is never imported, preserving the CLI-only experience.

Security posture (Q5 decision):
  * Token auto-generated per run (Jupyter-style). Printed to stderr at
    startup for the user to bookmark.
  * Binds 127.0.0.1 only (configurable via SystemConfig.dashboard_host).
  * CORS allows localhost/127.0.0.1 on any port (Flutter dev server support).

See Part 8 Stage 2 개발 일지(2).md §1–3 for full design rationale.
"""

from __future__ import annotations

from .app import DashboardDeps, create_app

__all__ = ["DashboardDeps", "create_app"]
