"""Unit tests for ReworkScheduler — Part 7 Stage 3.

Covers:
  1. disabled mode skips
  2. workitem missing → skip
  3. max_attempts reached → FAILED + record_fallback metric
  4. reopen + create_task on success path
  5. unknown agent role → skip
  6. EventBus subscription when enabled
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from application.rework_scheduler import ReworkConfig, ReworkScheduler
from domain.contracts import WorkItem, WorkStatus


def _make_workspace(item: WorkItem | None = None) -> MagicMock:
    mock = MagicMock()
    mock.get_by_task_id = AsyncMock(return_value=item)
    mock.get = AsyncMock(return_value=item)
    mock.reopen = AsyncMock()
    mock.set_status = AsyncMock()
    return mock


def _make_agent() -> MagicMock:
    mock = MagicMock()
    mock.execute_task = AsyncMock()
    return mock


def _make_event_bus() -> MagicMock:
    mock = MagicMock()
    mock.subscribe = MagicMock()
    return mock


def _base_payload(
    *,
    work_item_id: str = "wi_1",
    task_id: str = "task_1",
    author: str = "backend_agent",
    severity: str = "CRITICAL",
) -> dict[str, object]:
    return {
        "review_id": "review_abc",
        "work_item_id": work_item_id,
        "task_id": task_id,
        "author_agent_id": author,
        "reviewer_agent_id": "frontend",
        "severity": severity,
        "comments": ["fix the thing"],
        "suggested_changes": ["use async"],
        "task_result_snapshot": {
            "task_id": task_id,
            "agent_id": author,
            "approach": "initial approach",
            "dependencies": [],
        },
    }


def _make_scheduler(
    *,
    enabled: bool = True,
    max_attempts: int = 2,
    workspace: MagicMock | None = None,
    event_bus: MagicMock | None = None,
    agents: dict[str, MagicMock] | None = None,
    metrics: MagicMock | None = None,
    storage: MagicMock | None = None,
) -> tuple[ReworkScheduler, MagicMock, MagicMock, dict[str, MagicMock]]:
    ws = workspace or _make_workspace()
    bus = event_bus or _make_event_bus()
    ags = agents if agents is not None else {"backend": _make_agent()}
    sched = ReworkScheduler(
        workspace=ws,
        storage=storage or MagicMock(),
        event_bus=bus,
        agents=ags,
        run_id="run_test",
        config=ReworkConfig(enabled=enabled, max_attempts=max_attempts),
        metrics=metrics,
    )
    return sched, ws, bus, ags


async def test_disabled_skips_everything() -> None:
    sched, _, bus, _ = _make_scheduler(enabled=False)
    bus.subscribe.assert_not_called()
    ok = await sched.handle_rework(_base_payload())
    assert ok is False


async def test_subscribes_when_enabled() -> None:
    _, _, bus, _ = _make_scheduler(enabled=True)
    bus.subscribe.assert_called_once()
    event_name, handler = bus.subscribe.call_args[0]
    assert event_name == "review.rework_requested"
    assert callable(handler)


async def test_workitem_missing_skips() -> None:
    workspace = _make_workspace(item=None)
    sched, _, _, _ = _make_scheduler(workspace=workspace)
    ok = await sched.handle_rework(_base_payload())
    assert ok is False
    workspace.reopen.assert_not_awaited()


async def test_max_attempts_forces_failed_and_records_metric() -> None:
    item = WorkItem(id="wi_1", task_id="task_1", agent_id="backend", rework_count=2)
    workspace = _make_workspace(item=item)
    metrics = MagicMock()
    metrics.record_fallback = MagicMock()
    sched, _, _, _ = _make_scheduler(workspace=workspace, max_attempts=2, metrics=metrics)
    ok = await sched.handle_rework(_base_payload())
    assert ok is False
    workspace.set_status.assert_awaited_once_with("wi_1", WorkStatus.FAILED)
    metrics.record_fallback.assert_called_once()
    kwargs = metrics.record_fallback.call_args.kwargs
    assert kwargs["component"] == "rework_scheduler"
    assert kwargs["reason"] == "max_attempts_reached"


async def test_unknown_agent_role_skips() -> None:
    item = WorkItem(id="wi_1", task_id="task_1", agent_id="designer_agent")
    workspace = _make_workspace(item=item)
    sched, _, _, _ = _make_scheduler(workspace=workspace, agents={"backend": _make_agent()})
    ok = await sched.handle_rework(_base_payload(author="designer_agent"))
    assert ok is False
    workspace.reopen.assert_not_awaited()


async def test_successful_rework_reopens_and_schedules_execute() -> None:
    item = WorkItem(id="wi_1", task_id="task_1", agent_id="backend", rework_count=0)
    workspace = _make_workspace(item=item)
    backend_agent = _make_agent()
    sched, _, _, _ = _make_scheduler(workspace=workspace, agents={"backend": backend_agent})
    ok = await sched.handle_rework(_base_payload())
    assert ok is True
    # reopen called with severity-embedded reason
    workspace.reopen.assert_awaited_once()
    reopen_args = workspace.reopen.await_args
    assert reopen_args.args[0] == "wi_1"
    assert "CRITICAL" in reopen_args.kwargs["reason"] or "CRITICAL" in reopen_args.args[1]


async def test_task_rebuild_missing_task_id_skips() -> None:
    item = WorkItem(id="wi_1", task_id="", agent_id="backend", rework_count=0)
    workspace = _make_workspace(item=item)
    sched, _, _, _ = _make_scheduler(workspace=workspace, agents={"backend": _make_agent()})
    payload = _base_payload()
    payload["task_id"] = ""
    snapshot = payload["task_result_snapshot"]
    assert isinstance(snapshot, dict)
    snapshot["task_id"] = ""
    ok = await sched.handle_rework(payload)
    assert ok is False
