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


def _mlops_task(task_id: str = "mlops-stage3") -> Task:
    return Task(
        id=task_id,
        title="Add CI/CD pipeline",
        description="Generate GitHub Actions or GitLab CI with Makefile",
        agent_role=AgentRole.MLOPS,
        dependencies=[],
        priority=1,
    )


def _stage2_base_files() -> list[dict[str, str]]:
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
                'CMD ["uvicorn", "main:app"]\n'
            ),
            "type": "dockerfile",
        },
        {
            "name": ".dockerignore",
            "path": ".dockerignore",
            "content": ".env\n.git\n__pycache__\n*.pyc\n",
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
    ]


def _stage3_response(
    *,
    use_github_actions: bool = True,
    use_gitlab_ci: bool = False,
    include_lint_job: bool = True,
    include_test_job: bool = True,
    include_pip_cache: bool = True,
    include_makefile: bool = True,
) -> str:
    files = list(_stage2_base_files())

    if use_github_actions:
        ci_content = "name: CI\n\non:\n  push:\n    branches: [main]\n  pull_request:\n    branches: [main]\n\njobs:\n"
        if include_lint_job:
            ci_content += (
                "  lint:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - name: Set up Python\n"
                "        uses: actions/setup-python@v5\n"
                "        with:\n"
                "          python-version: '3.10'\n"
            )
            if include_pip_cache:
                ci_content += "          cache: 'pip'\n"
            ci_content += (
                "      - name: Lint\n"
                "        run: black --check . && flake8 . && mypy .\n"
            )
        if include_test_job:
            ci_content += (
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    needs: lint\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - name: Test\n"
                "        run: pytest tests/unit -v --cov=. --cov-report=xml\n"
            )
        files.append(
            {
                "name": "ci.yml",
                "path": ".github/workflows/ci.yml",
                "content": ci_content,
                "type": "yaml",
            }
        )

    if use_gitlab_ci:
        gitlab_content = "stages:\n  - lint\n  - test\n\n"
        if include_pip_cache:
            gitlab_content += "cache:\n  paths:\n    - .pip/\n\n"
        if include_lint_job:
            gitlab_content += (
                "lint:\n"
                "  stage: lint\n"
                "  script:\n"
                "    - pip install black flake8 mypy\n"
                "    - black --check .\n"
                "    - flake8 .\n"
                "    - mypy .\n"
            )
        if include_test_job:
            gitlab_content += (
                "test:\n"
                "  stage: test\n"
                "  script:\n"
                "    - pip install -r requirements.txt\n"
                "    - pytest tests/unit -v\n"
            )
        files.append(
            {
                "name": ".gitlab-ci.yml",
                "path": ".gitlab-ci.yml",
                "content": gitlab_content,
                "type": "yaml",
            }
        )

    if include_makefile:
        files.append(
            {
                "name": "Makefile",
                "path": "Makefile",
                "content": (
                    ".PHONY: setup lint format test test-fast deploy\n\n"
                    "setup:\n\tbash deploy/setup.sh\n\n"
                    "lint:\n\tblack --check . && flake8 . && mypy .\n\n"
                    "format:\n\tblack . && isort .\n\n"
                    "test:\n\tpytest tests/unit tests/integration -v\n\n"
                    "test-fast:\n\tpytest tests/unit -v\n\n"
                    "deploy:\n\tbash deploy/run.sh\n"
                ),
                "type": "text",
            }
        )

    payload = {
        "approach": "GitHub Actions CI + Makefile",
        "code": "",
        "files": files,
        "dependencies": [],
        "setup_commands": ["make setup", "make test"],
        "env_vars_required": ["DATABASE_URL"],
        "ports_exposed": [8000],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_mlops_stage3_success_with_github_actions() -> None:
    llm = MockLLMProvider(response=_stage3_response(use_github_actions=True))
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage3_success_github",
        config=MLOpsSLMConfig(stage=3, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    ci_files = [f for f in result.files if ".github/workflows" in f.path]
    assert len(ci_files) >= 1


@pytest.mark.asyncio
async def test_mlops_stage3_success_with_gitlab_ci() -> None:
    llm = MockLLMProvider(
        response=_stage3_response(use_github_actions=False, use_gitlab_ci=True)
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage3_success_gitlab",
        config=MLOpsSLMConfig(stage=3, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    gitlab_files = [f for f in result.files if ".gitlab-ci.yml" in f.path]
    assert len(gitlab_files) >= 1


@pytest.mark.asyncio
async def test_mlops_stage3_selects_stage3_prompt() -> None:
    llm = MockLLMProvider(response=_stage3_response())
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage3_prompt_check",
        config=MLOpsSLMConfig(stage=3, retry_delays=(0.0,)),
    )

    await agent.execute_task(_mlops_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "lint" in system_prompt.lower()
    assert "makefile" in system_prompt.lower() or "ci" in system_prompt.lower()


@pytest.mark.asyncio
async def test_mlops_stage3_retry_when_makefile_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(include_makefile=False),
            _stage3_response(include_makefile=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage3_retry_makefile",
        config=MLOpsSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage3_retry_when_ci_pipeline_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(use_github_actions=False, use_gitlab_ci=False),
            _stage3_response(use_github_actions=True),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage3_retry_ci",
        config=MLOpsSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_mlops_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_mlops_stage3_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(
                use_github_actions=False,
                use_gitlab_ci=False,
                include_makefile=False,
            ),
            _stage3_response(
                use_github_actions=False,
                use_gitlab_ci=False,
                include_makefile=False,
            ),
        ]
    )
    agent = MLOpsSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_mlops_stage3_exhausted",
        config=MLOpsSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_mlops_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA
