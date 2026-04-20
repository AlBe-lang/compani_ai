from __future__ import annotations

import asyncio
import json
from collections import defaultdict

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.backend_agent import BackendSLMAgent, BackendSLMConfig
from application.base_agent import SLMAgentError
from domain.contracts import AgentRole, Task, WorkItem, WorkStatus
from observability.error_codes import ErrorCode
from observability.logger import configure_logging


class TrackingWorkSpace(MockWorkSpace):
    def __init__(self) -> None:
        super().__init__()
        self.registered_ids: list[str] = []
        self.status_history: dict[str, list[WorkStatus]] = defaultdict(list)

    async def register(self, work_item: WorkItem) -> str:
        self.registered_ids.append(work_item.id)
        self.status_history[work_item.id].append(work_item.status)
        return await super().register(work_item)

    async def set_status(self, work_item_id: str, status: WorkStatus) -> None:
        self.status_history[work_item_id].append(status)
        await super().set_status(work_item_id, status)


class TimeoutAskQueue(MockMessageQueue):
    def __init__(self) -> None:
        super().__init__()
        self.ask_calls = 0

    async def ask(
        self,
        from_agent: str,
        to_agent: str,
        question: str,
        context: dict[str, object] | None = None,
        timeout_sec: float = 30.0,
    ) -> str:
        self.ask_calls += 1
        raise asyncio.TimeoutError


def _backend_task(
    *,
    dependencies: list[str] | None = None,
    description: str = "Build API",
    acceptance_criteria: list[str] | None = None,
) -> Task:
    return Task(
        id="backend-crud",
        title="Create CRUD API",
        description=description,
        agent_role=AgentRole.BACKEND,
        acceptance_criteria=acceptance_criteria or [],
        dependencies=dependencies or [],
        priority=1,
    )


