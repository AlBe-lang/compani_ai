"""Mock workspace implementation for isolated tests."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.contracts import TaskResult, WorkItem, WorkStatus


class MockWorkSpace:
    """Simple in-memory workspace with minimal status transitions."""

    def __init__(self) -> None:
        self._items: dict[str, WorkItem] = {}
        self._task_index: dict[str, str] = {}

    async def register(self, work_item: WorkItem) -> str:
        if not work_item.id:
            raise ValueError("work_item.id is required")
        self._items[work_item.id] = work_item.model_copy(deep=True)
        self._task_index[work_item.task_id] = work_item.id
        return work_item.id

    async def get(self, work_item_id: str) -> WorkItem | None:
        item = self._items.get(work_item_id)
        return item.model_copy(deep=True) if item else None

    async def set_status(self, work_item_id: str, status: WorkStatus) -> None:
        item = self._items.get(work_item_id)
        if item is None:
            return
        item.status = status
        item.updated_at = datetime.now(timezone.utc)

    async def attach_result(
        self,
        work_item_id: str,
        result: TaskResult,
        *,
        task_dependencies: list[str] | None = None,
        task_description: str = "",
    ) -> None:
        # Part 7 Stage 3 — keyword args accepted for protocol parity with
        # SharedWorkspace; test mock does not propagate them into events.
        _ = task_dependencies, task_description
        item = self._items.get(work_item_id)
        if item is None:
            return
        item.result = result.model_copy(deep=True)
        item.updated_at = datetime.now(timezone.utc)

    async def reopen(self, work_item_id: str, reason: str) -> WorkItem | None:
        """Part 7 Stage 3 parity — DONE → IN_PROGRESS + rework_count +1."""
        _ = reason
        item = self._items.get(work_item_id)
        if item is None or item.status is not WorkStatus.DONE:
            return None
        item.status = WorkStatus.IN_PROGRESS
        item.rework_count += 1
        item.updated_at = datetime.now(timezone.utc)
        return item.model_copy(deep=True)

    async def get_by_task_id(self, task_id: str) -> WorkItem | None:
        work_item_id = self._task_index.get(task_id)
        if work_item_id is None:
            return None
        return await self.get(work_item_id)

    async def detect_blocking(self, work_item_id: str) -> bool:
        item = self._items.get(work_item_id)
        if item is None:
            return False
        return item.status is WorkStatus.BLOCKED
