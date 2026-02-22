from __future__ import annotations

import pytest
from pydantic import ValidationError

from domain.contracts import (
    AgentDNA,
    AgentRole,
    FileInfo,
    Message,
    MessageType,
    ReviewResult,
    Strategy,
    Task,
    TaskResult,
    WorkItem,
)


def test_work_item_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WorkItem.model_validate(
            {
                "id": "w1",
                "task_id": "t1",
                "agent_id": "backend",
                "unknown_field": "x",
            }
        )


def test_message_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Message.model_validate(
            {
                "id": "m1",
                "from_agent": "cto",
                "to_agent": "backend",
                "type": MessageType.QUESTION,
                "content": "q",
                "unknown_field": "x",
            }
        )


def test_strategy_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Strategy.model_validate(
            {
                "project_name": "Todo",
                "description": "desc",
                "unknown_field": "x",
            }
        )


def test_task_result_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        TaskResult.model_validate(
            {
                "task_id": "t1",
                "agent_id": "backend",
                "approach": "a",
                "code": "c",
                "files": [
                    FileInfo(name="main.py", path="main.py", content="", type="python").model_dump()
                ],
                "unknown_field": "x",
            }
        )


def test_agent_dna_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        AgentDNA.model_validate(
            {
                "agent_id": "a1",
                "role": "backend",
                "expertise": ["fastapi"],
                "unknown_field": "x",
            }
        )


def test_task_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        Task.model_validate(
            {
                "id": "task-1",
                "title": "Build API",
                "description": "d",
                "agent_role": AgentRole.BACKEND,
                "unknown_field": "x",
            }
        )


def test_review_result_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(
            {
                "decision": "continue",
                "reason": "ok",
                "new_tasks": [],
                "unknown_field": "x",
            }
        )
