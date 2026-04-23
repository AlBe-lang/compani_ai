"""Unit tests for PeerReviewCoordinator — Part 7 Stage 2.

Focus areas:
  1. PeerReviewMode gating (OFF/ALL/CRITICAL, deps + duration)
  2. review_task happy path — APPROVE persisted, DNA feedback applied
  3. REQUEST_CHANGES severity → pending_rework flag set correctly
  4. REJECT → WorkSpace.set_status(FAILED) called
  5. LLM retry exhaustion → fallback metric recorded, None returned
  6. Reviewer selection (no reviewer available → None)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from application.peer_review import PeerReviewConfig, PeerReviewCoordinator, PeerReviewMode
from application.reviewer_selector import FixedWithKGFallbackSelector
from domain.contracts import PeerReviewDecision, PeerReviewSeverity, WorkStatus

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_workspace() -> MagicMock:
    mock = MagicMock()
    mock.set_status = AsyncMock()
    return mock


def _make_storage() -> MagicMock:
    mock = MagicMock()
    mock.save = AsyncMock()
    return mock


def _make_event_bus() -> MagicMock:
    mock = MagicMock()
    mock.subscribe = MagicMock()
    mock.publish = AsyncMock()
    return mock


def _make_llm(responses: list[str]) -> MagicMock:
    mock = MagicMock()
    it = iter(responses)

    async def _gen(*args: Any, **kwargs: Any) -> str:
        value = next(it)
        return value

    mock.generate = AsyncMock(side_effect=_gen)
    return mock


def _make_dna_manager() -> MagicMock:
    mock = MagicMock()
    mock.update_review_feedback = AsyncMock()
    return mock


def _make_coordinator(
    *,
    mode: PeerReviewMode = PeerReviewMode.ALL,
    critical_duration_sec: float = 60.0,
    workspace: MagicMock | None = None,
    storage: MagicMock | None = None,
    event_bus: MagicMock | None = None,
    llm: MagicMock | None = None,
    dna_manager: MagicMock | None = None,
    metrics: MagicMock | None = None,
) -> PeerReviewCoordinator:
    return PeerReviewCoordinator(
        workspace=workspace or _make_workspace(),
        storage=storage or _make_storage(),
        event_bus=event_bus or _make_event_bus(),
        llm=llm or _make_llm(['{"decision":"APPROVE","severity":"MINOR","comments":["ok"]}']),
        reviewer_model_by_role={
            "backend": "slm",
            "frontend": "slm",
            "mlops": "mlops-slm",
            "cto": "cto",
        },
        run_id="run_test",
        config=PeerReviewConfig(
            mode=mode,
            critical_duration_sec=critical_duration_sec,
            call_timeout_sec=0.5,
            max_retries=1,
            retry_interval_sec=0.0,
        ),
        selector=FixedWithKGFallbackSelector(knowledge_graph=None),
        dna_manager=dna_manager,
        metrics=metrics,
    )


def _base_payload(
    *,
    agent_id: str = "backend",
    task_id: str = "task_001",
    item_id: str = "wi_001",
    approach: str = "implemented FastAPI route",
    dependencies: list[str] | None = None,
    duration_sec: float = 10.0,
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "duration_sec": duration_sec,
        "result": {
            "task_id": task_id,
            "agent_id": agent_id,
            "approach": approach,
            "code": "",
            "files": [{"path": "main.py", "type": "python"}],
            "dependencies": dependencies or [],
            "setup_commands": [],
            "success": True,
        },
    }


# ------------------------------------------------------------------
# 1. Gating: PeerReviewMode
# ------------------------------------------------------------------


async def test_off_mode_never_reviews() -> None:
    coord = _make_coordinator(mode=PeerReviewMode.OFF)
    result = await coord.review_task(_base_payload())
    assert result is None


async def test_all_mode_reviews_every_task() -> None:
    coord = _make_coordinator(mode=PeerReviewMode.ALL)
    result = await coord.review_task(_base_payload(dependencies=[], duration_sec=1.0))
    assert result is not None
    assert result.decision is PeerReviewDecision.APPROVE


async def test_critical_mode_skips_short_no_dep_task() -> None:
    coord = _make_coordinator(mode=PeerReviewMode.CRITICAL, critical_duration_sec=60.0)
    result = await coord.review_task(_base_payload(dependencies=[], duration_sec=5.0))
    assert result is None


async def test_critical_mode_triggers_on_dependency() -> None:
    coord = _make_coordinator(mode=PeerReviewMode.CRITICAL)
    result = await coord.review_task(_base_payload(dependencies=["other_task"], duration_sec=5.0))
    assert result is not None


async def test_critical_mode_triggers_on_long_duration() -> None:
    coord = _make_coordinator(mode=PeerReviewMode.CRITICAL, critical_duration_sec=60.0)
    result = await coord.review_task(_base_payload(dependencies=[], duration_sec=120.0))
    assert result is not None


# ------------------------------------------------------------------
# 2. Happy path — APPROVE + DNA feedback + storage
# ------------------------------------------------------------------


async def test_approve_path_persists_and_feeds_dna() -> None:
    storage = _make_storage()
    dna = _make_dna_manager()
    coord = _make_coordinator(storage=storage, dna_manager=dna)

    result = await coord.review_task(_base_payload(agent_id="backend"))
    assert result is not None
    assert result.decision is PeerReviewDecision.APPROVE
    assert result.reviewer_agent_id == "frontend"  # fixed map backend→frontend

    saved_key, payload = storage.save.call_args[0]
    assert saved_key.startswith("peer_review:")
    assert payload["decision"] == "APPROVE"
    assert payload["author_agent_id"] == "backend"
    assert payload["reviewer_agent_id"] == "frontend"

    dna.update_review_feedback.assert_awaited_once()
    kwargs = dna.update_review_feedback.await_args.kwargs
    assert kwargs["reviewer_agent_id"] == "frontend"
    assert kwargs["author_agent_id"] == "backend"
    assert kwargs["decision"] is PeerReviewDecision.APPROVE


# ------------------------------------------------------------------
# 3. REQUEST_CHANGES — pending_rework by severity
# ------------------------------------------------------------------


async def test_request_changes_minor_does_not_set_pending_rework() -> None:
    llm = _make_llm(['{"decision":"REQUEST_CHANGES","severity":"MINOR","comments":["rename var"]}'])
    coord = _make_coordinator(llm=llm)
    result = await coord.review_task(_base_payload())
    assert result is not None
    assert result.decision is PeerReviewDecision.REQUEST_CHANGES
    assert result.severity is PeerReviewSeverity.MINOR
    assert result.pending_rework is False


async def test_request_changes_major_sets_pending_rework() -> None:
    llm = _make_llm(['{"decision":"REQUEST_CHANGES","severity":"MAJOR","comments":["slow query"]}'])
    coord = _make_coordinator(llm=llm)
    result = await coord.review_task(_base_payload())
    assert result is not None
    assert result.severity is PeerReviewSeverity.MAJOR
    assert result.pending_rework is True


async def test_request_changes_critical_sets_pending_rework() -> None:
    llm = _make_llm(
        ['{"decision":"REQUEST_CHANGES","severity":"CRITICAL","comments":["logic bug"]}']
    )
    coord = _make_coordinator(llm=llm)
    result = await coord.review_task(_base_payload())
    assert result is not None
    assert result.severity is PeerReviewSeverity.CRITICAL
    assert result.pending_rework is True


# ------------------------------------------------------------------
# 4. REJECT → workspace.set_status(FAILED)
# ------------------------------------------------------------------


async def test_reject_transitions_workitem_to_failed() -> None:
    llm = _make_llm(['{"decision":"REJECT","severity":"CRITICAL","comments":["abandon"]}'])
    workspace = _make_workspace()
    coord = _make_coordinator(llm=llm, workspace=workspace)
    result = await coord.review_task(_base_payload(item_id="wi_reject"))
    assert result is not None
    assert result.decision is PeerReviewDecision.REJECT
    workspace.set_status.assert_awaited_once_with("wi_reject", WorkStatus.FAILED)


async def test_approve_does_not_transition_status() -> None:
    workspace = _make_workspace()
    coord = _make_coordinator(workspace=workspace)
    await coord.review_task(_base_payload())
    workspace.set_status.assert_not_awaited()


# ------------------------------------------------------------------
# 5. LLM failure → retries exhausted → fallback metric, None
# ------------------------------------------------------------------


async def test_llm_returns_invalid_json_records_fallback_metric() -> None:
    llm = _make_llm(["not json 1", "not json 2", "not json 3"])
    metrics = MagicMock()
    metrics.record_fallback = MagicMock()
    coord = PeerReviewCoordinator(
        workspace=_make_workspace(),
        storage=_make_storage(),
        event_bus=_make_event_bus(),
        llm=llm,
        reviewer_model_by_role={"backend": "x", "frontend": "x", "mlops": "x", "cto": "x"},
        run_id="run_test",
        config=PeerReviewConfig(
            mode=PeerReviewMode.ALL,
            call_timeout_sec=0.5,
            max_retries=3,
            retry_interval_sec=0.0,
        ),
        selector=FixedWithKGFallbackSelector(knowledge_graph=None),
        metrics=metrics,
    )
    result = await coord.review_task(_base_payload())
    assert result is None
    assert llm.generate.call_count == 3
    metrics.record_fallback.assert_called_once()
    assert metrics.record_fallback.call_args.kwargs["component"] == "peer_review"


# ------------------------------------------------------------------
# 6. No reviewer available
# ------------------------------------------------------------------


async def test_unknown_author_role_skips_review() -> None:
    coord = _make_coordinator()
    payload = _base_payload(agent_id="stranger_agent")
    result = await coord.review_task(payload)
    assert result is None


# ------------------------------------------------------------------
# 7. Invalid decision value from LLM → retry then fail
# ------------------------------------------------------------------


async def test_unknown_decision_value_treated_as_parse_failure() -> None:
    # Single attempt, invalid decision → should return None
    llm = _make_llm(['{"decision":"NUKE","severity":"CRITICAL","comments":[]}'])
    coord = _make_coordinator(llm=llm)
    result = await coord.review_task(_base_payload())
    assert result is None


# ------------------------------------------------------------------
# 8. EventBus subscription (only when mode != OFF)
# ------------------------------------------------------------------


def test_subscribes_to_task_completed_when_mode_not_off() -> None:
    bus = _make_event_bus()
    _make_coordinator(mode=PeerReviewMode.ALL, event_bus=bus)
    bus.subscribe.assert_called_once()
    event_name, handler = bus.subscribe.call_args[0]
    assert event_name == "task.completed"
    assert callable(handler)


def test_does_not_subscribe_when_mode_off() -> None:
    bus = _make_event_bus()
    _make_coordinator(mode=PeerReviewMode.OFF, event_bus=bus)
    bus.subscribe.assert_not_called()
