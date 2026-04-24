"""E2E — CEO 대시보드 live 통합 검증.

원안 (세션 가이드 Stage 3): "실제 백엔드 연동 E2E 1개". 파이프라인 실행
대신 대시보드 전체 스택(HTTP REST + WebSocket + 브로드캐스터 + 설정 변경)
이 엔드투엔드로 동작하는지 검증.

Unit-level 테스트(tests/unit/test_dashboard_*.py)와 차이:
  * 여러 엔드포인트 + WebSocket 을 **한 세션** 에서 순차 검증
  * 실제 EventBus 인스턴스가 브로드캐스터에 연결된 상태
  * PATCH /api/config → 후속 /api/config GET 이 변경을 반영
  * WebSocket 이 snapshot 수신 → metrics_tick 도 tick 간격 내 도착

실제 uvicorn 서브프로세스 기동은 포트 충돌·플레이키니스 위험이 있어 이
테스트는 TestClient 기반으로 구성. "실행 중인 우리 백엔드에 프런트가
접속해도 되는가?" 를 증명하는 것이 목적이며, Ollama 는 호출하지 않으므로
pull 완료 전에도 실행 가능(@pytest.mark.slow 는 붙이지 않음).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from adapters.event_bus import InProcessEventBus
from application.agent_factory import SystemConfig
from interfaces.dashboard_api import DashboardDeps, create_app
from observability.metrics import MetricsCollector


@pytest.fixture
def live_client() -> tuple[TestClient, DashboardDeps]:
    """Wire a full dashboard stack with a real EventBus + MetricsCollector."""
    config = SystemConfig(dashboard_token="e2e-live-tok")
    bus = InProcessEventBus()
    deps = DashboardDeps(
        config=config,
        auth_token="e2e-live-tok",
        event_bus=bus,
        metrics=MetricsCollector(),
        poll_interval_sec=0.1,
    )
    return TestClient(create_app(deps, print_banner=False)), deps


def test_live_health_and_rest_auth_flow(live_client: tuple[TestClient, DashboardDeps]) -> None:
    """healthz no-auth + authenticated REST round-trip on every public endpoint."""
    client, _ = live_client

    # healthz — no auth required
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # All /api/* require auth
    for path in ("/api/run/current", "/api/agents/dna", "/api/metrics", "/api/config"):
        assert client.get(path).status_code == 401, f"{path} should require auth"

    headers = {"Authorization": "Bearer e2e-live-tok"}
    for path in ("/api/run/current", "/api/agents/dna", "/api/metrics", "/api/config"):
        r = client.get(path, headers=headers)
        assert r.status_code == 200, f"{path} should return 200 with valid token"


def test_live_config_patch_round_trip(live_client: tuple[TestClient, DashboardDeps]) -> None:
    """PATCH /api/config hot-reloadable → subsequent GET reflects the change."""
    client, _ = live_client
    headers = {"Authorization": "Bearer e2e-live-tok"}

    r = client.patch(
        "/api/config",
        headers=headers,
        json={"field": "peer_review_critical_duration_sec", "value": 45.5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["field"] == "peer_review_critical_duration_sec"
    assert body["category"] == "hot_reloadable"
    assert body["new_value"] == 45.5

    r = client.get("/api/config", headers=headers)
    assert r.status_code == 200
    fields_map = r.json()["fields"]
    assert fields_map["peer_review_critical_duration_sec"]["value"] == 45.5
    assert fields_map["peer_review_critical_duration_sec"]["category"] == "hot_reloadable"


def test_live_websocket_snapshot_and_tick(
    live_client: tuple[TestClient, DashboardDeps],
) -> None:
    """WebSocket yields snapshot on connect and at least one metrics_tick."""
    client, _ = live_client
    with client.websocket_connect("/ws/dashboard?token=e2e-live-tok") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "snapshot"
        assert "run_id" in first
        second = json.loads(ws.receive_text())
        assert second["type"] == "metrics_tick"
        assert "metrics" in second
