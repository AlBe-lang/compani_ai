from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from adapters.errors import AdapterError
from adapters.event_bus import InProcessEventBus
from adapters.shared_workspace import SharedWorkspace
from adapters.sqlite_storage import SQLiteStorage
from domain.contracts import TaskResult, WorkItem, WorkStatus
from domain.contracts.task_result import FileInfo
from observability.error_codes import ErrorCode


def _make_work_item(item_id: str = "wi-1", status: WorkStatus = WorkStatus.PLANNED) -> WorkItem:
    return WorkItem(id=item_id, task_id="task-1", agent_id="backend", status=status)


def _make_task_result() -> TaskResult:
    return TaskResult(
        task_id="task-1",
        agent_id="backend",
        success=True,
        approach="test",
        code="print('hello')",
        files=[FileInfo(name="main.py", path="main.py", content="print('hello')", type="python")],
        dependencies=[],
        setup_commands=[],
    )


@pytest.fixture
async def workspace() -> AsyncGenerator[SharedWorkspace, None]:
    storage = SQLiteStorage(":memory:")
    await storage.init()
    bus = InProcessEventBus()
    ws = SharedWorkspace(storage=storage, event_bus=bus)
    yield ws
    await storage.close()


async def test_register_stores_item(workspace: SharedWorkspace) -> None:
    item = _make_work_item()
    item_id = await workspace.register(item)
    assert item_id == "wi-1"
    stored = await workspace.get("wi-1")
    assert stored is not None
    assert stored.id == "wi-1"


async def test_get_returns_deep_copy(workspace: SharedWorkspace) -> None:
    item = _make_work_item()
    await workspace.register(item)
    a = await workspace.get("wi-1")
    b = await workspace.get("wi-1")
    assert a is not b


async def test_get_missing_returns_none(workspace: SharedWorkspace) -> None:
    result = await workspace.get("missing")
    assert result is None


async def test_valid_transition_planned_to_in_progress(workspace: SharedWorkspace) -> None:
    await workspace.register(_make_work_item(status=WorkStatus.PLANNED))
    await workspace.set_status("wi-1", WorkStatus.IN_PROGRESS)
    item = await workspace.get("wi-1")
    assert item is not None
    assert item.status is WorkStatus.IN_PROGRESS


async def test_valid_transition_in_progress_to_done(workspace: SharedWorkspace) -> None:
    await workspace.register(_make_work_item(status=WorkStatus.IN_PROGRESS))
    await workspace.set_status("wi-1", WorkStatus.DONE)
    item = await workspace.get("wi-1")
    assert item is not None
    assert item.status is WorkStatus.DONE


async def test_invalid_transition_raises_adapter_error(workspace: SharedWorkspace) -> None:
    await workspace.register(_make_work_item(status=WorkStatus.DONE))
    with pytest.raises(AdapterError) as exc_info:
        await workspace.set_status("wi-1", WorkStatus.IN_PROGRESS)
    assert exc_info.value.code is ErrorCode.E_DEPS_BLOCKED


async def test_set_status_missing_item_raises(workspace: SharedWorkspace) -> None:
    with pytest.raises(AdapterError) as exc_info:
        await workspace.set_status("nonexistent", WorkStatus.IN_PROGRESS)
    assert exc_info.value.code is ErrorCode.E_STORAGE_READ


async def test_attach_result_persists(workspace: SharedWorkspace) -> None:
    await workspace.register(_make_work_item())
    result = _make_task_result()
    await workspace.attach_result("wi-1", result)
    item = await workspace.get("wi-1")
    assert item is not None
    assert item.result is not None
    assert item.result.success is True


async def test_detect_blocking_true_for_blocked(workspace: SharedWorkspace) -> None:
    await workspace.register(_make_work_item(status=WorkStatus.BLOCKED))
    assert await workspace.detect_blocking("wi-1") is True


async def test_detect_blocking_false_for_non_blocked(workspace: SharedWorkspace) -> None:
    await workspace.register(_make_work_item(status=WorkStatus.IN_PROGRESS))
    assert await workspace.detect_blocking("wi-1") is False


async def test_detect_blocking_missing_item_returns_false(workspace: SharedWorkspace) -> None:
    assert await workspace.detect_blocking("missing") is False


async def test_get_by_task_id_resolves_correct_item(workspace: SharedWorkspace) -> None:
    item = WorkItem(
        id="work_task_abc_0001", task_id="task_abc", agent_id="backend", status=WorkStatus.PLANNED
    )
    await workspace.register(item)
    found = await workspace.get_by_task_id("task_abc")
    assert found is not None
    assert found.id == "work_task_abc_0001"


async def test_get_by_task_id_returns_none_for_unknown(workspace: SharedWorkspace) -> None:
    result = await workspace.get_by_task_id("nonexistent_task")
    assert result is None


async def test_event_published_on_status_change(workspace: SharedWorkspace) -> None:
    events: list[dict[str, object]] = []

    storage = SQLiteStorage(":memory:")
    await storage.init()
    bus = InProcessEventBus()
    bus.subscribe("work_item.updated", lambda t, p: events.append(p))  # type: ignore[arg-type]
    ws = SharedWorkspace(storage=storage, event_bus=bus)

    await ws.register(_make_work_item(status=WorkStatus.PLANNED))
    await ws.set_status("wi-1", WorkStatus.IN_PROGRESS)

    assert len(events) == 1
    assert events[0]["item_id"] == "wi-1"
    assert events[0]["curr_status"] == WorkStatus.IN_PROGRESS
    await storage.close()
