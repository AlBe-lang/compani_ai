"""Core protocol contracts shared across agents and infrastructure."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, TypeAlias, TypedDict, runtime_checkable

from domain.contracts import Message, MessageType, Task, TaskResult, WorkItem, WorkStatus


class LLMMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


EventPayload: TypeAlias = dict[str, object]
StorageValue: TypeAlias = dict[str, object]
EventHandler: TypeAlias = Callable[[str, EventPayload], Awaitable[None] | None]


@runtime_checkable
class LLMProvider(Protocol):
    """Contract for text generation backends."""

    async def generate(
        self,
        model: str,
        messages: list[LLMMessage],
        **kwargs: object,
    ) -> str:
        """Generate a response from an LLM."""


@runtime_checkable
class AgentPort(Protocol):
    """Contract for execution agents managed by CTO."""

    async def execute_task(
        self,
        task: Task,
        *,
        context: dict[str, object] | None = None,
    ) -> TaskResult:
        """Execute one task and return result.

        Part 7 Stage 3 added optional ``context`` — a free-form dict that
        upstream components (e.g. ReworkScheduler) can use to pass
        execution-time metadata such as ``review_feedback`` or a preexisting
        ``work_item_id`` for rework paths. Implementers should tolerate
        ``None`` and unknown keys gracefully.
        """


@runtime_checkable
class WorkSpacePort(Protocol):
    """Contract for shared workspace operations."""

    async def register(self, work_item: WorkItem) -> str:
        """Register a new work item and return its id."""

    async def get(self, work_item_id: str) -> WorkItem | None:
        """Get a work item by work_item_id."""

    async def get_by_task_id(self, task_id: str) -> WorkItem | None:
        """Get a work item by the task_id it was created for."""

    async def set_status(self, work_item_id: str, status: WorkStatus) -> None:
        """Update status of a work item."""

    async def attach_result(
        self,
        work_item_id: str,
        result: TaskResult,
        *,
        task_dependencies: list[str] | None = None,
        task_description: str = "",
    ) -> None:
        """Attach execution result to a work item.

        Part 7 Stage 3 added keyword-only ``task_dependencies`` and
        ``task_description`` — flow into the ``task.completed`` event payload
        for COI-aware peer reviewer selection. Both have safe defaults so
        legacy callers remain compatible.
        """

    async def reopen(self, work_item_id: str, reason: str) -> "WorkItem | None":
        """Part 7 Stage 3 — transition DONE WorkItem back to IN_PROGRESS.

        Used by ReworkScheduler to re-execute a Task after a peer review
        flagged pending_rework. Implementations should increment the
        WorkItem.rework_count. May return None or raise if the transition is
        invalid (non-DONE item).
        """

    async def detect_blocking(self, work_item_id: str) -> bool:
        """Return whether the work item is blocked."""


@runtime_checkable
class MessageQueuePort(Protocol):
    """Contract for async inter-agent communication."""

    async def ask(
        self,
        from_agent: str,
        to_agent: str,
        question: str,
        context: dict[str, object] | None = None,
        timeout_sec: float = 30.0,
    ) -> str:
        """Send a question and wait for an answer."""

    async def send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        message_type: MessageType = MessageType.NOTIFICATION,
        context: dict[str, object] | None = None,
    ) -> str:
        """Send a message and return message id."""

    async def receive(
        self,
        agent_id: str,
        timeout_sec: float = 0.0,
    ) -> Message | None:
        """Receive one message for an agent."""


@runtime_checkable
class StoragePort(Protocol):
    """Contract for persistence adapters."""

    async def save(self, key: str, value: StorageValue) -> None:
        """Save a value by key."""

    async def load(self, key: str) -> StorageValue | None:
        """Load value by key."""

    async def update(self, key: str, value: StorageValue) -> None:
        """Update an existing value by key."""

    async def query(self, **filters: object) -> list[StorageValue]:
        """Query values with filter conditions."""


@runtime_checkable
class KnowledgeGraphPort(Protocol):
    """Contract for agent expertise tracking and Q&A routing via vector DB."""

    async def store_interaction(
        self,
        agent_id: str,
        role: str,
        question: str,
        answer: str,
        success: bool,
        project_id: str,
        run_id: str,
    ) -> None:
        """Store a Q&A interaction and update expertise EMA for the agent role."""

    async def store_task_result(self, result: "TaskResult", run_id: str) -> None:
        """Store a task result vector for future routing context."""

    async def find_best_responder(
        self,
        question: str,
        context: dict[str, object] | None = None,
    ) -> str | None:
        """Return agent role best suited to answer question, or None if unknown."""

    async def get_expertise_level(self, role: str, topic: str) -> float:
        """Return EMA expertise level [0.0, 1.0] for a role on a topic."""


@runtime_checkable
class EventBusPort(Protocol):
    """Contract for event publish/subscribe."""

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""

    async def publish(self, event_type: str, payload: EventPayload) -> None:
        """Publish an event to subscribers."""
