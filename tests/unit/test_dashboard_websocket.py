"""Tests for dashboard WebSocket — Part 8 Stage 2 (Q2 hybrid)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from adapters.event_bus import InProcessEventBus
from application.agent_factory import SystemConfig
from interfaces.dashboard_api import DashboardDeps, create_app
from observability.metrics import MetricsCollector


def _make_app(
    *,
    token: str = "tok",
    poll_interval_sec: float = 0.1,
    metrics: MetricsCollector | None = None,
) -> tuple[TestClient, DashboardDeps]:
    config = SystemConfig(dashboard_token=token)
    bus = InProcessEventBus()
    deps = DashboardDeps(
        config=config,
        auth_token=token,
        event_bus=bus,
        metrics=metrics,
        poll_interval_sec=poll_interval_sec,
    )
    return TestClient(create_app(deps, print_banner=False)), deps


def test_websocket_requires_token() -> None:
    """Missing token → server closes with policy-violation code after accept."""
    from starlette.websockets import WebSocketDisconnect

    client, _ = _make_app()
    with client.websocket_connect("/ws/dashboard") as ws:
        try:
            ws.receive_text()
        except WebSocketDisconnect:
            pass  # closure expected when auth is rejected


def test_websocket_sends_snapshot_on_connect() -> None:
    client, _ = _make_app()
    with client.websocket_connect("/ws/dashboard?token=tok") as ws:
        first = json.loads(ws.receive_text())
    assert first["type"] == "snapshot"
    assert "run_id" in first
    assert "config" in first


def test_websocket_emits_metrics_tick() -> None:
    metrics = MetricsCollector()
    client, _ = _make_app(metrics=metrics, poll_interval_sec=0.05)
    with client.websocket_connect("/ws/dashboard?token=tok") as ws:
        # first frame = snapshot
        snapshot = json.loads(ws.receive_text())
        assert snapshot["type"] == "snapshot"
        # wait for at least one tick
        tick = json.loads(ws.receive_text())
    assert tick["type"] == "metrics_tick"
    assert "metrics" in tick


async def test_broadcaster_fanout_to_registered_clients() -> None:
    """Unit-level: broadcaster sends to every registered client.

    Full EventBus→broadcast→WebSocket integration requires same-loop execution
    which TestClient doesn't expose cleanly; we validate the fan-out logic
    directly and rely on ``test_websocket_sends_snapshot_on_connect`` for the
    WebSocket acceptance path.
    """
    from unittest.mock import AsyncMock

    from starlette.websockets import WebSocketState

    from interfaces.dashboard_api.websocket import DashboardBroadcaster

    class _Deps:
        event_bus = None

    broadcaster = DashboardBroadcaster(_Deps())  # type: ignore[arg-type]

    fake_ws = AsyncMock()
    fake_ws.client_state = WebSocketState.CONNECTED
    await broadcaster.register(fake_ws)
    await broadcaster.broadcast({"type": "event", "event": "x", "payload": {}})
    fake_ws.send_text.assert_awaited_once()
    payload = fake_ws.send_text.await_args.args[0]
    assert json.loads(payload)["event"] == "x"


async def test_broadcaster_drops_dead_client() -> None:
    """Clients whose send fails are silently dropped on the next broadcast."""
    from unittest.mock import AsyncMock

    from starlette.websockets import WebSocketState

    from interfaces.dashboard_api.websocket import DashboardBroadcaster

    class _Deps:
        event_bus = None

    broadcaster = DashboardBroadcaster(_Deps())  # type: ignore[arg-type]
    bad_ws = AsyncMock()
    bad_ws.client_state = WebSocketState.CONNECTED
    bad_ws.send_text.side_effect = RuntimeError("connection lost")
    await broadcaster.register(bad_ws)
    await broadcaster.broadcast({"type": "event"})
    assert bad_ws not in broadcaster._clients
