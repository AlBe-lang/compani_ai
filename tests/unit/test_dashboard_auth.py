"""Tests for dashboard token auth — Part 8 Stage 2 (Q5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from application.agent_factory import SystemConfig
from interfaces.dashboard_api import DashboardDeps, create_app
from interfaces.dashboard_api.auth import _constant_time_equals


def _make_app(token: str = "correct-token-abc") -> tuple[TestClient, str]:
    config = SystemConfig(dashboard_token=token)
    deps = DashboardDeps(config=config, auth_token=token)
    app = create_app(deps, print_banner=False)
    return TestClient(app), token


def test_healthz_does_not_require_auth() -> None:
    client, _ = _make_app()
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_api_requires_token() -> None:
    client, _ = _make_app()
    resp = client.get("/api/run/current")
    assert resp.status_code == 401


def test_api_accepts_bearer_token() -> None:
    client, token = _make_app()
    resp = client.get(
        "/api/run/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_api_accepts_query_token() -> None:
    client, token = _make_app()
    resp = client.get(f"/api/run/current?token={token}")
    assert resp.status_code == 200


def test_api_rejects_wrong_token() -> None:
    client, _ = _make_app()
    resp = client.get("/api/run/current?token=wrong")
    assert resp.status_code == 401


def test_constant_time_equals_same_string() -> None:
    assert _constant_time_equals("abc", "abc") is True


def test_constant_time_equals_different() -> None:
    assert _constant_time_equals("abc", "abd") is False


def test_constant_time_equals_different_length() -> None:
    assert _constant_time_equals("abc", "abcd") is False


def test_constant_time_equals_empty() -> None:
    assert _constant_time_equals("", "abc") is False
    assert _constant_time_equals("", "") is True
