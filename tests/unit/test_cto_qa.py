"""Unit tests for CTOAgent Q&A background handler."""

from __future__ import annotations

import asyncio

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.cto_agent import CTOAgent, CTOConfig
from domain.contracts import Message, MessageStatus, MessageType


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_cto(llm: MockLLMProvider | None = None) -> CTOAgent:
    return CTOAgent(
        llm=llm or MockLLMProvider(response="Use PostgreSQL."),
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(),
        run_id="test_run",
    )


def _make_question(from_agent: str = "backend", content: str = "What DB should I use?") -> Message:
    return Message(
        id="msg_001",
        from_agent=from_agent,
        to_agent="cto",
        content=content,
        type=MessageType.QUESTION,
        context={},
        status=MessageStatus.PENDING,
    )


# ------------------------------------------------------------------
# _generate_qa_answer
# ------------------------------------------------------------------


async def test_generate_qa_answer_calls_llm() -> None:
    llm = MockLLMProvider(response="Use PostgreSQL.")
    cto = _make_cto(llm)
    msg = _make_question()
    answer = await cto._generate_qa_answer(msg)
    assert answer == "Use PostgreSQL."
    assert len(llm.calls) == 1


async def test_generate_qa_answer_includes_question_in_messages() -> None:
    llm = MockLLMProvider(response="Yes.")
    cto = _make_cto(llm)
    msg = _make_question(content="What is 2+2?")
    await cto._generate_qa_answer(msg)
    user_content: str = llm.calls[0]["messages"][1]["content"]  # type: ignore[index]
    assert "What is 2+2?" in user_content


async def test_generate_qa_answer_includes_context_in_messages() -> None:
    llm = MockLLMProvider(response="FastAPI.")
    cto = _make_cto(llm)
    msg = Message(
        id="msg_ctx",
        from_agent="backend",
        to_agent="cto",
        content="Which framework?",
        type=MessageType.QUESTION,
        context={"project_type": "REST API"},
        status=MessageStatus.PENDING,
    )
    await cto._generate_qa_answer(msg)
    user_content: str = llm.calls[0]["messages"][1]["content"]  # type: ignore[index]
    assert "REST API" in user_content


# ------------------------------------------------------------------
# _handle_one_question
# ------------------------------------------------------------------


async def test_handle_one_question_sends_answer_back() -> None:
    queue = MockMessageQueue()
    cto = _make_cto(MockLLMProvider(response="Use Redis for caching."))
    msg = _make_question(from_agent="backend")
    await cto._handle_one_question(queue, msg)

    # Answer must land in backend's inbox
    reply = await queue.receive("backend")
    assert reply is not None
    assert reply.type is MessageType.ANSWER
    assert reply.content == "Use Redis for caching."
    assert reply.from_agent == "cto"


async def test_handle_one_question_does_not_crash_on_llm_error() -> None:
    class _FailingLLM(MockLLMProvider):
        async def generate(self, *args: object, **kwargs: object) -> str:  # type: ignore[override]
            raise RuntimeError("LLM timeout")

    queue = MockMessageQueue()
    cto = _make_cto(_FailingLLM())
    msg = _make_question()
    await cto._handle_one_question(queue, msg)  # must not raise


# ------------------------------------------------------------------
# handle_questions — background loop
# ------------------------------------------------------------------


async def test_handle_questions_processes_queued_message() -> None:
    queue = MockMessageQueue()
    cto = _make_cto(MockLLMProvider(response="FastAPI is the right choice."))

    # Put a question in cto's inbox before starting the loop
    await queue.send("frontend", "cto", "Which backend framework?", MessageType.QUESTION)

    task = asyncio.create_task(cto.handle_questions(queue))
    await asyncio.sleep(0.1)  # give the loop time to process
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    reply = await queue.receive("frontend")
    assert reply is not None
    assert reply.type is MessageType.ANSWER


async def test_handle_questions_cancels_cleanly() -> None:
    queue = MockMessageQueue()
    cto = _make_cto()

    task = asyncio.create_task(cto.handle_questions(queue))
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task  # CancelledError must propagate (not be swallowed)


# ------------------------------------------------------------------
# Route question integration: SQLiteMessageQueue + handle_questions
# ------------------------------------------------------------------


async def test_route_question_answered_by_cto_loop() -> None:
    """End-to-end: frontend asks a question, CTO loop answers it via route_question."""
    from adapters.sqlite_message_queue import SQLiteMessageQueue
    from adapters.sqlite_storage import SQLiteStorage

    storage = SQLiteStorage(":memory:")
    await storage.init()
    queue = SQLiteMessageQueue(storage=storage)

    llm = MockLLMProvider(response="Definitely PostgreSQL.")
    cto = _make_cto(llm)

    # Start CTO Q&A background handler
    cto_task = asyncio.create_task(cto.handle_questions(queue))

    # Ask question — route_question will send to "cto" (keyword fallback: "database" → "backend",
    # but with no KG it routes to "cto" as final fallback for unknown)
    # Direct ask to "cto" to keep the test deterministic
    answer = await queue.ask(
        from_agent="frontend",
        to_agent="cto",
        question="What SQL database should I use?",
        timeout_sec=2.0,
    )

    cto_task.cancel()
    try:
        await cto_task
    except asyncio.CancelledError:
        pass

    await storage.close()

    assert answer == "Definitely PostgreSQL."
