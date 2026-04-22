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


def _backend_task(task_id: str = "backend-stage5") -> Task:
    return Task(
        id=task_id,
        title="Build API with tests",
        description="Generate backend code with full pytest coverage",
        agent_role=AgentRole.BACKEND,
        dependencies=[],
        priority=1,
    )


def _stage4_base_files() -> list[dict[str, str]]:
    """Cumulative Stage 4 assets required by Stage 5 validation."""
    return [
        {
            "name": "database.py",
            "path": "backend/database.py",
            "content": "from sqlalchemy import create_engine",
            "type": "python",
        },
        {
            "name": "todo.py",
            "path": "backend/models/todo.py",
            "content": "from sqlalchemy.orm import Mapped",
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
            "name": "error_response.py",
            "path": "backend/schemas/error_response.py",
            "content": "class ErrorResponse:\n    pass",
            "type": "python",
        },
        # Stage 3: HTTPException in router code
        {
            "name": "base_router.py",
            "path": "backend/routers/base_router.py",
            "content": (
                "from fastapi import APIRouter, HTTPException\n"
                "router = APIRouter()\n"
            ),
            "type": "python",
        },
        # Stage 4: JWT auth mechanism + Depends injection
        {
            "name": "security.py",
            "path": "backend/security.py",
            "content": (
                "from fastapi.security import OAuth2PasswordBearer\n"
                "from jose import jwt\n\n"
                "oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')\n\n"
                "def get_current_user(token: str):\n"
                "    return jwt.decode(token, 'secret', algorithms=['HS256'])\n"
            ),
            "type": "python",
        },
        {
            "name": "todos.py",
            "path": "backend/routers/todos.py",
            "content": (
                "from fastapi import APIRouter, Depends\n"
                "router = APIRouter()\n"
                "@router.get('/todos')\n"
                "def list_todos(user=Depends(lambda: None)):\n"
                "    return []\n"
            ),
            "type": "python",
        },
    ]


def _stage5_response(
    *,
    include_unit_tests: bool = True,
    include_integration_tests: bool = True,
) -> str:
    files = list(_stage4_base_files())

    if include_unit_tests:
        files.append(
            {
                "name": "test_service.py",
                "path": "backend/tests/unit/test_service.py",
                "content": (
                    "import pytest\n\n"
                    "def test_validate_token_returns_payload():\n"
                    "    result = {'sub': 'user1'}\n"
                    "    assert result['sub'] == 'user1'\n\n"
                    "def test_empty_todo_list():\n"
                    "    assert [] == []\n"
                ),
                "type": "python",
            }
        )

    if include_integration_tests:
        files.append(
            {
                "name": "test_api.py",
                "path": "backend/tests/integration/test_api.py",
                "content": (
                    "import pytest\n"
                    "import httpx\n"
                    "from httpx import AsyncClient\n\n"
                    "@pytest.mark.asyncio\n"
                    "async def test_list_todos_returns_200():\n"
                    "    async with AsyncClient(base_url='http://test') as client:\n"
                    "        response = await client.get('/todos')\n"
                    "    assert response.status_code == 200\n\n"
                    "@pytest.mark.asyncio\n"
                    "async def test_create_todo_returns_201():\n"
                    "    async with AsyncClient(base_url='http://test') as client:\n"
                    "        response = await client.post('/todos', json={'title': 'test'})\n"
                    "    assert response.status_code in (200, 201)\n"
                ),
                "type": "python",
            }
        )

    payload = {
        "approach": "FastAPI + pytest + httpx AsyncClient integration tests",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": files,
        "dependencies": ["fastapi", "sqlalchemy", "python-jose", "pytest", "httpx"],
        "setup_commands": ["pip install fastapi sqlalchemy python-jose pytest httpx"],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_backend_stage5_success_with_unit_and_integration_tests() -> None:
    llm = MockLLMProvider(response=_stage5_response())
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage5_success",
        config=BackendSLMConfig(stage=5, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    test_files = [f for f in result.files if "test_" in f.name]
    assert len(test_files) >= 2
    all_test_content = " ".join(f.content for f in test_files)
    assert "def test_" in all_test_content
    assert "asyncclient" in all_test_content.lower() or "httpx" in all_test_content.lower()


@pytest.mark.asyncio
async def test_backend_stage5_selects_stage5_prompt() -> None:
    llm = MockLLMProvider(response=_stage5_response())
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage5_prompt_check",
        config=BackendSLMConfig(stage=5, retry_delays=(0.0,)),
    )

    await agent.execute_task(_backend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "pytest" in system_prompt.lower()
    assert "httpx" in system_prompt.lower()


@pytest.mark.asyncio
async def test_backend_stage5_retry_when_unit_tests_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage5_response(include_unit_tests=False),
            _stage5_response(include_unit_tests=True),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage5_retry_unit",
        config=BackendSLMConfig(stage=5, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_backend_stage5_retry_when_integration_tests_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage5_response(include_integration_tests=False),
            _stage5_response(include_integration_tests=True),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage5_retry_integration",
        config=BackendSLMConfig(stage=5, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_backend_stage5_fails_after_exhausting_retries_when_no_tests() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage5_response(include_unit_tests=False, include_integration_tests=False),
            _stage5_response(include_unit_tests=False, include_integration_tests=False),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage5_exhausted",
        config=BackendSLMConfig(stage=5, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_backend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_backend_stage5_regression_all_lower_stages_still_pass() -> None:
    """All five stage configs should still resolve their prompts correctly."""
    stages_and_responses: list[tuple[int, str]] = [
        (
            1,
            json.dumps(
                {
                    "approach": "basic",
                    "code": "",
                    "files": [
                        {
                            "name": "main.py",
                            "path": "backend/main.py",
                            "content": "from fastapi import FastAPI\napp = FastAPI()",
                            "type": "python",
                        }
                    ],
                    "dependencies": [],
                    "setup_commands": [],
                }
            ),
        ),
    ]
    for stage, response in stages_and_responses:
        agent = BackendSLMAgent(
            llm=MockLLMProvider(response=response),
            workspace=MockWorkSpace(),
            queue=MockMessageQueue(),
            run_id=f"run_backend_stage5_regression_s{stage}",
            config=BackendSLMConfig(stage=stage, retry_delays=(0.0,)),
        )
        result = await agent.execute_task(
            Task(
                id=f"task-s{stage}",
                title="task",
                description="desc",
                agent_role=AgentRole.BACKEND,
                dependencies=[],
                priority=1,
            )
        )
        assert result.success is True