def _stage1_response(*, include_path: bool = True) -> str:
    file_payload: dict[str, object] = {
        "name": "main.py",
        "path": "backend/main.py",
        "content": "from fastapi import FastAPI\napp = FastAPI()",
        "type": "python",
    }
    if not include_path:
        file_payload.pop("path")

    payload = {
        "approach": "FastAPI CRUD scaffold",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": [file_payload],
        "dependencies": ["fastapi", "pydantic"],
        "setup_commands": ["pip install fastapi pydantic"],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_backend_stage1_execute_success_waiting_to_in_progress() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    workspace = TrackingWorkSpace()
    queue = MockMessageQueue()
    dependency_id = "work_dep_1"
    await workspace.register(
        WorkItem(
            id=dependency_id,
            task_id="dep-task",
            agent_id="backend",
            status=WorkStatus.IN_PROGRESS,
        )
    )

    agent = BackendSLMAgent(
        llm=llm,
        workspace=workspace,
        queue=queue,
        run_id="run_backend_stage1_ok",
        config=BackendSLMConfig(
            retry_delays=(0.0,),
            dep_timeout_sec=0.2,
            dep_poll_sec=0.001,
        ),
    )
    task = _backend_task(dependencies=[dependency_id])

    async def release_dependency() -> None:
        await asyncio.sleep(0.005)
        await workspace.set_status(dependency_id, WorkStatus.DONE)

    release_task = asyncio.create_task(release_dependency())
    result = await agent.execute_task(task)
    await release_task

    assert result.task_id == task.id
    assert result.agent_id == "backend"
    assert result.success is True
    assert len(llm.calls) == 1

    work_item_id = workspace.registered_ids[-1]
    history = workspace.status_history[work_item_id]
    assert WorkStatus.WAITING in history
    assert WorkStatus.IN_PROGRESS in history
    assert history.index(WorkStatus.WAITING) < history.index(WorkStatus.IN_PROGRESS)

    stored = await workspace.get(work_item_id)
    assert stored is not None
    assert stored.status is WorkStatus.DONE
    assert stored.result is not None
    assert stored.result.task_id == task.id


@pytest.mark.asyncio
async def test_backend_stage1_dependency_timeout_raises_error() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    workspace = TrackingWorkSpace()
    queue = MockMessageQueue()
    dependency_id = "work_dep_timeout"
    await workspace.register(
        WorkItem(
            id=dependency_id,
            task_id="dep-timeout",
            agent_id="backend",
            status=WorkStatus.IN_PROGRESS,
        )
    )

    agent = BackendSLMAgent(
        llm=llm,
        workspace=workspace,
        queue=queue,
        run_id="run_backend_dep_timeout",
        config=BackendSLMConfig(
            retry_delays=(0.0,),
            dep_timeout_sec=0.01,
            dep_poll_sec=0.001,
        ),
    )
    task = _backend_task(dependencies=[dependency_id])

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(task)

    assert exc_info.value.code is ErrorCode.E_DEPS_TIMEOUT
    assert len(llm.calls) == 0

    work_item_id = workspace.registered_ids[-1]
    failed = await workspace.get(work_item_id)
    assert failed is not None
    assert failed.status is WorkStatus.FAILED
    assert failed.result is not None
    assert failed.result.error_code is ErrorCode.E_DEPS_TIMEOUT


@pytest.mark.asyncio
async def test_backend_stage1_qa_timeout_fallback_continues() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    workspace = TrackingWorkSpace()
    queue = TimeoutAskQueue()
    agent = BackendSLMAgent(
        llm=llm,
        workspace=workspace,
        queue=queue,
        run_id="run_backend_qa_timeout",
        config=BackendSLMConfig(retry_delays=(0.0,)),
    )
    task = _backend_task(description="Need endpoint format?")

    result = await agent.execute_task(task)

    assert queue.ask_calls == 1
    assert result.success is True
    assert result.task_id == task.id
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_backend_stage1_retries_when_file_shape_invalid_then_succeeds() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_path=False),
            _stage1_response(include_path=True),
        ]
    )
    workspace = TrackingWorkSpace()
    queue = MockMessageQueue()
    agent = BackendSLMAgent(
        llm=llm,
        workspace=workspace,
        queue=queue,
        run_id="run_backend_file_retry",
        config=BackendSLMConfig(
            max_retries=2,
            retry_delays=(0.0, 0.0),
        ),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert result.files[0].path == "backend/main.py"
    assert len(llm.calls) == 2
    second_messages = llm.calls[1]["messages"]
    assert isinstance(second_messages, list)
    second_user_content = second_messages[1]["content"]
    assert isinstance(second_user_content, str)
    assert "Return only valid JSON." in second_user_content


@pytest.mark.asyncio
async def test_backend_stage1_acceptance_criteria_can_trigger_qa() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    workspace = TrackingWorkSpace()
    queue = TimeoutAskQueue()
    agent = BackendSLMAgent(
        llm=llm,
        workspace=workspace,
        queue=queue,
        run_id="run_backend_acceptance_qa",
        config=BackendSLMConfig(retry_delays=(0.0,)),
    )
    task = _backend_task(
        description="Implement request validation",
        acceptance_criteria=["External API schema must match partner interface contract."],
    )

    result = await agent.execute_task(task)

    assert queue.ask_calls == 1
    assert result.success is True


@pytest.mark.asyncio
async def test_backend_stage1_emits_required_execution_logs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(force=True)
    llm = MockLLMProvider(response=_stage1_response())
    workspace = TrackingWorkSpace()
    queue = MockMessageQueue()
    dependency_id = "work_dep_done"
    await workspace.register(
        WorkItem(
            id=dependency_id,
            task_id="dep-done",
            agent_id="backend",
            status=WorkStatus.DONE,
        )
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=workspace,
        queue=queue,
        run_id="run_backend_required_logs",
        config=BackendSLMConfig(retry_delays=(0.0,)),
    )

    await agent.execute_task(_backend_task(dependencies=[dependency_id]))

    payloads = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    events = {payload.get("event") for payload in payloads}
    assert "slm.deps.waiting" in events
    assert "slm.qa.sent" in events
    assert "slm.llm.call" in events
