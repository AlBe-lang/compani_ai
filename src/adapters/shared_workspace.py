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
        # Dedicated event so StageGateMeeting subscribes without filtering all updates.
        if status is WorkStatus.BLOCKED:
            await self._event_bus.publish(
                "blocking.detected",
                {"item_id": work_item_id, "agent_id": item.agent_id},
            )

    async def attach_result(
        self,
        work_item_id: str,
        result: TaskResult,
        *,
        task_dependencies: list[str] | None = None,
        task_description: str = "",
    ) -> None:
        """Attach result to a WorkItem and emit ``task.completed`` on DONE.

        Part 7 Stage 3 added optional ``task_dependencies`` and
        ``task_description`` — included in the event payload so peer-review
        coordinators can perform COI (conflict-of-interest) reviewer filtering
        based on direct-dependency task ids. Both parameters default to empty
        for backward compatibility with Stage 1/2 callers.
        """
        item = await self.get(work_item_id)
        if item is None:
            raise AdapterError(ErrorCode.E_STORAGE_READ, f"WorkItem not found: {work_item_id}")
        item.result = result
        item.updated_at = datetime.now(timezone.utc)
        self._cache[work_item_id] = item
        await self._storage.update(work_item_id, item.model_dump(mode="json"))

        # Part 7 Stage 2 — publish task.completed only when the WorkItem actually
        # reached DONE. attach_result may in rare cases be invoked on FAILED items
        # (defensive path); in that case no peer review should be triggered.
        if item.status is WorkStatus.DONE:
            await self._event_bus.publish(
                "task.completed",
                {
                    "item_id": work_item_id,
                    "task_id": item.task_id,
                    "agent_id": item.agent_id,
                    "result": result.model_dump(mode="json"),
                    "task_dependencies": list(task_dependencies or []),
                    "task_description": task_description,
                    "rework_count": item.rework_count,
                },
            )

    async def reopen(self, work_item_id: str, reason: str) -> WorkItem:
        """Part 7 Stage 3 — transition DONE WorkItem back to IN_PROGRESS for rework.

        Intentionally bypasses the standard ``_ALLOWED_TRANSITIONS`` matrix —
        rework is a controlled re-execution path triggered by peer-review
        ``pending_rework=True`` verdicts. Increments ``rework_count`` and emits
        ``work_item.reopened`` for observability / scheduler coordination.

        Raises AdapterError if the item is not currently DONE. Callers (Rework
        scheduler) must enforce ``rework_max_attempts`` before invoking.
        """
        item = await self.get(work_item_id)
        if item is None:
            raise AdapterError(ErrorCode.E_STORAGE_READ, f"WorkItem not found: {work_item_id}")
        if item.status is not WorkStatus.DONE:
            raise AdapterError(
                ErrorCode.E_DEPS_BLOCKED,
                f"reopen requires DONE status, got {item.status}",
            )
        item.status = WorkStatus.IN_PROGRESS
        item.rework_count += 1
        item.updated_at = datetime.now(timezone.utc)
        self._cache[work_item_id] = item
        await self._storage.update(work_item_id, item.model_dump(mode="json"))
        log.info(
            "ws.item.reopened",
            item_id=work_item_id,
            rework_count=item.rework_count,
            reason=reason,
        )
        await self._event_bus.publish(
            "work_item.reopened",
            {
                "item_id": work_item_id,
                "task_id": item.task_id,
                "agent_id": item.agent_id,
                "reason": reason,
                "rework_count": item.rework_count,
            },
        )
        return item

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
