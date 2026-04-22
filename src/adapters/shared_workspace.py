"""Shared workspace adapter with in-memory cache and SQLite persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from domain.contracts import TaskResult, WorkItem, WorkStatus
from domain.ports import EventBusPort, StoragePort
from observability.error_codes import ErrorCode
from observability.logger import get_logger

from .errors import AdapterError

log = get_logger(__name__)

_ALLOWED_TRANSITIONS: frozenset[tuple[WorkStatus, WorkStatus]] = frozenset(
    {
        (WorkStatus.PLANNED, WorkStatus.IN_PROGRESS),
        (WorkStatus.PLANNED, WorkStatus.WAITING),
        (WorkStatus.WAITING, WorkStatus.IN_PROGRESS),
        (WorkStatus.IN_PROGRESS, WorkStatus.DONE),
        (WorkStatus.IN_PROGRESS, WorkStatus.FAILED),
        (WorkStatus.IN_PROGRESS, WorkStatus.BLOCKED),
        (WorkStatus.BLOCKED, WorkStatus.IN_PROGRESS),
    }
)


class SharedWorkspace:
    """WorkSpacePort implementation: in-memory cache + SQLite persistence + EventBus."""

    def __init__(self, storage: StoragePort, event_bus: EventBusPort) -> None:
        self._storage = storage
        self._event_bus = event_bus
        self._cache: dict[str, WorkItem] = {}
        # Secondary index: task_id → work_item_id.
        # BaseSLMAgent._wait_dependencies resolves dependencies by task_id, but items
        # are stored by work_item_id (work_{task_id}_{uuid}). This index bridges the gap.
        self._task_index: dict[str, str] = {}

    async def register(self, work_item: WorkItem) -> str:
        self._cache[work_item.id] = work_item
        self._task_index[work_item.task_id] = work_item.id
        await self._storage.save(work_item.id, work_item.model_dump(mode="json"))
        log.info("ws.item.registered", item_id=work_item.id, owner=work_item.agent_id)
        return work_item.id

    async def get(self, work_item_id: str) -> WorkItem | None:
        if work_item_id in self._cache:
            return self._cache[work_item_id].model_copy(deep=True)
        data = await self._storage.load(work_item_id)
        if data is None:
            return None
        item = WorkItem.model_validate(data)
        self._cache[work_item_id] = item
        return item.model_copy(deep=True)

    async def set_status(self, work_item_id: str, status: WorkStatus) -> None:
        item = await self.get(work_item_id)
        if item is None:
            raise AdapterError(ErrorCode.E_STORAGE_READ, f"WorkItem not found: {work_item_id}")
        if (item.status, status) not in _ALLOWED_TRANSITIONS:
            raise AdapterError(
                ErrorCode.E_DEPS_BLOCKED,
                f"invalid status transition: {item.status} → {status}",
            )
        prev = item.status
        item.status = status
        item.updated_at = datetime.now(timezone.utc)
        self._cache[work_item_id] = item
        await self._storage.update(work_item_id, item.model_dump(mode="json"))
        log.info("ws.item.status", item_id=work_item_id, prev=prev, curr=status)
        await self._event_bus.publish(
            "work_item.updated",
            {"item_id": work_item_id, "prev_status": prev, "curr_status": status},
        )

    async def attach_result(self, work_item_id: str, result: TaskResult) -> None:
        item = await self.get(work_item_id)
        if item is None:
            raise AdapterError(ErrorCode.E_STORAGE_READ, f"WorkItem not found: {work_item_id}")
        item.result = result
        item.updated_at = datetime.now(timezone.utc)
        self._cache[work_item_id] = item
        await self._storage.update(work_item_id, item.model_dump(mode="json"))

    async def get_by_task_id(self, task_id: str) -> WorkItem | None:
        work_item_id = self._task_index.get(task_id)
        if work_item_id is None:
            return None
        return await self.get(work_item_id)

    async def detect_blocking(self, work_item_id: str) -> bool:
        item = await self.get(work_item_id)
        if item is None:
            return False
        blocked = item.status is WorkStatus.BLOCKED
        if blocked:
            log.warning("ws.blocking", item_id=work_item_id)
        return blocked
