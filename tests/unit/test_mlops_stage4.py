from __future__ import annotations

import json

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.mlops_agent import MLOpsSLMAgent, MLOpsSLMConfig
from application.base_agent import SLMAgentError
from domain.contracts import AgentRole, Task
from observability.error_codes import ErrorCode


def _mlops_task(task_id: str = "mlops-stage4") -> Task:
    return Task(
        id=task_id,
        title="Add monitoring and deployment scripts",
        description="Prometheus config, .env.example, idempotent deploy script",
        agent_role=AgentRole.MLOPS,
        dependencies=[],
        priority=1,
    )


def _stage3_base_files() -> list[dict[str, str]]:
    return [
        {
            "name": "Dockerfile",
            "path": "Dockerfile",
            "content": (
                "FROM python:3.10-slim\n"
                "WORKDIR /app\n"
                "RUN pip install --no-cache-dir flask\n"
                "RUN useradd -m appuser\nUSER appuser\n"
                "EXPOSE 8000\nCMD [\"python\", \"app.py\"]\n"
            ),
            "type": "dockerfile",
        },
        {
            "name": ".dockerignore",
            "path": ".dockerignore",
            "content": ".env\n.git\n__pycache__\n",
            "type": "text",
        },
        {
            "name": "docker-compose.yml",
            "path": "docker-compose.yml",
            "content": (
                "version: '3.8'\nservices:\n  api:\n"
                "    build: .\n"
                "    environment:\n      - DATABASE_URL=${DATABASE_URL}\n"
                "    restart: unless-stopped\n"
                "    healthcheck:\n"
                '      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]\n'
                "      interval: 30s\n      timeout: 10s\n      retries: 3\n"
            ),
            "type": "yaml",
        },
        {
            "name": "ci.yml",
            "path": ".github/workflows/ci.yml",
            "content": (
                "name: CI\non:\n  push:\n    branches: [main]\njobs:\n"
                "  lint:\n    runs-on: ubuntu-latest\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - uses: actions/setup-python@v5\n"
                "        with:\n          python-version: '3.10'\n          cache: 'pip'\n"
                "      - run: black --check .\n"
                "  test:\n    runs-on: ubuntu-latest\n    needs: lint\n    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - run: pytest tests/unit -v\n"
            ),
            "type": "yaml",
        },
        {
            "name": "Makefile",
            "path": "Makefile",
            "content": (
                ".PHONY: lint test\n"
                "lint:\n\tblack --check .\n"
                "test:\n\tpytest tests/unit -v\n"
                "test-fast:\n\tpytest tests/unit -v -x\n"
                "format:\n\tblack .\n"
                "setup:\n\tbash deploy/setup.sh\n"
                "deploy:\n\tbash deploy/run.sh\n"
            ),
            "type": "text",
        },
    ]


