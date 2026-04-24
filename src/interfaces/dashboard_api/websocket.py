"""WebSocket endpoint + EventBus bridge — Part 8 Stage 2 (Q2).

Each client receives:
  1. an initial ``snapshot`` message (via snapshot.build_snapshot)
  2. live event pushes bridged from InProcessEventBus for 5 event types
  3. a periodic ``metrics_tick`` every ``poll_interval_sec`` seconds (Q2 hybrid)

Connection lifecycle:
  * Accept → token verify → send snapshot → register → forward events
  * Disconnect → unregister → cancel polling task

Broadcasts are best-effort; a slow/dead client is dropped rather than
blocking the event bus for every other subscriber.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from observability.logger import get_logger

from .auth import verify_ws
from .snapshot import build_snapshot

if TYPE_CHECKING:
    from .app import DashboardDeps

log = get_logger(__name__)

# Events bridged from InProcessEventBus to connected dashboard clients.
# Keep synchronised with adapters/shared_workspace.py and peer_review emitters.
_BRIDGED_EVENTS: tuple[str, ...] = (
    "work_item.updated",
    "task.completed",
    "blocking.detected",
    "work_item.reopened",
    "review.rework_requested",
)


class DashboardBroadcaster:
    """Fan-out hub between EventBus and connected WebSocket clients."""

    def __init__(self, deps: "DashboardDeps") -> None:
        self._deps = deps
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._subscribed = False

    def ensure_subscribed(self) -> None:
        """Wire EventBus handlers once per app lifetime."""
        if self._subscribed or self._deps.event_bus is None:
            return
        for event_name in _BRIDGED_EVENTS:
            self._deps.event_bus.subscribe(event_name, self._on_event)
        self._subscribed = True
        log.info("dashboard.ws.bridge_subscribed", events=list(_BRIDGED_EVENTS))

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)
        log.info("dashboard.ws.connected", total=len(self._clients))

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        log.info("dashboard.ws.disconnected", total=len(self._clients))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send to every connected client. Failed sends drop the client."""
        payload = json.dumps(message, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                if ws.client_state != WebSocketState.CONNECTED:
                    dead.append(ws)
                    continue
                await ws.send_text(payload)
            except Exception as exc:
                log.warning("dashboard.ws.send_error", detail=str(exc))
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    def _on_event(self, event_type: str, payload: Any) -> None:
        """EventBus handler. Schedules async broadcast so publish doesn't block."""
        envelope = {
            "type": "event",
            "event": event_type,
            "payload": payload,
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(envelope))
        except RuntimeError:
            log.warning("dashboard.ws.no_loop_on_event", event=event_type)


async def dashboard_websocket_endpoint(websocket: WebSocket, deps: "DashboardDeps") -> None:
    """FastAPI WebSocket entrypoint. Install via ``app.add_api_websocket_route``."""
    await websocket.accept()
    if not await verify_ws(websocket, deps.auth_token):
        return

    deps.broadcaster.ensure_subscribed()

    # 1) Initial snapshot — solves blank-screen on first connect (Q2 D 흡수)
    try:
        snapshot = await build_snapshot(deps)
        await websocket.send_text(json.dumps(snapshot, ensure_ascii=False, default=str))
    except Exception as exc:
        log.warning("dashboard.ws.snapshot_error", detail=str(exc))

    await deps.broadcaster.register(websocket)

    # 2) Start 5s metrics tick loop alongside event pushes (Q2 hybrid)
    tick_task = asyncio.create_task(_metrics_tick_loop(websocket, deps))
    try:
        while True:
            # Keep the connection alive; we ignore client messages beyond
            # the initial handshake (Stage 2 has no client → server commands
            # on WS; /settings mutations go through HTTP PATCH).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("dashboard.ws.loop_error", detail=str(exc))
    finally:
        tick_task.cancel()
        try:
            await tick_task
        except asyncio.CancelledError:
            pass
        await deps.broadcaster.unregister(websocket)


async def _metrics_tick_loop(websocket: WebSocket, deps: "DashboardDeps") -> None:
    """Push a ``metrics_tick`` every ``poll_interval_sec`` seconds.

    Stops cleanly when the WebSocket closes — see caller's ``finally`` block.
    """
    from .snapshot import _metrics_snapshot  # local import to avoid cycle

    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            await asyncio.sleep(deps.poll_interval_sec)
            # Sample memory before emitting (R-10A)
            if deps.metrics is not None:
                deps.metrics.sample_memory(deps.config.run_id)
            payload = {
                "type": "metrics_tick",
                "metrics": _metrics_snapshot(deps),
            }
            try:
                await websocket.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            except Exception:  # pragma: no cover — drop on send failure
                return
    except asyncio.CancelledError:
        raise
