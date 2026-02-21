"""Mock workspace implementation for isolated tests."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.contracts import TaskResult, WorkItem, WorkStatus


class MockWorkSpace:
    """Simple in-memory workspace with minimal status transitions."""

    def __init__(self) -> None:
        self._items: dict[str, WorkItem] = {}

    async def register(self, work_item: WorkItem) -> str:
        if not work_item.id:
            raise ValueError("work_item.id is required")
        self._items[work_item.id] = work_item.model_copy(deep=True)
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

    async def attach_result(self, work_item_id: str, result: TaskResult) -> None:
        item = self._items.get(work_item_id)
        if item is None:
            return
        item.result = result.model_dump(mode="json")
        item.updated_at = datetime.now(timezone.utc)

    async def detect_blocking(self, work_item_id: str) -> bool:
        item = self._items.get(work_item_id)
        if item is None:
            return False
        return item.status is WorkStatus.BLOCKED
