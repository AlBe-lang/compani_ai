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


def _frontend_task(task_id: str = "frontend-stage4") -> Task:
    return Task(
        id=task_id,
        title="Build Flutter Todo UI",
        description="Flutter basic widgets: StatelessWidget, StatefulWidget, const constructors",
        agent_role=AgentRole.FRONTEND,
        dependencies=[],
        priority=1,
    )


def _stage4_response(
    *,
    include_dart: bool = True,
    include_widget_file: bool = True,
    include_stateless: bool = True,
    include_const_constructor: bool = True,
    include_pubspec: bool = True,
    include_main_dart: bool = True,
) -> str:
    files: list[dict[str, str]] = []

    if include_main_dart:
        if include_stateless:
            main_content = (
                "import 'package:flutter/material.dart';\n\n"
                "void main() {\n"
                "  runApp(const MyApp());\n"
                "}\n\n"
                "class MyApp extends StatelessWidget {\n"
                "  const MyApp({super.key});\n"
                "  @override\n"
                "  Widget build(BuildContext context) {\n"
                "    return MaterialApp(home: Scaffold(body: Text('Hello')));\n"
                "  }\n"
                "}\n"
            )
        else:
            # StatefulWidget-only main to avoid false positive in stateless check
            main_content = (
                "import 'package:flutter/material.dart';\n\n"
                "void main() { runApp(MyApp()); }\n\n"
                "class MyApp extends StatefulWidget {\n"
                "  @override\n"
                "  State<MyApp> createState() => _MyAppState();\n"
                "}\n"
                "class _MyAppState extends State<MyApp> {\n"
                "  @override\n"
                "  Widget build(BuildContext context) => MaterialApp(home: Scaffold());\n"
                "}\n"
            )
        files.append(
            {
                "name": "main.dart",
                "path": "flutter/lib/main.dart",
                "content": main_content,
                "type": "dart",
            }
        )

    if include_widget_file:
        widget_content = "import 'package:flutter/material.dart';\n\n"
        if include_stateless:
            widget_content += "class TodoItem extends StatelessWidget {\n"
            widget_content += "  final String title;\n"
            if include_const_constructor:
                widget_content += "  const TodoItem({super.key, required this.title});\n"
            else:
                widget_content += "  TodoItem({super.key, required this.title});\n"
            widget_content += "  @override\n"
            widget_content += "  Widget build(BuildContext context) {\n"
            widget_content += "    return Text(title);\n"
            widget_content += "  }\n}\n"
        else:
            widget_content += "class TodoItem extends StatefulWidget {\n"
            widget_content += "  final String title;\n"
            widget_content += "  const TodoItem({super.key, required this.title});\n"
            widget_content += "  @override\n"
            widget_content += "  State<TodoItem> createState() => _TodoItemState();\n}\n"
            widget_content += "class _TodoItemState extends State<TodoItem> {\n"
            widget_content += "  @override\n"
            widget_content += "  Widget build(BuildContext context) => Text(widget.title);\n}\n"
        files.append(
            {
                "name": "todo_item.dart",
                "path": "flutter/lib/widgets/todo_item.dart",
                "content": widget_content,
                "type": "dart",
            }
        )
    elif include_dart:
        files.append(
            {
                "name": "placeholder.dart",
                "path": "flutter/lib/placeholder.dart",
                "content": "// placeholder dart file\n",
                "type": "dart",
            }
        )

    if include_pubspec:
        files.append(
            {
                "name": "pubspec.yaml",
                "path": "flutter/pubspec.yaml",
                "content": (
                    "name: todo_flutter\n"
                    "environment:\n"
                    "  sdk: '>=3.0.0 <4.0.0'\n"
                    "  flutter: '>=3.0.0'\n"
                    "dependencies:\n"
                    "  flutter:\n"
                    "    sdk: flutter\n"
                ),
                "type": "yaml",
            }
        )

    payload = {
        "approach": "Flutter StatelessWidget with const constructors",
        "code": "",
        "files": files,
        "dependencies": ["flutter"],
        "setup_commands": ["flutter pub get", "flutter run"],
        "framework": "flutter",
        "api_endpoints_used": [],
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_frontend_stage4_success() -> None:
    llm = MockLLMProvider(response=_stage4_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage4_success",
        config=FrontendSLMConfig(stage=4, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    dart_files = [f for f in result.files if f.name.endswith(".dart")]
    assert len(dart_files) >= 1


@pytest.mark.asyncio
async def test_frontend_stage4_selects_stage4_prompt() -> None:
    llm = MockLLMProvider(response=_stage4_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage4_prompt_check",
        config=FrontendSLMConfig(stage=4, retry_delays=(0.0,)),
    )

    await agent.execute_task(_frontend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "flutter" in system_prompt.lower()
    assert "statelesswidget" in system_prompt.lower() or "stateless" in system_prompt.lower()


@pytest.mark.asyncio
async def test_frontend_stage4_retry_when_stateless_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_stateless=False),
            _stage4_response(include_stateless=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage4_retry_stateless",
        config=FrontendSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage4_retry_when_pubspec_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_pubspec=False),
            _stage4_response(include_pubspec=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage4_retry_pubspec",
        config=FrontendSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage4_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage4_response(include_dart=False, include_widget_file=False, include_main_dart=False),
            _stage4_response(include_dart=False, include_widget_file=False, include_main_dart=False),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage4_exhausted",
        config=FrontendSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_frontend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_frontend_stage4_rejects_react_framework() -> None:
    """Stage 4 must declare framework='flutter', not 'react'."""
    react_payload = {
        "approach": "React fallback",
        "code": "",
        "files": [
            {
                "name": "TodoItem.tsx",
                "path": "frontend/src/components/TodoItem.tsx",
                "content": "interface Props { title: string; }\nconst TodoItem = ({ title }: Props) => <div>{title}</div>;",
                "type": "tsx",
            }
        ],
        "dependencies": [],
        "setup_commands": [],
        "framework": "react",
        "api_endpoints_used": [],
    }
    llm = MockLLMProvider(
        responses=[
            json.dumps(react_payload),
            _stage4_response(),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage4_wrong_framework",
        config=FrontendSLMConfig(stage=4, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2
