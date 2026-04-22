from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from adapters.sqlite_message_queue import SQLiteMessageQueue
from adapters.sqlite_storage import SQLiteStorage
from domain.contracts import MessageType


@pytest.fixture
async def queue() -> AsyncGenerator[SQLiteMessageQueue, None]:
    storage = SQLiteStorage(":memory:")
    await storage.init()
    q = SQLiteMessageQueue(storage=storage)
    yield q
    await storage.close()


async def test_send_returns_message_id(queue: SQLiteMessageQueue) -> None:
    msg_id = await queue.send("frontend", "backend", "hello")
    assert isinstance(msg_id, str)
    assert len(msg_id) > 0


async def test_receive_gets_sent_message(queue: SQLiteMessageQueue) -> None:
    await queue.send("frontend", "backend", "please help")
    msg = await queue.receive("backend")
    assert msg is not None
    assert msg.content == "please help"
    assert msg.from_agent == "frontend"
    assert msg.to_agent == "backend"


async def test_receive_empty_returns_none(queue: SQLiteMessageQueue) -> None:
    msg = await queue.receive("backend")
    assert msg is None


async def test_send_sets_correct_message_type(queue: SQLiteMessageQueue) -> None:
    await queue.send("cto", "mlops", "deploy now", message_type=MessageType.NOTIFICATION)
    msg = await queue.receive("mlops")
    assert msg is not None
    assert msg.type is MessageType.NOTIFICATION


async def test_ask_sends_question_to_target(queue: SQLiteMessageQueue) -> None:
    await queue.ask("frontend", "backend", "what is the API?", timeout_sec=0.01)
    msg = await queue.receive("backend")
    assert msg is not None
    assert msg.type is MessageType.QUESTION
    assert msg.content == "what is the API?"


async def test_ask_returns_empty_on_timeout(queue: SQLiteMessageQueue) -> None:
    result = await queue.ask("frontend", "backend", "will not be answered", timeout_sec=0.01)
    assert result == ""


async def test_message_persisted_to_storage(queue: SQLiteMessageQueue) -> None:
    msg_id = await queue.send("frontend", "backend", "stored?")
    storage_data = await queue._storage.load(msg_id)
    assert storage_data is not None
    assert storage_data["content"] == "stored?"


async def test_multiple_messages_queued_in_order(queue: SQLiteMessageQueue) -> None:
    await queue.send("cto", "backend", "first")
    await queue.send("cto", "backend", "second")
    m1 = await queue.receive("backend")
    m2 = await queue.receive("backend")
    assert m1 is not None and m2 is not None
    assert m1.content == "first"
    assert m2.content == "second"