def _stage4_response(
    *,
    include_prometheus: bool = True,
    include_scrape_configs: bool = True,
    include_env_example: bool = True,
    include_deploy_script: bool = True,
    include_set_e: bool = True,
    include_info_prefix: bool = True,
) -> str:
    files = list(_stage3_base_files())

    if include_prometheus:
        prom_content = "global:\n  scrape_interval: 15s\n\n"
        if include_scrape_configs:
            prom_content += (
                "scrape_configs:\n"
                "  - job_name: 'api'\n"
                "    static_configs:\n"
                "      - targets: ['localhost:8000']\n"
            )
        files.append(
            {
                "name": "prometheus.yml",
                "path": "prometheus.yml",
                "content": prom_content,
                "type": "yaml",
            }
        )

    if include_env_example:
        files.append(
            {
                "name": ".env.example",
                "path": ".env.example",
                "content": (
                    "# Required environment variables\n"
                    "DATABASE_URL=postgres://user:password@localhost:5432/dbname\n"
                    "SECRET_KEY=your-secret-key-here\n"
                    "APP_ENV=development\n"
                ),
                "type": "text",
            }
        )

    if include_deploy_script:
        script_content = "#!/bin/bash\n"
        if include_set_e:
            script_content += "set -euo pipefail\n\n"
        if include_info_prefix:
            script_content += 'echo "[INFO] Starting deployment..."\n\n'
            script_content += 'if ! command -v docker &>/dev/null; then\n'
            script_content += '    echo "[ERROR] Docker is not installed." >&2\n'
            script_content += "    exit 1\nfi\n\n"
            script_content += 'echo "[INFO] Building Docker image..."\n'
        script_content += "docker-compose up --build -d\n"
        files.append(
            {
                "name": "run.sh",
                "path": "deploy/run.sh",
                "content": script_content,
                "type": "text",
            }
        )

    payload = {
        "approach": "Prometheus monitoring + .env.example + idempotent deploy script",
        "code": "",
        "files": files,
        "dependencies": [],
        "setup_commands": ["bash deploy/run.sh"],
        "env_vars_required": ["DATABASE_URL", "SECRET_KEY"],
        "ports_exposed": [8000, 9090],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_mlops_stage4_success() -> None:
    llm = MockLLMProvider(response=_stage4_response())
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage4_success",
        config=MLOpsSLMConfig(stage=4, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    prom = next((f for f in result.files if "prometheus" in f.name), None)
    assert prom is not None
    env_ex = next((f for f in result.files if f.name == ".env.example"), None)
    assert env_ex is not None


@pytest.mark.asyncio
async def test_mlops_stage4_selects_stage4_prompt() -> None:
    llm = MockLLMProvider(response=_stage4_response())
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage4_prompt_check",
        config=MLOpsSLMConfig(stage=4, retry_delays=(0.0,)),
    )

    await agent.execute_task(_mlops_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "prometheus" in system_prompt.lower()
    assert "set -euo pipefail" in system_prompt or "pipefail" in system_prompt


@pytest.mark.asyncio
async def test_mlops_stage4_retry_when_prometheus_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_prometheus=False),
            _stage4_response(include_prometheus=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage4_retry_prometheus",
        config=MLOpsSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage4_retry_when_deploy_script_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_deploy_script=False),
            _stage4_response(include_deploy_script=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage4_retry_deploy",
        config=MLOpsSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage4_retry_when_set_e_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_set_e=False),
            _stage4_response(include_set_e=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage4_retry_set_e",
        config=MLOpsSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage4_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(
                include_prometheus=False,
                include_env_example=False,
                include_deploy_script=False,
            ),
            _stage4_response(
                include_prometheus=False,
                include_env_example=False,
                include_deploy_script=False,
            ),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage4_exhausted",
        config=MLOpsSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_mlops_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_mlops_stage4_regression_stage1_still_passes() -> None:
    stage1_payload = {
        "approach": "basic Dockerfile",
        "code": "",
        "files": [
            {
                "name": "Dockerfile",
                "path": "Dockerfile",
                "content": (
                    "FROM python:3.10-slim\n"
                    "WORKDIR /app\n"
                    "RUN pip install --no-cache-dir flask\n"
                    "RUN useradd -m appuser\nUSER appuser\n"
                    "EXPOSE 8000\nCMD [\"python\", \"app.py\"]\n"
                ),
                "type": "dockerfile",
            },
            {
                "name": ".dockerignore",
                "path": ".dockerignore",
                "content": ".env\n.git\n__pycache__\n*.pyc\n",
                "type": "text",
            },
        ],
        "dependencies": [],
        "setup_commands": ["docker build -t app ."],
        "env_vars_required": [],
        "ports_exposed": [8000],
    }
    agent = MLOpsSLMAgent(
        llm=MockLLMProvider(response=json.dumps(stage1_payload)),
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage4_regression_s1",
        config=MLOpsSLMConfig(stage=1, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(
        Task(
            id="task-mlops-s1",
            title="Basic container",
            description="Dockerfile only",
            agent_role=AgentRole.MLOPS,
            dependencies=[],
            priority=1,
        )
    )

    assert result.success is True
