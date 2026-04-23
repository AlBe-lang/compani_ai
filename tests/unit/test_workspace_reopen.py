"""Tests for SharedWorkspace.reopen + WorkItem.rework_count — Part 7 Stage 3."""

from __future__ import annotations

from typing import Any

import pytest

from adapters.event_bus import InProcessEventBus
from adapters.shared_workspace import SharedWorkspace
from adapters.sqlite_storage import SQLiteStorage
from domain.contracts import FileInfo, TaskResult, WorkItem, WorkStatus


@pytest.fixture
async def storage() -> SQLiteStorage:
    s = SQLiteStorage(":memory:")
    await s.init()
    return s


@pytest.fixture
def event_bus() -> InProcessEventBus:
    return InProcessEventBus()


@pytest.fixture
def workspace(storage: SQLiteStorage, event_bus: InProcessEventBus) -> SharedWorkspace:
    return SharedWorkspace(storage, event_bus)


async def _setup_done_item(workspace: SharedWorkspace, work_item_id: str = "wi_1") -> None:
    item = WorkItem(id=work_item_id, task_id="t1", agent_id="backend_agent")
    await workspace.register(item)
    await workspace.set_status(work_item_id, WorkStatus.IN_PROGRESS)
    await workspace.set_status(work_item_id, WorkStatus.DONE)


async def test_reopen_transitions_done_to_in_progress(workspace: SharedWorkspace) -> None:
    await _setup_done_item(workspace)
    reopened = await workspace.reopen("wi_1", reason="peer_review:CRITICAL")
    assert reopened.status is WorkStatus.IN_PROGRESS
    assert reopened.rework_count == 1


async def test_reopen_increments_rework_count_each_call(workspace: SharedWorkspace) -> None:
    await _setup_done_item(workspace)
    await workspace.reopen("wi_1", reason="rework-1")
    # Cycle DONE → reopen again
    await workspace.set_status("wi_1", WorkStatus.DONE)
    reopened2 = await workspace.reopen("wi_1", reason="rework-2")
    assert reopened2.rework_count == 2


async def test_reopen_publishes_event(
    workspace: SharedWorkspace, event_bus: InProcessEventBus
) -> None:
    await _setup_done_item(workspace)
    received: list[tuple[str, dict[str, Any]]] = []

    def handler(event_type: str, payload: object) -> None:
        if isinstance(payload, dict):
            received.append((event_type, payload))

    event_bus.subscribe("work_item.reopened", handler)
    await workspace.reopen("wi_1", reason="rework-test")
    assert any(et == "work_item.reopened" for et, _ in received)
    reopened_payload = next(p for et, p in received if et == "work_item.reopened")
    assert reopened_payload["item_id"] == "wi_1"
    assert reopened_payload["reason"] == "rework-test"
    assert reopened_payload["rework_count"] == 1


async def test_reopen_rejects_non_done_status(workspace: SharedWorkspace) -> None:
    item = WorkItem(id="wi_nd", task_id="t_nd", agent_id="backend_agent")
    await workspace.register(item)
    await workspace.set_status("wi_nd", WorkStatus.IN_PROGRESS)
    # Not DONE → should raise
    from adapters.errors import AdapterError

    with pytest.raises(AdapterError):
        await workspace.reopen("wi_nd", reason="should fail")


async def test_reopen_rejects_missing_item(workspace: SharedWorkspace) -> None:
    from adapters.errors import AdapterError

    with pytest.raises(AdapterError):
        await workspace.reopen("wi_missing", reason="x")


async def test_attach_result_payload_carries_task_dependencies(
    workspace: SharedWorkspace, event_bus: InProcessEventBus
) -> None:
    item = WorkItem(id="wi_x", task_id="tx", agent_id="backend_agent")
    await workspace.register(item)
    await workspace.set_status("wi_x", WorkStatus.IN_PROGRESS)
    await workspace.set_status("wi_x", WorkStatus.DONE)

    received: list[dict[str, Any]] = []

    def handler(event_type: str, payload: object) -> None:
        if event_type == "task.completed" and isinstance(payload, dict):
            received.append(payload)

    event_bus.subscribe("task.completed", handler)

    result = TaskResult(
        task_id="tx",
        agent_id="backend_agent",
        approach="done",
        code="",
        files=[FileInfo(name="m.py", path="m.py", content="x", type="python")],
    )
    await workspace.attach_result(
        "wi_x",
        result,
        task_dependencies=["tx_prev"],
        task_description="backend task",
    )
    assert len(received) == 1
    payload = received[0]
    assert payload["task_dependencies"] == ["tx_prev"]
    assert payload["task_description"] == "backend task"
    assert payload["rework_count"] == 0
