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


def _frontend_task(task_id: str = "frontend-stage5") -> Task:
    return Task(
        id=task_id,
        title="Build Flutter Todo UI with state and API",
        description="Flutter Riverpod state management + http API integration",
        agent_role=AgentRole.FRONTEND,
        dependencies=[],
        priority=1,
    )


def _stage4_base_files() -> list[dict[str, str]]:
    return [
        {
            "name": "main.dart",
            "path": "flutter/lib/main.dart",
            "content": (
                "import 'package:flutter/material.dart';\n"
                "void main() { runApp(const MyApp()); }\n"
                "class MyApp extends StatelessWidget {\n"
                "  const MyApp({super.key});\n"
                "  @override\n"
                "  Widget build(BuildContext context) => MaterialApp(home: Scaffold());\n"
                "}\n"
            ),
            "type": "dart",
        },
        {
            "name": "todo_item.dart",
            "path": "flutter/lib/widgets/todo_item.dart",
            "content": (
                "import 'package:flutter/material.dart';\n"
                "class TodoItem extends StatelessWidget {\n"
                "  final String title;\n"
                "  const TodoItem({super.key, required this.title});\n"
                "  @override\n"
                "  Widget build(BuildContext context) => Text(title);\n"
                "}\n"
            ),
            "type": "dart",
        },
        {
            "name": "pubspec.yaml",
            "path": "flutter/pubspec.yaml",
            "content": (
                "name: todo_flutter\n"
                "environment:\n  sdk: '>=3.0.0 <4.0.0'\n"
                "dependencies:\n  flutter:\n    sdk: flutter\n"
            ),
            "type": "yaml",
        },
    ]


def _stage5_response(
    *,
    include_riverpod: bool = True,
    include_http_call: bool = True,
    include_try_catch: bool = True,
    include_api_endpoints_used: bool = True,
) -> str:
    files = list(_stage4_base_files())

    if include_riverpod:
        provider_content = (
            "import 'package:flutter_riverpod/flutter_riverpod.dart';\n\n"
            "final todosProvider = StateNotifierProvider<TodosNotifier, List<String>>(\n"
            "  (ref) => TodosNotifier(),\n"
            ");\n\n"
            "class TodosNotifier extends StateNotifier<List<String>> {\n"
            "  TodosNotifier() : super([]);\n"
            "  void add(String todo) => state = [...state, todo];\n"
            "}\n"
        )
        files.append(
            {
                "name": "todos_provider.dart",
                "path": "flutter/lib/providers/todos_provider.dart",
                "content": provider_content,
                "type": "dart",
            }
        )

    if include_http_call:
        service_content = "import 'package:http/http.dart' as http;\n\n"
        service_content += "const _baseUrl = 'http://localhost:8000';\n\n"
        service_content += "Future<List<String>> fetchTodos() async {\n"
        if include_try_catch:
            service_content += "  try {\n"
            service_content += "    final res = await http.get(Uri.parse('$_baseUrl/api/todos'));\n"
            service_content += "    return [];\n"
            service_content += "  } catch (e) {\n"
            service_content += "    rethrow;\n"
            service_content += "  }\n"
        else:
            service_content += "  final res = await http.get(Uri.parse('$_baseUrl/api/todos'));\n"
            service_content += "  return [];\n"
        service_content += "}\n"
        files.append(
            {
                "name": "todo_service.dart",
                "path": "flutter/lib/services/todo_service.dart",
                "content": service_content,
                "type": "dart",
            }
        )

    payload = {
        "approach": "Flutter Riverpod + http package",
        "code": "",
        "files": files,
        "dependencies": ["flutter_riverpod", "http"],
        "setup_commands": ["flutter pub get", "flutter run"],
        "framework": "flutter",
        "api_endpoints_used": (
            ["GET /api/todos", "POST /api/todos"] if include_api_endpoints_used else []
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.asyncio
async def test_frontend_stage5_success() -> None:
    llm = MockLLMProvider(response=_stage5_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage5_success",
        config=FrontendSLMConfig(stage=5, retry_delays=(0.0,)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    provider_files = [f for f in result.files if "/providers/" in f.path]
    assert len(provider_files) >= 1


@pytest.mark.asyncio
async def test_frontend_stage5_selects_stage5_prompt() -> None:
    llm = MockLLMProvider(response=_stage5_response())
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage5_prompt_check",
        config=FrontendSLMConfig(stage=5, retry_delays=(0.0,)),
    )

    await agent.execute_task(_frontend_task())

    messages = llm.calls[0]["messages"]
    assert isinstance(messages, list)
    system_prompt = messages[0]["content"]
    assert isinstance(system_prompt, str)
    assert "riverpod" in system_prompt.lower()
    assert "http" in system_prompt.lower()


@pytest.mark.asyncio
async def test_frontend_stage5_retry_when_riverpod_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage5_response(include_riverpod=False),
            _stage5_response(include_riverpod=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage5_retry_riverpod",
        config=FrontendSLMConfig(stage=5, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage5_retry_when_http_call_missing_then_success() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage5_response(include_http_call=False),
            _stage5_response(include_http_call=True),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage5_retry_http",
        config=FrontendSLMConfig(stage=5, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    result = await agent.execute_task(_frontend_task())

    assert result.success is True
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_frontend_stage5_fails_after_exhausting_retries() -> None:
    llm = MockLLMProvider(
        responses=[
            _stage5_response(
                include_riverpod=False,
                include_http_call=False,
                include_api_endpoints_used=False,
            ),
            _stage5_response(
                include_riverpod=False,
                include_http_call=False,
                include_api_endpoints_used=False,
            ),
        ]
    )
    agent = FrontendSLMAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        queue=MockMessageQueue(),
        run_id="run_frontend_stage5_exhausted",
        config=FrontendSLMConfig(stage=5, max_retries=2, retry_delays=(0.0, 0.0)),
    )

    with pytest.raises(SLMAgentError) as exc_info:
        await agent.execute_task(_frontend_task())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA
