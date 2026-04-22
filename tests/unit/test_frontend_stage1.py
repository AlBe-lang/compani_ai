from __future__ import annotations

import json

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.frontend_agent import FrontendSLMAgent, FrontendSLMConfig
from application.base_agent import SLMAgentError
from domain.contracts import AgentRole, Task
from observability.error_codes import ErrorCode


def _frontend_task(task_id: str = "frontend-stage1") -> Task:
    return Task(
        id=task_id,
        title="Build Todo UI",
        description="Generate React TypeScript components for a Todo app",
        agent_role=AgentRole.FRONTEND,
        dependencies=[],
        priority=1,
    )


def _stage1_response(
    *,
    include_tsx: bool = True,
    include_props_interface: bool = True,
    include_package_json: bool = True,
    include_tsconfig: bool = True,
) -> str:
    files: list[dict[str, str]] = []

    if include_tsx:
        files.append(
            {
                "name": "TodoItem.tsx",
                "path": "frontend/src/components/TodoItem.tsx",
                "content": (
                    "import React from 'react';\n\n"
                    + (
                        "interface TodoItemProps {\n  id: number;\n  title: string;\n  done: boolean;\n}\n\n"
                        if include_props_interface
                        else "// no type definitions\n\n"
                    )
                    + "const TodoItem = ({ id, title, done }: TodoItemProps) => {\n"
                    "  return (\n"
                    "    <div className=\"todo-item\">\n"
                    "      <span>{title}</span>\n"
                    "    </div>\n"
                    "  );\n"
                    "};\n\n"
                    "export default TodoItem;\n"
                ),
                "type": "tsx",
            }
        )

    if include_package_json:
        files.append(
            {
                "name": "package.json",
                "path": "frontend/package.json",
                "content": json.dumps(
                    {
                        "name": "todo-frontend",
                        "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
                        "devDependencies": {"typescript": "^5.0.0"},
                    }
                ),
                "type": "json",
            }
        )

    if include_tsconfig:
        files.append(
            {
                "name": "tsconfig.json",
                "path": "frontend/tsconfig.json",
                "content": json.dumps(
                    {"compilerOptions": {"target": "ES2020", "jsx": "react-jsx", "strict": True}}
                ),
                "type": "json",
            }
        )

    payload = {
        "approach": "React TypeScript functional components",
        "code": "import React from 'react';",
        "files": files,
        "dependencies": ["react", "react-dom", "typescript"],
        "setup_commands": ["npm install", "npm start"],
        "framework": "react",
        "api_endpoints_used": [],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_frontend_stage1_success() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage1_success",
        config=FrontendSLMConfig(stage=1, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    tsx_files = [f for f in result.files if f.name.endswith(".tsx")]
    assert len(tsx_files) >= 1


@pytest.mark.asyncio
async def test_frontend_stage1_selects_stage1_prompt() -> None:
    llm = MockLLMProvider(response=_stage1_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage1_prompt_check",
        config=FrontendSLMConfig(stage=1, retry_delays=(0.0,)),
    )

    await agent.execute_task(_frontend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "typescript" in system_prompt.lower()
    assert "functional" in system_prompt.lower() or "function" in system_prompt.lower()


@pytest.mark.asyncio
async def test_frontend_stage1_retry_when_tsx_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_tsx=False),
            _stage1_response(include_tsx=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage1_retry_tsx",
        config=FrontendSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage1_retry_when_props_interface_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_props_interface=False),
            _stage1_response(include_props_interface=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage1_retry_props",
        config=FrontendSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage1_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage1_response(include_tsx=False),
            _stage1_response(include_tsx=False),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage1_exhausted",
        config=FrontendSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_frontend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_frontend_stage1_rejects_wrong_framework() -> None:
    payload = {
        "approach": "Flutter",
        "code": "",
        "files": [
            {
                "name": "main.dart",
                "path": "flutter/lib/main.dart",
                "content": "void main() {}",
                "type": "dart",
            }
        ],
        "dependencies": [],
        "setup_commands": [],
        "framework": "flutter",
        "api_endpoints_used": [],
    }
    llm = MockLLMProvider(
        responses=[
            json.dumps(payload),
            _stage1_response(),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage1_wrong_framework",
        config=FrontendSLMConfig(stage=1, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2
