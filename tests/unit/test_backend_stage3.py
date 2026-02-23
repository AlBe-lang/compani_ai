from __future__ import annotations

import json

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.backend_agent import BackendSLMAgent, BackendSLMConfig
from domain.contracts import AgentRole, Task


def _backend_task(task_id: str = "backend-stage3") -> Task:
    return Task(
        id=task_id,
        title="Build API with validation",
        description="Implement DB-backed endpoints with robust validation",
        agent_role=AgentRole.BACKEND,
        dependencies=[],
        priority=1,
    )


def _stage1_response() -> str:
    payload = {
        "approach": "FastAPI CRUD scaffold",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": [
            {
                "name": "main.py",
                "path": "backend/main.py",
                "content": "from fastapi import FastAPI\napp = FastAPI()",
                "type": "python",
            }
        ],
        "dependencies": ["fastapi", "pydantic"],
        "setup_commands": ["pip install fastapi pydantic"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _stage2_response() -> str:
    payload = {
        "approach": "FastAPI + SQLAlchemy + Alembic",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": [
            {
                "name": "database.py",
                "path": "backend/database.py",
                "content": "from sqlalchemy import create_engine",
                "type": "python",
            },
            {
                "name": "todo.py",
                "path": "backend/models/todo.py",
                "content": "from sqlalchemy.orm import Mapped, mapped_column",
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
        ],
        "dependencies": ["fastapi", "sqlalchemy", "alembic"],
        "setup_commands": ["pip install fastapi sqlalchemy alembic"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _stage3_response(
    *,
    include_http_exception: bool = True,
    include_error_response_schema: bool = True,
) -> str:
    router_content = (
        "from fastapi import APIRouter, HTTPException\n"
        "router = APIRouter()\n"
        "@router.get('/todos/{todo_id}')\n"
        "def get_todo(todo_id: int):\n"
        "    if todo_id < 1:\n"
        "        raise HTTPException(status_code=400, detail='invalid id')\n"
        "    return {'id': todo_id}\n"
    )
    if not include_http_exception:
        router_content = (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.get('/todos/{todo_id}')\n"
            "def get_todo(todo_id: int):\n"
            "    return {'id': todo_id}\n"
        )

    files: list[dict[str, str]] = [
        {
            "name": "database.py",
            "path": "backend/database.py",
            "content": "from sqlalchemy import create_engine",
            "type": "python",
        },
        {
            "name": "todo.py",
            "path": "backend/models/todo.py",
            "content": "from sqlalchemy.orm import Mapped, mapped_column",
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
        {
            "name": "todo.py",
            "path": "backend/routers/todo.py",
            "content": router_content,
            "type": "python",
        },
    ]

    if include_error_response_schema:
        files.append(
            {
                "name": "error_response.py",
                "path": "backend/schemas/error_response.py",
                "content": (
                    "from pydantic import BaseModel\n\n"
                    "class ErrorResponse(BaseModel):\n"
                    "    code: str\n"
                    "    message: str\n"
                ),
                "type": "python",
            }
        )

    payload = {
        "approach": "FastAPI + SQLAlchemy + Alembic + validation",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": files,
        "dependencies": ["fastapi", "sqlalchemy", "alembic", "pydantic"],
        "setup_commands": ["pip install fastapi sqlalchemy alembic pydantic"],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_backend_stage3_success_with_validation_patterns_and_prompt_selection() -> None:
    llm = MockLLMProvider(response=_stage3_response())
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage3_success",
        config=BackendSLMConfig(stage=3, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_backend_task())

    assert any("HTTPException" in file.content for file in result.files)
    assert any(
        file.path.endswith("/schemas/error_response.py") and "ErrorResponse" in file.content
        for file in result.files
    )

    call = llm.calls[0]
    messages = call["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "Stage 3 must include" in system_prompt


@pytest.mark.asyncio
async def test_backend_stage3_retry_when_http_exception_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(include_http_exception=False),
            _stage3_response(include_http_exception=True),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage3_retry_http_exception",
        config=BackendSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert any("HTTPException" in file.content for file in result.files)
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_backend_stage3_retry_when_error_response_schema_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(include_error_response_schema=False),
            _stage3_response(include_error_response_schema=True),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage3_retry_error_schema",
        config=BackendSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert any(file.path.endswith("/schemas/error_response.py") for file in result.files)
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_backend_stage3_addition_keeps_stage1_and_stage2_paths_working() -> None:
    stage1_agent = BackendSLMAgent(
        llm=MockLLMProvider(response=_stage1_response()),
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage3_regression_stage1",
        config=BackendSLMConfig(stage=1, retry_delays=(0.0,)),
    )
    stage1_result = await stage1_agent.execute_task(_backend_task("backend-stage1-regression"))
    assert stage1_result.success is True

    stage2_agent = BackendSLMAgent(
        llm=MockLLMProvider(response=_stage2_response()),
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage3_regression_stage2",
        config=BackendSLMConfig(stage=2, retry_delays=(0.0,)),
    )
    stage2_result = await stage2_agent.execute_task(_backend_task("backend-stage2-regression"))
    assert stage2_result.success is True
