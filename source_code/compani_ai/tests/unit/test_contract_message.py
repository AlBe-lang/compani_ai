from __future__ import annotations

from domain.contracts import Message, MessageStatus, MessageType


def test_message_serialization_roundtrip() -> None:
    message = Message(
        id="msg_1",
        from_agent="cto",
        to_agent="backend",
        type=MessageType.QUESTION,
        content="API spec needed",
        context={"task_id": "task-1"},
        status=MessageStatus.PENDING,
    )

    restored = Message.model_validate_json(message.model_dump_json())

    assert restored.id == "msg_1"
    assert restored.type is MessageType.QUESTION
    assert restored.status is MessageStatus.PENDING
    assert restored.context["task_id"] == "task-1"
