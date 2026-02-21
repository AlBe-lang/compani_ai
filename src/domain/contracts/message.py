"""Message contract for inter-agent communication."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MessageType(str, Enum):
    QUESTION = "QUESTION"
    ANSWER = "ANSWER"
    NOTIFICATION = "NOTIFICATION"


class MessageStatus(str, Enum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"
    TIMEOUT = "TIMEOUT"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    from_agent: str
    to_agent: str
    type: MessageType
    content: str
    context: dict[str, object] = Field(default_factory=dict)
    status: MessageStatus = MessageStatus.PENDING
    created_at: datetime = Field(default_factory=_utc_now)
