from __future__ import annotations

import json

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.backend_agent import BackendSLMAgent, BackendSLMConfig
from application.base_agent import SLMAgentError
from domain.contracts import AgentRole, Task
from observability.error_codes import ErrorCode


def _backend_task() -> Task:
    return Task(
        id="backend-stage2",
        title="Build API with DB",
        description="Implement DB-backed endpoints",
        agent_role=AgentRole.BACKEND,
        dependencies=[],
        priority=1,
    )


def _stage2_response(
    *,
    include_models: bool = True,
    model_content: str = "from sqlalchemy import Column, Integer, String",
) -> str:
    files: list[dict[str, str]] = [
        {
            "name": "database.py",
            "path": "backend/database.py",
            "content": "from sqlalchemy import create_engine",
            "type": "python",
        },
        {
            "name": "env.py",
            "path": "backend/alembic/env.py",
            "content": "from alembic import context",
            "type": "python",
        },
        {
            "name": "0001_initial.py",
            "path": "backend/alembic/versions/0001_initial.py",
            "content": "def upgrade():\n    pass",
            "type": "python",
        },
    ]
    if include_models:
        files.append(
            {
                "name": "todo.py",
                "path": "backend/models/todo.py",
                "content": model_content,
                "type": "python",
            }
        )

    payload = {
        "approach": "FastAPI + SQLAlchemy + Alembic",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": files,
        "dependencies": ["fastapi", "sqlalchemy", "alembic"],
        "setup_commands": ["pip install fastapi sqlalchemy alembic"],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_backend_stage2_success_with_required_patterns_and_prompt_selection() -> None:
    llm = MockLLMProvider(response=_stage2_response())
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage2_success",
        config=BackendSLMConfig(stage=2, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_backend_task())

    paths = {file.path for file in result.files}
    assert "backend/database.py" in paths
    assert "backend/alembic/env.py" in paths
    assert "backend/alembic/versions/0001_initial.py" in paths
    assert any("/models/" in path and path.endswith(".py") for path in paths)

    call = llm.calls[0]
    messages = call["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "Stage 2 must include:" in system_prompt


@pytest.mark.asyncio
async def test_backend_stage2_retry_when_models_pattern_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage2_response(include_models=False),
            _stage2_response(include_models=True),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage2_retry",
        config=BackendSLMConfig(stage=2, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert any("/models/" in file.path for file in result.files)
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_backend_stage2_model_file_contains_sqlalchemy_keyword() -> None:
    llm = MockLLMProvider(
        response=_stage2_response(
            include_models=True,
            model_content="from sqlalchemy.orm import Mapped, mapped_column",
        )
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage2_sqlalchemy",
        config=BackendSLMConfig(stage=2, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_backend_task())

    model_files = [file for file in result.files if "/models/" in file.path]
    assert model_files
    assert any("sqlalchemy" in file.content.lower() for file in model_files)


def test_backend_stage2_invalid_stage_raises_system_config() -> None:
    with pytest.raises(SLMAgentError) as exc_info:
        BackendSLMAgent(
            llm=MockLLMProvider(response=_stage2_response()),
            workspace=MockWorkSpace(),
            queue=MockMessageQueue(),
            run_id="run_backend_stage2_invalid_stage",
            config=BackendSLMConfig(stage=99),
        )

    assert exc_info.value.code is ErrorCode.E_SYSTEM_CONFIG

