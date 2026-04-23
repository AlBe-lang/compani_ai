from __future__ import annotations

import json

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.mock_workspace import MockWorkSpace
from application.base_agent import SLMAgentError
from application.frontend_agent import FrontendSLMAgent, FrontendSLMConfig
from domain.contracts import AgentRole, Task
from observability.error_codes import ErrorCode


def _frontend_task(task_id: str = "frontend-stage6") -> Task:
    return Task(
        id=task_id,
        title="Frontend tests",
        description="Jest + RTL for React, widget tests for Flutter",
        agent_role=AgentRole.FRONTEND,
        dependencies=[],
        priority=1,
    )


def _stage3_react_base_files() -> list[dict[str, str]]:
    return [
        {
            "name": "TodoItem.tsx",
            "path": "frontend/src/components/TodoItem.tsx",
            "content": (
                "import React from 'react';\n"
                "interface TodoItemProps { title: string; }\n"
                "const TodoItem = ({ title }: TodoItemProps) => <div>{title}</div>;\n"
                "export default TodoItem;\n"
            ),
            "type": "tsx",
        },
        {
            "name": "useTodos.ts",
            "path": "frontend/src/hooks/useTodos.ts",
            "content": (
                "import { useState } from 'react';\n"
                "export const useTodos = () => {\n"
                "  const [todos, setTodos] = useState<string[]>([]);\n"
                "  return { todos };\n};\n"
            ),
            "type": "ts",
        },
        {
            "name": "todoApi.ts",
            "path": "frontend/src/api/todoApi.ts",
            "content": (
                "const BASE_URL = process.env.REACT_APP_API_URL ?? '';\n"
                "export const fetchTodos = async (): Promise<string[]> => {\n"
                "  try {\n"
                "    const res = await fetch(`${BASE_URL}/api/todos`);\n"
                "    return res.json();\n"
                "  } catch (err) { throw err; }\n"
                "};\n"
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


def _stage6_response(
    *,
    include_react_tests: bool = True,
    include_flutter_tests: bool = True,
) -> str:
    files = list(_stage3_react_base_files())

    if include_react_tests:
        files.append(
            {
                "name": "TodoItem.test.tsx",
                "path": "frontend/src/__tests__/TodoItem.test.tsx",
                "content": (
                    "import React from 'react';\n"
                    "import { render, screen } from '@testing-library/react';\n"
                    "import TodoItem from '../components/TodoItem';\n\n"
                    "describe('TodoItem', () => {\n"
                    "  test('renders title', () => {\n"
                    "    render(<TodoItem title='Buy milk' />);\n"
                    "    expect(screen.getByText('Buy milk')).toBeInTheDocument();\n"
                    "  });\n"
                    "});\n"
                ),
                "type": "tsx",
            }
        )
        files.append(
            {
                "name": "useTodos.test.ts",
                "path": "frontend/src/__tests__/useTodos.test.ts",
                "content": (
                    "import { renderHook } from '@testing-library/react';\n"
                    "import { useTodos } from '../hooks/useTodos';\n\n"
                    "test('useTodos returns empty todos initially', () => {\n"
                    "  const { result } = renderHook(() => useTodos());\n"
                    "  expect(result.current.todos).toEqual([]);\n"
                    "});\n"
                ),
                "type": "ts",
            }
        )

    if include_flutter_tests:
        files.append(
            {
                "name": "todo_item_test.dart",
                "path": "flutter/test/todo_item_test.dart",
                "content": (
                    "import 'package:flutter_test/flutter_test.dart';\n"
                    "import 'package:flutter/material.dart';\n\n"
                    "void main() {\n"
                    "  testWidgets('TodoItem renders title', (tester) async {\n"
                    "    await tester.pumpWidget(\n"
                    "      const MaterialApp(home: Text('Buy milk')),\n"
                    "    );\n"
                    "    expect(find.text('Buy milk'), findsOneWidget);\n"
                    "  });\n"
                    "}\n"
                ),
                "type": "dart",
            }
        )

    payload = {
        "approach": "Jest + RTL for React, flutter_test for Flutter",
        "code": "",
        "files": files,
        "dependencies": ["@testing-library/react", "jest", "flutter_test"],
        "setup_commands": ["npm test", "flutter test"],
        "framework": "react",
        "api_endpoints_used": [],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_frontend_stage6_success() -> None:
    llm = MockLLMProvider(response=_stage6_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage6_success",
        config=FrontendSLMConfig(stage=6, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    test_files = [f for f in result.files if "test" in f.name.lower()]
    assert len(test_files) >= 2


@pytest.mark.asyncio
async def test_frontend_stage6_selects_stage6_prompt() -> None:
    llm = MockLLMProvider(response=_stage6_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage6_prompt_check",
        config=FrontendSLMConfig(stage=6, retry_delays=(0.0,)),
    )

    await agent.execute_task(_frontend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "jest" in system_prompt.lower()
    assert "flutter" in system_prompt.lower()


@pytest.mark.asyncio
async def test_frontend_stage6_retry_when_react_tests_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage6_response(include_react_tests=False),
            _stage6_response(include_react_tests=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage6_retry_react_tests",
        config=FrontendSLMConfig(stage=6, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage6_retry_when_flutter_tests_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage6_response(include_flutter_tests=False),
            _stage6_response(include_flutter_tests=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage6_retry_flutter_tests",
        config=FrontendSLMConfig(stage=6, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage6_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage6_response(include_react_tests=False, include_flutter_tests=False),
            _stage6_response(include_react_tests=False, include_flutter_tests=False),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage6_exhausted",
        config=FrontendSLMConfig(stage=6, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_frontend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_frontend_stage6_regression_stage1_still_passes() -> None:
    stage1_payload = {
        "approach": "React basic",
        "code": "",
        "files": [
            {
                "name": "TodoItem.tsx",
                "path": "frontend/src/components/TodoItem.tsx",
                "content": (
                    "import React from 'react';\n"
                    "interface TodoItemProps { title: string; }\n"
                    "const TodoItem = ({ title }: TodoItemProps) => <div>{title}</div>;\n"
                    "export default TodoItem;\n"
                ),
                "type": "tsx",
            },
            {
                "name": "package.json",
                "path": "frontend/package.json",
                "content": json.dumps(
                    {"name": "todo-frontend", "dependencies": {"react": "^18.0.0"}}
                ),
                "type": "json",
            },
            {
                "name": "tsconfig.json",
                "path": "frontend/tsconfig.json",
                "content": json.dumps({"compilerOptions": {"target": "ES2020"}}),
                "type": "json",
            },
        ],
        "dependencies": ["react"],
        "setup_commands": ["npm install"],
        "framework": "react",
        "api_endpoints_used": [],
    }
    agent = FrontendSLMAgent(
        llm=MockLLMProvider(response=json.dumps(stage1_payload)),
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage6_regression_s1",
        config=FrontendSLMConfig(stage=1, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(
        Task(
            id="task-s1",
            title="Basic UI",
            description="React basic",
            agent_role=AgentRole.FRONTEND,
            dependencies=[],
            priority=1,
        )
    )

    assert result.success is True
