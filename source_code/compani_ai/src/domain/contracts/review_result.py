"""Review contracts for CTO progress assessment."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .strategy import Task


class ReviewDecision(str, Enum):
    CONTINUE = "continue"
    REPLAN = "replan"
    ABORT = "abort"


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    reason: str
    new_tasks: list[Task] = Field(default_factory=list)
