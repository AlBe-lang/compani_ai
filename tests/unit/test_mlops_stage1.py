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


def _mlops_task(task_id: str = "mlops-stage1") -> Task:
    return Task(
        id=task_id,
        title="Containerise FastAPI app",
        description="Generate Dockerfile and .dockerignore for FastAPI application",
        agent_role=AgentRole.MLOPS,
        dependencies=[],
        priority=1,
    )


def _stage1_response(
    *,
    include_dockerfile: bool = True,
    include_non_root_user: bool = True,
    include_no_cache: bool = True,
    include_dockerignore: bool = True,
) -> str:
    files: list[dict[str, str]] = []

    if include_dockerfile:
        dockerfile_content = "FROM python:3.10-slim AS base\n\n"
        dockerfile_content += "WORKDIR /app\n"
        dockerfile_content += "COPY requirements.txt .\n"
        if include_no_cache:
            dockerfile_content += "RUN pip install --no-cache-dir -r requirements.txt\n"
        else:
            dockerfile_content += "RUN pip install -r requirements.txt\n"
        dockerfile_content += "COPY . .\n\n"
        if include_non_root_user:
            dockerfile_content += "RUN useradd -m appuser\n"
            dockerfile_content += "USER appuser\n\n"
        dockerfile_content += "EXPOSE 8000\n"
        dockerfile_content += 'CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
        files.append(
            {
                "name": "Dockerfile",
                "path": "Dockerfile",
                "content": dockerfile_content,
                "type": "dockerfile",
            }
        )

    if include_dockerignore:
        files.append(
            {
                "name": ".dockerignore",
                "path": ".dockerignore",
                "content": (
                    ".env\n"
                    ".git\n"
                    ".github\n"
                    "__pycache__\n"
                    "*.pyc\n"
                    "*.pyo\n"
                    ".pytest_cache\n"
                    "venv/\n"
                    "*.egg-info/\n"
                    "dist/\n"
                    "build/\n"
                ),
                "type": "text",
            }
        )

    payload = {
        "approach": "Python slim Docker image with non-root user",
        "code": "",
        "files": files,
        "dependencies": [],
        "setup_commands": ["docker build -t app .", "docker run -p 8000:8000 app"],
        "env_vars_required": [],
        "ports_exposed": [8000],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_mlops_stage1_success() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage1_success",
        config=MLOpsSLMConfig(stage=1, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    dockerfile = next((f for f in result.files if f.name == "Dockerfile"), None)
    assert dockerfile is not None


@pytest.mark.asyncio
async def test_mlops_stage1_selects_stage1_prompt() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage1_prompt_check",
        config=MLOpsSLMConfig(stage=1, retry_delays=(0.0,)),
    )

    await agent.execute_task(_mlops_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "dockerfile" in system_prompt.lower()
    assert "non-root" in system_prompt.lower() or "user" in system_prompt.lower()


@pytest.mark.asyncio
async def test_mlops_stage1_retry_when_non_root_user_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_non_root_user=False),
            _stage1_response(include_non_root_user=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage1_retry_user",
        config=MLOpsSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage1_retry_when_no_cache_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_no_cache=False),
            _stage1_response(include_no_cache=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage1_retry_cache",
        config=MLOpsSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage1_retry_when_dockerignore_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_dockerignore=False),
            _stage1_response(include_dockerignore=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage1_retry_dockerignore",
        config=MLOpsSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage1_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_dockerfile=False, include_dockerignore=False),
            _stage1_response(include_dockerfile=False, include_dockerignore=False),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage1_exhausted",
        config=MLOpsSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_mlops_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_mlops_stage1_fails_when_env_vars_required_missing() -> None:
    """env_vars_required field must be present (even if empty list)."""
    payload = {
        "approach": "basic",
        "code": "",
        "files": [
            {
                "name": "Dockerfile",
                "path": "Dockerfile",
                "content": "FROM python:3.10-slim\nWORKDIR /app\nUSER nobody\nRUN pip install --no-cache-dir flask\n",  # noqa: E501
                "type": "dockerfile",
            },
            {
                "name": ".dockerignore",
                "path": ".dockerignore",
                "content": ".env\n.git\n",
                "type": "text",
            },
        ],
        "dependencies": [],
        "setup_commands": [],
        "ports_exposed": [8000],
        # env_vars_required intentionally omitted
    }
    llm = MockLLMProvider(
        responses=[
            json.dumps(payload),
            _stage1_response(),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage1_missing_env_vars",
        config=MLOpsSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2
