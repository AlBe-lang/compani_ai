"""ReworkScheduler — Part 7 Stage 3.

Subscribes to ``review.rework_requested`` (emitted by PeerReviewCoordinator
when a review sets ``pending_rework=True``). Responsibilities:

  1. Check ``WorkItem.rework_count`` against ``rework_max_attempts``;
     force FAILED if exceeded (prevents infinite loops).
  2. Call ``workspace.reopen()`` to transition DONE → IN_PROGRESS.
  3. Rebuild the original Task from the review snapshot + dependency metadata.
  4. Invoke the producer agent's ``execute_task`` with a ``review_feedback``
     entry in the task execution context so the agent's prompt can absorb
     the reviewer's comments and suggested_changes.

Stage 3 scope boundary: the scheduler does NOT orchestrate re-execution
chains (producer → reviewer → rework → ...). The new ``execute_task`` call
eventually emits another ``task.completed``, which cycles naturally through
the existing peer-review loop. ``rework_max_attempts`` cap keeps the cycle
bounded.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.contracts import AgentRole, Task, WorkStatus
from domain.ports import AgentPort, StoragePort, WorkSpacePort
from observability.logger import get_logger

if TYPE_CHECKING:
    from domain.ports import EventBusPort
    from observability.metrics import MetricsCollector

log = get_logger(__name__)

_DEFAULT_MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class ReworkConfig:
    enabled: bool = False
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS


class ReworkScheduler:
    """EventBus handler that drives pending_rework → actual re-execution."""

    def __init__(
        self,
        *,
        workspace: WorkSpacePort,
        storage: StoragePort,
        event_bus: "EventBusPort",
        agents: Mapping[str, AgentPort],
        run_id: str,
        config: ReworkConfig | None = None,
        metrics: "MetricsCollector | None" = None,
    ) -> None:
        self._workspace = workspace
        self._storage = storage
        self._event_bus = event_bus
        self._agents = dict(agents)
        self._run_id = run_id
        self._config = config or ReworkConfig()
        self._metrics = metrics
        self._logger = get_logger(component="rework_scheduler", run_id=run_id)

        if self._config.enabled:
            event_bus.subscribe("review.rework_requested", self._on_rework_requested)

    # ------------------------------------------------------------------
    # 퍼블릭 API
    # ------------------------------------------------------------------

    async def handle_rework(self, payload: dict[str, object]) -> bool:
        """Run a single rework cycle for the given review payload.

        Returns True when re-execution was scheduled, False when skipped
        (disabled, max attempts, agent missing, etc.). Called directly or
        by the EventBus handler.
        """
        if not self._config.enabled:
            self._logger.debug("rework.disabled")
            return False

        work_item_id = str(payload.get("work_item_id", ""))
        author_agent_id = str(payload.get("author_agent_id", ""))
        if not work_item_id or not author_agent_id:
            self._logger.warning("rework.invalid_payload", payload_keys=list(payload.keys()))
            return False

        item = await self._workspace.get_by_task_id(str(payload.get("task_id", "")))
        if item is None:
            item = await self._workspace.get(work_item_id)
        if item is None:
            self._logger.warning("rework.workitem_missing", work_item_id=work_item_id)
            return False

        # Rework budget check (pre-increment — reopen() will increment it).
        if item.rework_count >= self._config.max_attempts:
            self._logger.warning(
                "rework.max_attempts_reached",
                work_item_id=work_item_id,
                rework_count=item.rework_count,
                max=self._config.max_attempts,
            )
            if self._metrics is not None:
                self._metrics.record_fallback(
                    run_id=self._run_id,
                    component="rework_scheduler",
                    reason="max_attempts_reached",
                )
            # Try to transition to FAILED; ignore if the transition is invalid.
            try:
                await self._workspace.set_status(work_item_id, WorkStatus.FAILED)
            except Exception as exc:
                self._logger.warning(
                    "rework.force_failed_error",
                    work_item_id=work_item_id,
                    detail=str(exc),
                )
            return False

        agent_role = self._role_from_agent_id(author_agent_id)
        agent = self._agents.get(agent_role)
        if agent is None:
            self._logger.warning(
                "rework.agent_missing",
                role=agent_role,
                available=sorted(self._agents.keys()),
            )
            return False

        # Flip status → IN_PROGRESS + increment counter.
        try:
            await self._workspace.reopen(
                work_item_id,
                reason=f"peer_review:{payload.get('severity', '?')}",
            )
        except Exception as exc:
            self._logger.warning("rework.reopen_error", work_item_id=work_item_id, detail=str(exc))
            return False

        task = self._rebuild_task(payload, agent_role)
        if task is None:
            self._logger.warning("rework.task_rebuild_failed", work_item_id=work_item_id)
            return False

        raw_comments = payload.get("comments")
        raw_changes = payload.get("suggested_changes")
        comments_list = list(raw_comments) if isinstance(raw_comments, list) else []
        changes_list = list(raw_changes) if isinstance(raw_changes, list) else []
        context: dict[str, object] = {
            "review_feedback": {
                "comments": comments_list,
                "suggested_changes": changes_list,
                "severity": payload.get("severity", ""),
                "review_id": payload.get("review_id", ""),
            }
        }
        self._logger.info(
            "rework.scheduled",
            work_item_id=work_item_id,
            task_id=task.id,
            role=agent_role,
            rework_count=item.rework_count + 1,
        )
        # Fire-and-forget re-execution — eventually emits task.completed which
        # re-enters the peer review loop. rework_max_attempts caps the cycle.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._execute_rework(agent, task, context))
        except RuntimeError:
            # No running loop (tests that exercise the handler synchronously).
            self._logger.debug("rework.no_loop")
        return True

    async def _execute_rework(
        self, agent: AgentPort, task: Task, context: dict[str, object]
    ) -> None:
        """Invoke agent.execute_task with the injected review_feedback context."""
        try:
            await agent.execute_task(task, context=context)
        except TypeError:
            # Older AgentPort impls don't accept context kwarg — degrade gracefully.
            try:
                await agent.execute_task(task)  # type: ignore[call-arg]
            except Exception as exc:
                self._logger.warning("rework.execute_error", detail=str(exc))
        except Exception as exc:
            self._logger.warning("rework.execute_error", detail=str(exc))

    # ------------------------------------------------------------------
    # EventBus 핸들러
    # ------------------------------------------------------------------

    def _on_rework_requested(self, event_type: str, payload: dict[str, object]) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.handle_rework(payload))
        except RuntimeError:
            self._logger.warning("rework.no_loop", task_id=payload.get("task_id"))

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _role_from_agent_id(agent_id: str) -> str:
        lowered = agent_id.lower()
        for role in ("backend", "frontend", "mlops", "cto"):
            if role in lowered:
                return role
        return "general"

    def _rebuild_task(self, payload: dict[str, object], agent_role: str) -> Task | None:
        """Reconstruct a minimal Task object from the review snapshot.

        We don't preserve the original Task at source, so this is a best-effort
        rebuild. For rework purposes the important fields are id/title/
        description/agent_role/dependencies — acceptance_criteria/priority get
        reasonable defaults.
        """
        snapshot: dict[str, Any] = {}
        raw_snap = payload.get("task_result_snapshot")
        if isinstance(raw_snap, dict):
            snapshot = raw_snap
        task_id = str(payload.get("task_id", "")) or str(snapshot.get("task_id", ""))
        if not task_id:
            return None
        description = str(snapshot.get("approach", "") or "")
        try:
            role_enum = AgentRole(agent_role)
        except ValueError:
            return None
        deps_raw = snapshot.get("dependencies", []) or []
        # snapshot.dependencies are package deps (pip etc) not task ids. We keep
        # them empty for the rebuilt Task — rework re-runs in isolation, since
        # all upstream tasks have already produced their results.
        _ = deps_raw  # intentionally unused; see comment above
        return Task(
            id=task_id,
            title=f"[rework] {task_id}",
            description=description or "Rework requested by peer review",
            agent_role=role_enum,
            acceptance_criteria=[],
            dependencies=[],
            priority=3,
        )
