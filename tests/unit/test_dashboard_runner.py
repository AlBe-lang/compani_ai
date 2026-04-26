"""Tests for v1.1 demo run endpoints + RunManager — POST /api/run / cancel / SSE stream.

Subprocess 동작 자체는 mock 으로 격리. RunManager 통합 시나리오는 별도 e2e
또는 통합 테스트에서 다루는 게 적절(여기는 단위 단계).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi.testclient import TestClient

from application.agent_factory import SystemConfig
from interfaces.dashboard_api import DashboardDeps, create_app
from interfaces.dashboard_api.runner import RunManager, RunState


class _FakeRunManager:
    """Drop-in test double for :class:`RunManager`.

    Records calls and lets each test scenario pre-program responses without
    spawning real subprocesses.
    """

    def __init__(
        self,
        *,
        start_raises: BaseException | None = None,
        cancel_returns: bool = True,
    ) -> None:
        self.start_calls: list[str] = []
        self.cancel_calls = 0
        self.stream_calls = 0
        self._start_raises = start_raises
        self._cancel_returns = cancel_returns

    async def start(self, request: str) -> RunState:
        self.start_calls.append(request)
        if self._start_raises is not None:
            raise self._start_raises
        if not request.strip():
            raise ValueError("request must not be empty")
        return RunState(run_id="test1234", request=request, started_at=1.0, pid=4242)

    async def cancel(self) -> bool:
        self.cancel_calls += 1
        return self._cancel_returns

    async def stream(self) -> AsyncIterator[str]:
        self.stream_calls += 1
        yield 'event: run.start\ndata: {"run_id": "test1234"}\n\n'
        yield 'data: {"event": "cto.strategy.start"}\n\n'
        yield 'event: run.done\ndata: {"exit_code": 0}\n\n'


def _make_app(
    *,
    token: str = "tok",
    run_manager: object | None = None,
) -> tuple[TestClient, DashboardDeps]:
    config = SystemConfig(dashboard_token=token)
    deps = DashboardDeps(
        config=config,
        auth_token=token,
        run_manager=run_manager,  # type: ignore[arg-type]
    )
    return TestClient(create_app(deps, print_banner=False)), deps


def _auth(token: str = "tok") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------
# POST /api/run
# -----------------------------------------------------------------


def test_post_run_503_when_run_manager_missing() -> None:
    client, _ = _make_app(run_manager=None)
    resp = client.post("/api/run", headers=_auth(), json={"request": "Todo"})
    assert resp.status_code == 503
    assert "run manager" in resp.json()["detail"].lower()


def test_post_run_400_when_request_empty() -> None:
    fake = _FakeRunManager()
    client, _ = _make_app(run_manager=fake)
    resp = client.post("/api/run", headers=_auth(), json={"request": "   "})
    assert resp.status_code == 400
    # FakeRunManager 는 호출되지 않아야 함 — route 단계에서 차단.
    assert fake.start_calls == []


def test_post_run_409_when_already_running() -> None:
    fake = _FakeRunManager(start_raises=RuntimeError("another run is in progress"))
    client, _ = _make_app(run_manager=fake)
    resp = client.post("/api/run", headers=_auth(), json={"request": "Todo"})
    assert resp.status_code == 409
    assert "in progress" in resp.json()["detail"]


def test_post_run_200_returns_run_id_and_pid() -> None:
    fake = _FakeRunManager()
    client, _ = _make_app(run_manager=fake)
    resp = client.post("/api/run", headers=_auth(), json={"request": "Todo"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "test1234"
    assert body["pid"] == 4242
    assert fake.start_calls == ["Todo"]


def test_post_run_401_without_token() -> None:
    fake = _FakeRunManager()
    client, _ = _make_app(run_manager=fake)
    resp = client.post("/api/run", json={"request": "Todo"})
    assert resp.status_code == 401


# -----------------------------------------------------------------
# POST /api/cancel
# -----------------------------------------------------------------


def test_post_cancel_503_when_run_manager_missing() -> None:
    client, _ = _make_app(run_manager=None)
    resp = client.post("/api/cancel", headers=_auth())
    assert resp.status_code == 503


def test_post_cancel_returns_cancelled_flag() -> None:
    fake = _FakeRunManager(cancel_returns=True)
    client, _ = _make_app(run_manager=fake)
    resp = client.post("/api/cancel", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": True}
    assert fake.cancel_calls == 1


def test_post_cancel_returns_false_when_no_active_run() -> None:
    fake = _FakeRunManager(cancel_returns=False)
    client, _ = _make_app(run_manager=fake)
    resp = client.post("/api/cancel", headers=_auth())
    assert resp.status_code == 200
    assert resp.json() == {"cancelled": False}


# -----------------------------------------------------------------
# GET /api/run/stream  (SSE)
# -----------------------------------------------------------------


def test_get_stream_503_when_run_manager_missing() -> None:
    client, _ = _make_app(run_manager=None)
    resp = client.get("/api/run/stream", params={"token": "tok"})
    assert resp.status_code == 503


def test_get_stream_401_with_wrong_token() -> None:
    fake = _FakeRunManager()
    client, _ = _make_app(run_manager=fake)
    resp = client.get("/api/run/stream", params={"token": "WRONG"})
    assert resp.status_code == 401
    assert fake.stream_calls == 0


def test_get_stream_yields_sse_frames() -> None:
    fake = _FakeRunManager()
    client, _ = _make_app(run_manager=fake)
    with client.stream("GET", "/api/run/stream", params={"token": "tok"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.read().decode("utf-8")
    assert "event: run.start" in body
    assert "cto.strategy.start" in body
    assert "event: run.done" in body
    assert fake.stream_calls == 1


# -----------------------------------------------------------------
# RunManager unit (no subprocess — direct attribute / state checks)
# -----------------------------------------------------------------


def test_run_manager_rejects_empty_request() -> None:
    rm = RunManager()

    async def _go() -> None:
        try:
            await rm.start("   ")
        except ValueError as exc:
            assert "must not be empty" in str(exc)
            return
        raise AssertionError("expected ValueError")

    asyncio.run(_go())


def test_run_manager_is_running_false_before_start() -> None:
    rm = RunManager()
    assert rm.is_running() is False
    assert rm.current is None


def test_run_manager_cancel_returns_false_when_no_run() -> None:
    rm = RunManager()

    async def _go() -> bool:
        return await rm.cancel()

    assert asyncio.run(_go()) is False


def test_run_manager_stream_emits_empty_frame_when_no_run() -> None:
    rm = RunManager()

    async def _go() -> list[str]:
        out: list[str] = []
        async for frame in rm.stream():
            out.append(frame)
        return out

    frames = asyncio.run(_go())
    assert len(frames) == 1
    assert "run.empty" in frames[0]
