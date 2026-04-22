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


def _frontend_task(task_id: str = "frontend-stage2") -> Task:
    return Task(
        id=task_id,
        title="Build Todo UI with hooks",
        description="React TypeScript with useState, useEffect, custom hooks",
        agent_role=AgentRole.FRONTEND,
        dependencies=[],
        priority=1,
    )


def _stage1_base_files() -> list[dict[str, str]]:
    return [
        {
            "name": "TodoItem.tsx",
            "path": "frontend/src/components/TodoItem.tsx",
            "content": (
                "import React from 'react';\n"
                "interface TodoItemProps { id: number; title: string; }\n"
                "const TodoItem = ({ id, title }: TodoItemProps) => {\n"
                "  return <div>{title}</div>;\n"
                "};\n"
                "export default TodoItem;\n"
            ),
            "type": "tsx",
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


def _stage2_response(
    *,
    include_usestate: bool = True,
    include_useeffect: bool = True,
    include_custom_hook: bool = True,
) -> str:
    files = list(_stage1_base_files())

    if include_usestate:
        hook_imports = "useState" + (", useEffect" if include_useeffect else "")
        hook_content = (
            f"import {{ {hook_imports} }} from 'react';\n\n"
            "export const useTodos = () => {\n"
            "  const [todos, setTodos] = useState<string[]>([]);\n"
            + ("  useEffect(() => { setTodos([]); }, []);\n" if include_useeffect else "")
            + "  return { todos, setTodos };\n};\n"
        )
    else:
        hook_content = (
            "// hook with no state\n"
            "export const useTodos = () => ({ todos: [] });\n"
        )

    if include_custom_hook:
        files.append(
            {
                "name": "useTodos.ts",
                "path": "frontend/src/hooks/useTodos.ts",
                "content": hook_content,
                "type": "ts",
            }
        )

    # Updated component uses hooks inline (for usestate/useeffect validation when hook not present)
    component_content = "import React"
    if include_usestate and not include_custom_hook:
        component_content += ", { useState, useEffect }" if include_useeffect else ", { useState }"
    component_content += " from 'react';\n"
    if include_usestate and not include_custom_hook:
        component_content += "const TodoList = () => {\n"
        component_content += "  const [items, setItems] = useState<string[]>([]);\n"
        if include_useeffect:
            component_content += "  useEffect(() => {}, []);\n"
        component_content += "  return <div>{items.length}</div>;\n};\n"
        component_content += "export default TodoList;\n"
    else:
        component_content += (
            "interface TodoListProps { title: string; }\n"
            "const TodoList = ({ title }: TodoListProps) => <div>{title}</div>;\n"
            "export default TodoList;\n"
        )
    files.append(
        {
            "name": "TodoList.tsx",
            "path": "frontend/src/components/TodoList.tsx",
            "content": component_content,
            "type": "tsx",
        }
    )

    payload = {
        "approach": "React hooks with custom useTodos",
        "code": "",
        "files": files,
        "dependencies": ["react", "typescript"],
        "setup_commands": ["npm install"],
        "framework": "react",
        "api_endpoints_used": [],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_frontend_stage2_success() -> None:
    llm = MockLLMProvider(response=_stage2_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage2_success",
        config=FrontendSLMConfig(stage=2, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    hook_files = [f for f in result.files if "/hooks/" in f.path]
    assert len(hook_files) >= 1


@pytest.mark.asyncio
async def test_frontend_stage2_selects_stage2_prompt() -> None:
    llm = MockLLMProvider(response=_stage2_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage2_prompt_check",
        config=FrontendSLMConfig(stage=2, retry_delays=(0.0,)),
    )

    await agent.execute_task(_frontend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "usestate" in system_prompt.lower() or "useState" in system_prompt
    assert "useeffect" in system_prompt.lower() or "useEffect" in system_prompt


@pytest.mark.asyncio
async def test_frontend_stage2_retry_when_custom_hook_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage2_response(include_custom_hook=False),
            _stage2_response(include_custom_hook=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage2_retry_hook",
        config=FrontendSLMConfig(stage=2, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage2_retry_when_usestate_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage2_response(include_usestate=False),
            _stage2_response(include_usestate=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage2_retry_usestate",
        config=FrontendSLMConfig(stage=2, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage2_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage2_response(include_custom_hook=False, include_usestate=False),
            _stage2_response(include_custom_hook=False, include_usestate=False),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage2_exhausted",
        config=FrontendSLMConfig(stage=2, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_frontend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA
