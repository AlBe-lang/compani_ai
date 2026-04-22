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


def _backend_task(task_id: str = "backend-stage4") -> Task:
    return Task(
        id=task_id,
        title="Build API with JWT auth",
        description="Implement JWT-protected endpoints",
        agent_role=AgentRole.BACKEND,
        dependencies=[],
        priority=1,
    )


def _base_files() -> list[dict[str, str]]:
    """Minimal Stage 3 asset set (cumulative) shared by all Stage 4 responses.

    Includes HTTPException usage and ErrorResponse schema required by Stage 3
    validation, plus Alembic/models required by Stage 2 validation.
    """
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
        # Stage 3 requires HTTPException in router/service code
        {
            "name": "base_router.py",
            "path": "backend/routers/base_router.py",
            "content": (
                "from fastapi import APIRouter, HTTPException\n"
                "router = APIRouter()\n"
                "@router.get('/{id}')\n"
                "def get_item(id: int):\n"
                "    if id < 1:\n"
                "        raise HTTPException(status_code=404, detail='not found')\n"
            ),
            "type": "python",
        },
    ]


def _stage4_response(
    *,
    include_auth_mechanism: bool = True,
    include_depends: bool = True,
) -> str:
    # Router content: Depends() injected only when include_depends=True
    if include_depends:
        router_content = (
            "from fastapi import APIRouter, Depends\n"
            "from backend.security import get_current_user\n"
            "router = APIRouter()\n"
            "@router.get('/todos')\n"
            "def list_todos(current_user=Depends(get_current_user)):\n"
            "    return []\n"
        )
    else:
        router_content = (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n"
            "@router.get('/todos')\n"
            "def list_todos():\n"
            "    return []\n"
        )

    # Security module: auth keywords present only when include_auth_mechanism=True
    # Does NOT include Depends() so it doesn't accidentally satisfy depends check
    if include_auth_mechanism:
        security_content = (
            "from fastapi.security import OAuth2PasswordBearer\n"
            "from jose import jwt\n\n"
            "oauth2_scheme = OAuth2PasswordBearer(tokenUrl='token')\n\n"
            "def get_current_user(token: str):\n"
            "    payload = jwt.decode(token, 'secret', algorithms=['HS256'])\n"
            "    return payload\n"
        )
    else:
        security_content = "# placeholder module\n"

    files = _base_files() + [
        {
            "name": "todos.py",
            "path": "backend/routers/todos.py",
            "content": router_content,
            "type": "python",
        },
        {
            "name": "security.py",
            "path": "backend/security.py",
            "content": security_content,
            "type": "python",
        },
    ]

    payload = {
        "approach": "FastAPI + OAuth2PasswordBearer + python-jose",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": files,
        "dependencies": ["fastapi", "sqlalchemy", "python-jose", "passlib"],
        "setup_commands": ["pip install fastapi sqlalchemy python-jose passlib"],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_backend_stage4_success_with_auth_and_depends() -> None:
    llm = MockLLMProvider(response=_stage4_response())
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage4_success",
        config=BackendSLMConfig(stage=4, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    all_content = " ".join(f.content for f in result.files).lower()
    assert any(kw in all_content for kw in ("bearer", "oauth2", "jwt", "security"))
    assert "depends(" in all_content


@pytest.mark.asyncio
async def test_backend_stage4_selects_stage4_prompt() -> None:
    llm = MockLLMProvider(response=_stage4_response())
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage4_prompt_check",
        config=BackendSLMConfig(stage=4, retry_delays=(0.0,)),
    )

    await agent.execute_task(_backend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "OAuth2 Bearer" in system_prompt or "JWT" in system_prompt


@pytest.mark.asyncio
async def test_backend_stage4_retry_when_auth_mechanism_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_auth_mechanism=False),
            _stage4_response(include_auth_mechanism=True),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage4_retry_auth",
        config=BackendSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_backend_stage4_retry_when_depends_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_depends=False),
            _stage4_response(include_depends=True),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage4_retry_depends",
        config=BackendSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_backend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_backend_stage4_fails_with_e_parse_schema_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_auth_mechanism=False),
            _stage4_response(include_auth_mechanism=False),
        ]
    )
    agent = BackendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage4_exhausted",
        config=BackendSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_backend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_backend_stage4_regression_keeps_lower_stages_working() -> None:
    """Confirm stage 1, 2, 3 paths are unaffected by stage 4 additions."""
    stage1_payload = {
        "approach": "FastAPI CRUD",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": [
            {
                "name": "main.py",
                "path": "backend/main.py",
                "content": "from fastapi import FastAPI\napp = FastAPI()",
                "type": "python",
            }
        ],
        "dependencies": ["fastapi"],
        "setup_commands": [],
    }
    agent = BackendSLMAgent(
        llm=MockLLMProvider(response=json.dumps(stage1_payload)),
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_backend_stage4_regression",
        config=BackendSLMConfig(stage=1, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(
        Task(
            id="regression-s1",
            title="Basic API",
            description="CRUD",
            agent_role=AgentRole.BACKEND,
            dependencies=[],
            priority=1,
        )
    )

    assert result.success is True
