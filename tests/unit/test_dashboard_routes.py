"""Tests for dashboard HTTP routes — Part 8 Stage 2."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from application.agent_factory import EmbeddingPreset, SystemConfig
from application.concurrency import LLMConcurrencyLimiter
from application.peer_review import PeerReviewMode
from interfaces.dashboard_api import DashboardDeps, create_app
from observability.metrics import MetricsCollector


def _make_app(
    *,
    token: str = "tok",
    workspace: MagicMock | None = None,
    dna_manager: MagicMock | None = None,
    metrics: MetricsCollector | None = None,
    limiter: LLMConcurrencyLimiter | None = None,
) -> tuple[TestClient, DashboardDeps]:
    config = SystemConfig(dashboard_token=token)
    deps = DashboardDeps(
        config=config,
        auth_token=token,
        workspace=workspace,
        dna_manager=dna_manager,
        metrics=metrics,
        limiter=limiter,
    )
    return TestClient(create_app(deps, print_banner=False)), deps


def _auth_headers(token: str = "tok") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_get_current_run_returns_config_summary() -> None:
    client, deps = _make_app()
    resp = client.get("/api/run/current", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == deps.config.run_id
    assert data["config_summary"]["cto_model"] == deps.config.cto_model


def test_get_agents_dna_empty_when_no_manager() -> None:
    client, _ = _make_app()
    resp = client.get("/api/agents/dna", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_metrics_available_flag_false_without_collector() -> None:
    client, _ = _make_app()
    resp = client.get("/api/metrics", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_get_metrics_with_collector() -> None:
    metrics = MetricsCollector()
    client, deps = _make_app(metrics=metrics)
    metrics.record_task(deps.config.run_id, "t1", "backend", success=True, duration_sec=1.0)
    resp = client.get("/api/metrics", headers=_auth_headers())
    data = resp.json()
    assert data["available"] is True
    assert data["total_tasks"] == 1
    assert data["success_count"] == 1


def test_get_config_returns_per_field_metadata() -> None:
    client, _ = _make_app()
    resp = client.get("/api/config", headers=_auth_headers())
    data = resp.json()
    fields_data = data["fields"]
    # Hot-reloadable field
    assert fields_data["peer_review_mode"]["category"] == "hot_reloadable"
    assert "options" in fields_data["peer_review_mode"]
    # Destructive field
    assert fields_data["embedding_preset"]["category"] == "destructive"
    # Restart-required field
    assert fields_data["cto_model"]["category"] == "restart_required"
    # Sensitive masked
    assert fields_data["dashboard_token"].get("sensitive") is True


def test_patch_config_hot_reloadable_succeeds_without_confirm() -> None:
    client, deps = _make_app()
    resp = client.patch(
        "/api/config",
        headers=_auth_headers(),
        json={"field": "peer_review_mode", "value": "all"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["category"] == "hot_reloadable"
    assert deps.config.peer_review_mode is PeerReviewMode.ALL


def test_patch_config_destructive_without_confirm_rejected() -> None:
    client, _ = _make_app()
    resp = client.patch(
        "/api/config",
        headers=_auth_headers(),
        json={"field": "embedding_preset", "value": EmbeddingPreset.MINILM_FAST.value},
    )
    assert resp.status_code == 400
    assert "destructive" in resp.json()["detail"]


def test_patch_config_destructive_with_confirm_accepted() -> None:
    client, deps = _make_app()
    resp = client.patch(
        "/api/config",
        headers=_auth_headers(),
        json={
            "field": "embedding_preset",
            "value": EmbeddingPreset.MINILM_FAST.value,
            "confirm": True,
        },
    )
    assert resp.status_code == 200
    assert deps.config.embedding_preset is EmbeddingPreset.MINILM_FAST


def test_patch_config_unknown_field_returns_400() -> None:
    client, _ = _make_app()
    resp = client.patch(
        "/api/config",
        headers=_auth_headers(),
        json={"field": "nonexistent_field", "value": 1},
    )
    assert resp.status_code == 400


def test_patch_config_invalid_enum_returns_400() -> None:
    client, _ = _make_app()
    resp = client.patch(
        "/api/config",
        headers=_auth_headers(),
        json={"field": "peer_review_mode", "value": "nonexistent_mode"},
    )
    assert resp.status_code == 400


def test_patch_config_concurrency_update_propagates_to_limiter() -> None:
    limiter = LLMConcurrencyLimiter()
    assert limiter.config == {"cto": 1, "slm": 1, "mlops": 1, "total": 2}
    client, _ = _make_app(limiter=limiter)
    resp = client.patch(
        "/api/config",
        headers=_auth_headers(),
        json={"field": "llm_concurrency_slm", "value": 2},
    )
    assert resp.status_code == 200
    assert limiter.config["slm"] == 2


def test_get_environment_includes_memory_and_embedding_state() -> None:
    client, _ = _make_app()
    resp = client.get("/api/environment", headers=_auth_headers())
    data = resp.json()
    assert "total_memory_gb" in data
    assert "can_use_e5_large" in data
    assert "current_embedding_preset" in data
