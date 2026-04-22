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


def _frontend_task(task_id: str = "frontend-stage3") -> Task:
    return Task(
        id=task_id,
        title="Build Todo UI with API integration",
        description="React TypeScript with fetch, error/loading states, env var",
        agent_role=AgentRole.FRONTEND,
        dependencies=[],
        priority=1,
    )


def _stage2_base_files() -> list[dict[str, str]]:
    return [
        {
            "name": "TodoItem.tsx",
            "path": "frontend/src/components/TodoItem.tsx",
            "content": (
                "import React from 'react';\n"
                "interface TodoItemProps { id: number; title: string; }\n"
                "const TodoItem = ({ id, title }: TodoItemProps) => <div>{title}</div>;\n"
                "export default TodoItem;\n"
            ),
            "type": "tsx",
        },
        {
            "name": "useTodos.ts",
            "path": "frontend/src/hooks/useTodos.ts",
            "content": (
                "import { useState, useEffect } from 'react';\n"
                "export const useTodos = () => {\n"
                "  const [todos, setTodos] = useState<string[]>([]);\n"
                "  useEffect(() => {}, []);\n"
                "  return { todos };\n};\n"
            ),
            "type": "ts",
        },
        {
            "name": "package.json",
            "path": "frontend/package.json",
            "content": json.dumps({"name": "todo-frontend", "dependencies": {"react": "^18.0.0"}}),
            "type": "json",
        },
        {
            "name": "tsconfig.json",
            "path": "frontend/tsconfig.json",
            "content": json.dumps({"compilerOptions": {"target": "ES2020"}}),
            "type": "json",
        },
    ]


def _stage3_response(
    *,
    include_api_module: bool = True,
    include_try_catch: bool = True,
    include_env_var: bool = True,
    include_loading_state: bool = True,
    include_api_endpoints_used: bool = True,
) -> str:
    files = list(_stage2_base_files())

    if include_api_module:
        api_content = "const BASE_URL = "
        if include_env_var:
            api_content += "process.env.REACT_APP_API_URL ?? '';\n\n"
        else:
            api_content += "'http://localhost:8000';\n\n"
        api_content += "export const fetchTodos = async (): Promise<string[]> => {\n"
        if include_try_catch:
            api_content += "  try {\n"
            api_content += "    const res = await fetch(`${BASE_URL}/api/todos`);\n"
            api_content += "    return res.json();\n"
            api_content += "  } catch (err) {\n"
            api_content += "    throw err;\n"
            api_content += "  }\n"
        else:
            api_content += "  const res = await fetch(`${BASE_URL}/api/todos`);\n"
            api_content += "  return res.json();\n"
        api_content += "};\n"
        files.append(
            {
                "name": "todoApi.ts",
                "path": "frontend/src/api/todoApi.ts",
                "content": api_content,
                "type": "ts",
            }
        )

    # Component with loading/error state
    component_content = "import React"
    if include_loading_state:
        component_content += ", { useState } from 'react';\n"
        component_content += "interface TodoListProps { title: string; }\n"
        component_content += "const TodoList = ({ title }: TodoListProps) => {\n"
        component_content += "  const [isLoading, setIsLoading] = React.useState(false);\n"
        component_content += "  const [error, setError] = React.useState<string | null>(null);\n"
        component_content += "  if (isLoading) return <div>Loading...</div>;\n"
        component_content += "  if (error) return <div>{error}</div>;\n"
        component_content += "  return <div>{title}</div>;\n};\n"
        component_content += "export default TodoList;\n"
    else:
        component_content += " from 'react';\n"
        component_content += "interface TodoListProps { title: string; }\n"
        component_content += "const TodoList = ({ title }: TodoListProps) => <div>{title}</div>;\n"
        component_content += "export default TodoList;\n"
    files.append(
        {
            "name": "TodoList.tsx",
            "path": "frontend/src/components/TodoList.tsx",
            "content": component_content,
            "type": "tsx",
        }
    )

    payload = {
        "approach": "React TypeScript fetch API with error/loading states",
        "code": "",
        "files": files,
        "dependencies": ["react", "typescript"],
        "setup_commands": ["npm install"],
        "framework": "react",
        "api_endpoints_used": (
            ["GET /api/todos", "POST /api/todos"] if include_api_endpoints_used else []
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_frontend_stage3_success() -> None:
    llm = MockLLMProvider(response=_stage3_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage3_success",
        config=FrontendSLMConfig(stage=3, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    api_files = [f for f in result.files if "/api/" in f.path]
    assert len(api_files) >= 1


@pytest.mark.asyncio
async def test_frontend_stage3_selects_stage3_prompt() -> None:
    llm = MockLLMProvider(response=_stage3_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage3_prompt_check",
        config=FrontendSLMConfig(stage=3, retry_delays=(0.0,)),
    )

    await agent.execute_task(_frontend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "api" in system_prompt.lower()
    assert "error" in system_prompt.lower()


@pytest.mark.asyncio
async def test_frontend_stage3_retry_when_try_catch_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(include_try_catch=False),
            _stage3_response(include_try_catch=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage3_retry_try_catch",
        config=FrontendSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage3_retry_when_env_var_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(include_env_var=False),
            _stage3_response(include_env_var=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage3_retry_env_var",
        config=FrontendSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage3_retry_when_api_endpoints_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(include_api_endpoints_used=False),
            _stage3_response(include_api_endpoints_used=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage3_retry_endpoints",
        config=FrontendSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage3_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage3_response(include_api_module=False, include_api_endpoints_used=False),
            _stage3_response(include_api_module=False, include_api_endpoints_used=False),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage3_exhausted",
        config=FrontendSLMConfig(stage=3, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_frontend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA
