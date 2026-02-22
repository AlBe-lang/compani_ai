from __future__ import annotations

from domain.contracts import TaskResult, WorkItem, WorkStatus


def test_work_item_serialization_roundtrip() -> None:
    item = WorkItem(
        id="w1",
        task_id="task-1",
        agent_id="backend",
        status=WorkStatus.IN_PROGRESS,
        result=TaskResult(
            task_id="task-1",
            agent_id="backend",
            approach="started",
            code="pass",
            files=[],
            success=True,
        ),
    )

    restored = WorkItem.model_validate_json(item.model_dump_json())

    assert restored.id == "w1"
    assert restored.status is WorkStatus.IN_PROGRESS
    assert restored.result is not None
    assert restored.result.task_id == "task-1"
    assert restored.created_at.tzinfo is not None
