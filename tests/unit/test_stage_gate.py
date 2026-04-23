"""Unit tests for StageGateMeeting."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.stage_gate import GateConfig, GateVerdict, StageGateMeeting
from domain.contracts import ReviewDecision, WorkItem, WorkStatus
from domain.contracts.review_result import ReviewResult

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_work_item(
    status: WorkStatus = WorkStatus.DONE,
    duration_sec: float = 10.0,
    agent_id: str = "backend",
    item_id: str = "wi_001",
) -> WorkItem:
    now = _utc_now()
    created = now - timedelta(seconds=duration_sec)
    return WorkItem(
        id=item_id,
        task_id="task_001",
        agent_id=agent_id,
        status=status,
        result=None,
        created_at=created,
        updated_at=now,
    )


def _make_cto(
    decision: ReviewDecision = ReviewDecision.REPLAN, reason: str = "needs rework"
) -> MagicMock:
    cto = MagicMock()
    cto.review_progress = AsyncMock(return_value=ReviewResult(decision=decision, reason=reason))
    return cto


def _make_storage() -> MagicMock:
    storage = MagicMock()
    storage.save = AsyncMock()
    return storage


def _make_event_bus() -> MagicMock:
    bus = MagicMock()
    bus.subscribe = MagicMock()
    bus.publish = AsyncMock()
    return bus


def _make_gate(
    cto: MagicMock | None = None,
    config: GateConfig | None = None,
) -> tuple[StageGateMeeting, MagicMock, MagicMock]:
    cto = cto or _make_cto()
    storage = _make_storage()
    bus = _make_event_bus()
    gate = StageGateMeeting(
        cto=cto,
        event_bus=bus,
        storage=storage,
        run_id="run_test",
        config=config,
    )
    return gate, storage, bus


# ------------------------------------------------------------------
# _check_numeric_gate
# ------------------------------------------------------------------


def test_numeric_gate_pass_when_no_items() -> None:
    gate, _, _ = _make_gate()
    items: list[WorkItem] = []
    result = gate._check_numeric_gate(items)
    assert result.verdict is GateVerdict.PASS
    assert result.failure_rate == 0.0
    assert result.total_items == 0


def test_numeric_gate_pass_all_done() -> None:
    gate, _, _ = _make_gate()
    items = [_make_work_item(WorkStatus.DONE, item_id=f"wi_{i}") for i in range(5)]
    result = gate._check_numeric_gate(items)
    assert result.verdict is GateVerdict.PASS
    assert result.failure_rate == 0.0


def test_numeric_gate_fail_when_failure_rate_exceeds_threshold() -> None:
    gate, _, _ = _make_gate(config=GateConfig(max_failure_rate=0.3))
    items = [
        _make_work_item(WorkStatus.FAILED, item_id="wi_0"),
        _make_work_item(WorkStatus.FAILED, item_id="wi_1"),
        _make_work_item(WorkStatus.DONE, item_id="wi_2"),
    ]
    # 2/3 ≈ 66.7% > 30%
    result = gate._check_numeric_gate(items)
    assert result.verdict is GateVerdict.ABORT
    assert result.failure_rate == pytest.approx(2 / 3)


def test_numeric_gate_blocked_counts_as_failure() -> None:
    gate, _, _ = _make_gate(config=GateConfig(max_failure_rate=0.3))
    items = [
        _make_work_item(WorkStatus.BLOCKED, item_id="wi_0"),
        _make_work_item(WorkStatus.DONE, item_id="wi_1"),
        _make_work_item(WorkStatus.DONE, item_id="wi_2"),
    ]
    # 1/3 ≈ 33.3% > 30%
    result = gate._check_numeric_gate(items)
    assert result.verdict is GateVerdict.ABORT
    assert result.failure_rate == pytest.approx(1 / 3)


def test_numeric_gate_pass_at_exact_threshold() -> None:
    gate, _, _ = _make_gate(config=GateConfig(max_failure_rate=0.5))
    items = [
        _make_work_item(WorkStatus.FAILED, item_id="wi_0"),
        _make_work_item(WorkStatus.DONE, item_id="wi_1"),
    ]
    # 0.5 == threshold → should PASS (not strictly greater)
    result = gate._check_numeric_gate(items)
    assert result.verdict is GateVerdict.PASS


def test_numeric_gate_avg_duration_calculated() -> None:
    gate, _, _ = _make_gate()
    items = [
        _make_work_item(WorkStatus.DONE, duration_sec=10.0, item_id="wi_0"),
        _make_work_item(WorkStatus.DONE, duration_sec=30.0, item_id="wi_1"),
    ]
    # Items with DONE status and no result — duration still computed from timestamps
    result = gate._check_numeric_gate(items)
    # avg = (10 + 30) / 2 = 20, but only DONE items with result count
    # result=None → durations list is empty → avg_duration=0.0
    assert result.avg_duration == pytest.approx(0.0)


# ------------------------------------------------------------------
# evaluate — PASS path (no CTO call)
# ------------------------------------------------------------------


async def test_evaluate_pass_does_not_call_cto() -> None:
    cto = _make_cto()
    gate, storage, _ = _make_gate(cto=cto)
    items = [_make_work_item(WorkStatus.DONE, item_id=f"wi_{i}") for i in range(3)]
    result = await gate.evaluate(items)
    assert result.verdict is GateVerdict.PASS
    cto.review_progress.assert_not_called()


async def test_evaluate_pass_persists_result() -> None:
    gate, storage, _ = _make_gate()
    items = [_make_work_item(WorkStatus.DONE)]
    await gate.evaluate(items)
    assert storage.save.called


async def test_evaluate_empty_items_passes() -> None:
    gate, storage, _ = _make_gate()
    result = await gate.evaluate([])
    assert result.verdict is GateVerdict.PASS


# ------------------------------------------------------------------
# evaluate — FAIL → CTO delegation
# ------------------------------------------------------------------


async def test_evaluate_fail_delegates_to_cto() -> None:
    cto = _make_cto(decision=ReviewDecision.REPLAN, reason="restructure needed")
    gate, storage, _ = _make_gate(cto=cto, config=GateConfig(max_failure_rate=0.1))
    items = [
        _make_work_item(WorkStatus.FAILED, item_id="wi_0"),
        _make_work_item(WorkStatus.DONE, item_id="wi_1"),
    ]
    result = await gate.evaluate(items)
    cto.review_progress.assert_called_once()
    assert result.verdict is GateVerdict.REPLAN
    assert "CTO:" in result.reason


async def test_evaluate_cto_abort_decision_maps_to_abort() -> None:
    cto = _make_cto(decision=ReviewDecision.ABORT, reason="unrecoverable failure")
    gate, _, _ = _make_gate(cto=cto, config=GateConfig(max_failure_rate=0.1))
    items = [
        _make_work_item(WorkStatus.FAILED, item_id="wi_0"),
        _make_work_item(WorkStatus.DONE, item_id="wi_1"),
    ]
    result = await gate.evaluate(items)
    assert result.verdict is GateVerdict.ABORT


async def test_evaluate_fail_persists_delegated_result() -> None:
    cto = _make_cto(decision=ReviewDecision.REPLAN)
    gate, storage, _ = _make_gate(cto=cto, config=GateConfig(max_failure_rate=0.1))
    items = [
        _make_work_item(WorkStatus.FAILED, item_id="wi_0"),
        _make_work_item(WorkStatus.DONE, item_id="wi_1"),
    ]
    await gate.evaluate(items)
    assert storage.save.called


# ------------------------------------------------------------------
# evaluate_emergency
# ------------------------------------------------------------------


async def test_evaluate_emergency_returns_replan() -> None:
    gate, storage, _ = _make_gate()
    payload: dict[str, object] = {"item_id": "wi_blocked", "agent_id": "backend"}
    result = await gate.evaluate_emergency(payload)
    assert result.verdict is GateVerdict.REPLAN
    assert result.failure_rate == 1.0
    assert result.total_items == 1


async def test_evaluate_emergency_persists_result() -> None:
    gate, storage, _ = _make_gate()
    payload: dict[str, object] = {"item_id": "wi_blocked", "agent_id": "frontend"}
    await gate.evaluate_emergency(payload)
    assert storage.save.called


# ------------------------------------------------------------------
# EventBus subscription
# ------------------------------------------------------------------


def test_constructor_subscribes_to_blocking_detected() -> None:
    gate, _, bus = _make_gate()
    bus.subscribe.assert_called_once()
    event_name, handler = bus.subscribe.call_args[0]
    assert event_name == "blocking.detected"
    assert callable(handler)


def test_blocking_detected_appends_to_list() -> None:
    gate, _, _ = _make_gate()
    payload: dict[str, object] = {"item_id": "wi_x", "agent_id": "mlops"}
    # Call handler directly (no running loop)
    gate._on_blocking_detected("blocking.detected", payload)
    assert payload in gate._blocking_items


async def test_blocking_detected_creates_emergency_task() -> None:
    gate, storage, _ = _make_gate()
    payload: dict[str, object] = {"item_id": "wi_x", "agent_id": "mlops"}
    gate._on_blocking_detected("blocking.detected", payload)
    # Allow event loop to run the created task
    await asyncio.sleep(0)
    assert storage.save.called


# ------------------------------------------------------------------
# GateConfig defaults
# ------------------------------------------------------------------


def test_gate_config_defaults() -> None:
    config = GateConfig()
    assert config.max_failure_rate == pytest.approx(0.3)
    assert config.max_avg_duration == pytest.approx(120.0)


def test_gate_config_custom_threshold_respected() -> None:
    gate, _, _ = _make_gate(config=GateConfig(max_failure_rate=0.5))
    items = [
        _make_work_item(WorkStatus.FAILED, item_id="wi_0"),
        _make_work_item(WorkStatus.DONE, item_id="wi_1"),
        _make_work_item(WorkStatus.DONE, item_id="wi_2"),
    ]
    # 1/3 ≈ 33% < 50% → PASS
    result = gate._check_numeric_gate(items)
    assert result.verdict is GateVerdict.PASS
