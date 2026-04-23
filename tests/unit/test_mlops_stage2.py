from __future__ import annotations

import json

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.base_agent import SLMAgentError
from application.mlops_agent import MLOpsSLMAgent, MLOpsSLMConfig
from domain.contracts import AgentRole, Task
from observability.error_codes import ErrorCode


def _mlops_task(task_id: str = "mlops-stage2") -> Task:
    return Task(
        id=task_id,
        title="Add docker-compose",
        description="Generate docker-compose.yml with healthcheck and env vars",
        agent_role=AgentRole.MLOPS,
        dependencies=[],
        priority=1,
    )


def _stage1_base_files() -> list[dict[str, str]]:
    return [
        {
            "name": "Dockerfile",
            "path": "Dockerfile",
            "content": (
                "FROM python:3.10-slim AS base\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
                "RUN useradd -m appuser\n"
                "USER appuser\n"
                "EXPOSE 8000\n"
                'CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
            ),
            "type": "dockerfile",
        },
        {
            "name": ".dockerignore",
            "path": ".dockerignore",
            "content": ".env\n.git\n__pycache__\n*.pyc\n.pytest_cache\nvenv/\n",
            "type": "text",
        },
    ]


def _stage2_response(
    *,
    include_compose: bool = True,
    include_healthcheck: bool = True,
    include_env_var_ref: bool = True,
    include_restart: bool = True,
) -> str:
    files = list(_stage1_base_files())

    if include_compose:
        compose_content = "version: '3.8'\n\nservices:\n  api:\n"
        compose_content += "    build:\n      context: .\n      dockerfile: Dockerfile\n"
        compose_content += '    ports:\n      - "8000:8000"\n'
        if include_env_var_ref:
            compose_content += "    environment:\n      - DATABASE_URL=${DATABASE_URL}\n"
        else:
            compose_content += "    environment:\n      - DATABASE_URL=postgres://localhost/db\n"
        if include_restart:
            compose_content += "    restart: unless-stopped\n"
        if include_healthcheck:
            compose_content += (
                "    healthcheck:\n"
                '      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]\n'
                "      interval: 30s\n"
                "      timeout: 10s\n"
                "      retries: 3\n"
            )
        compose_content += "\nvolumes:\n  db_data:\n"
        files.append(
            {
                "name": "docker-compose.yml",
                "path": "docker-compose.yml",
                "content": compose_content,
                "type": "yaml",
            }
        )

    payload = {
        "approach": "docker-compose with healthcheck and env vars",
        "code": "",
        "files": files,
        "dependencies": [],
        "setup_commands": ["docker-compose up --build"],
        "env_vars_required": ["DATABASE_URL"],
        "ports_exposed": [8000],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_mlops_stage2_success() -> None:
    llm = MockLLMProvider(response=_stage2_response())
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage2_success",
        config=MLOpsSLMConfig(stage=2, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    compose = next((f for f in result.files if "docker-compose" in f.name), None)
    assert compose is not None


@pytest.mark.asyncio
async def test_mlops_stage2_selects_stage2_prompt() -> None:
    llm = MockLLMProvider(response=_stage2_response())
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage2_prompt_check",
        config=MLOpsSLMConfig(stage=2, retry_delays=(0.0,)),
    )

    await agent.execute_task(_mlops_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "healthcheck" in system_prompt.lower()
    assert "docker-compose" in system_prompt.lower()


@pytest.mark.asyncio
async def test_mlops_stage2_retry_when_healthcheck_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage2_response(include_healthcheck=False),
            _stage2_response(include_healthcheck=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage2_retry_healthcheck",
        config=MLOpsSLMConfig(stage=2, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage2_retry_when_env_var_ref_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage2_response(include_env_var_ref=False),
            _stage2_response(include_env_var_ref=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage2_retry_env",
        config=MLOpsSLMConfig(stage=2, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage2_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage2_response(include_compose=False),
            _stage2_response(include_compose=False),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage2_exhausted",
        config=MLOpsSLMConfig(stage=2, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_mlops_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA
