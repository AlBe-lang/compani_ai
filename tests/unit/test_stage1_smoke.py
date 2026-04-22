from __future__ import annotations

import json

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from domain.contracts import TaskResult, WorkItem, WorkStatus
from domain.ports import EventBusPort, LLMProvider, MessageQueuePort, StoragePort, WorkSpacePort
from observability.error_codes import ErrorCode
from observability.ids import generate_run_id
from observability.logger import configure_logging, get_logger


def test_protocols_and_error_codes_importable() -> None:
    assert LLMProvider is not None
    assert WorkSpacePort is not None
    assert MessageQueuePort is not None
    assert StoragePort is not None
    assert EventBusPort is not None
    assert ErrorCode.E_PARSE_JSON.value == "E-PARSE-JSON"


def test_logger_prints_json_with_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(force=True)
    run_id = generate_run_id()
    logger = get_logger(component="stage1", run_id=run_id)
    logger.info("smoke_log")
    captured = capsys.readouterr().err.strip()
    payload = json.loads(captured)
    assert payload["event"] == "smoke_log"
    assert payload["run_id"] == run_id
    assert payload["component"] == "stage1"


@pytest.mark.asyncio
async def test_mock_llm_provider_returns_injected_response() -> None:
    llm = MockLLMProvider(response='{"project_name":"demo"}')
    response = await llm.generate(
        model="mock-model",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert response == '{"project_name":"demo"}'
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_mock_workspace_register_and_update() -> None:
    workspace = MockWorkSpace()
    item_id = await workspace.register(
        WorkItem(
            id="w1",
            task_id="t1",
            agent_id="backend",
            status=WorkStatus.PLANNED,
        )
    )
    assert item_id == "w1"

    await workspace.set_status("w1", WorkStatus.BLOCKED)
    item = await workspace.get("w1")
    assert item is not None
    assert item.status is WorkStatus.BLOCKED
    assert await workspace.detect_blocking("w1") is True

    await workspace.attach_result(
        "w1",
        TaskResult(
            task_id="t1",
            agent_id="backend",
            approach="mock",
            code="pass",
            success=True,
            files=[],
        ),
    )
    updated = await workspace.get("w1")
    assert updated is not None
    assert updated.result is not None
    assert updated.result.task_id == "t1"


@pytest.mark.asyncio
async def test_mock_message_queue_send_and_receive() -> None:
    queue = MockMessageQueue()
    message_id = await queue.send("frontend", "backend", "API endpoint?")
    assert message_id.startswith("msg_")

    message = await queue.receive("backend", timeout_sec=0.1)
    assert message is not None
    assert message.from_agent == "frontend"
    assert message.to_agent == "backend"

    answer = await queue.ask("frontend", "backend", "health?", timeout_sec=0.01)
    assert answer == ""
