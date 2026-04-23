"""Work item contract for shared workspace state."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ._utils import utc_now
from .task_result import TaskResult


class WorkStatus(str, Enum):
    PLANNED = "PLANNED"
    WAITING = "WAITING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class WorkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    task_id: str
    agent_id: str
    status: WorkStatus = WorkStatus.PLANNED
    result: TaskResult | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    # Part 7 Stage 3 — number of times this WorkItem has been reopened for rework.
    # Non-breaking (default 0). Used by ReworkScheduler to enforce rework_max_attempts.
    rework_count: int = Field(default=0, ge=0)
