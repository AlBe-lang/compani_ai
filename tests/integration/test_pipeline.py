"""Integration test — full pipeline with MockLLM + real SQLite (no Ollama required)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from adapters.event_bus import InProcessEventBus
from adapters.file_storage import FileStorage
from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_message_queue import MockMessageQueue
from adapters.shared_workspace import SharedWorkspace
from adapters.sqlite_storage import SQLiteStorage
from application.agent_factory import AgentFactory, SystemConfig

# ── LLM response fixtures ────────────────────────────────────────────────────

_STRATEGY = json.dumps(
    {
        "project_name": "Todo App",
        "description": "Simple task management application",
        "tech_stack": ["FastAPI", "React"],
        "constraints": ["REST API only"],
    }
)

_DECOMPOSE = json.dumps(
    {
        "tasks": [
            {
                "id": "backend_api",
                "title": "Build REST API",
                "description": "Create FastAPI endpoints for todos",
                "agent_role": "backend",
                "acceptance_criteria": ["GET /todos returns list"],
                "dependencies": [],
                "priority": 1,
            },
            {
                "id": "frontend_ui",
                "title": "Build React UI",
                "description": "Create React todo list component",
                "agent_role": "frontend",
                "acceptance_criteria": ["TodoList renders items"],
                "dependencies": [],
                "priority": 2,
            },
            {
                "id": "mlops_docker",
                "title": "Dockerize application",
                "description": "Create Dockerfile and compose",
                "agent_role": "mlops",
                "acceptance_criteria": ["docker build succeeds"],
                "dependencies": [],
                "priority": 3,
            },
        ]
    }
)

_BACKEND_RESULT = json.dumps(
    {
        "approach": "FastAPI with Pydantic models",
        "code": "from fastapi import FastAPI\napp = FastAPI()",
        "files": [
            {
                "name": "main.py",
                "path": "backend/main.py",
                "content": "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/todos')\ndef list_todos(): return []",  # noqa: E501
                "type": "python",
            }
        ],
        "dependencies": ["fastapi", "uvicorn"],
        "setup_commands": ["pip install fastapi uvicorn"],
    }
)

_FRONTEND_RESULT = json.dumps(
    {
        "framework": "react",
        "approach": "React functional components with TypeScript",
        "code": "// React todo components",
        "files": [
            {
                "name": "TodoList.tsx",
                "path": "frontend/src/components/TodoList.tsx",
                "content": (
                    "interface TodoListProps { items: string[]; }\n"
                    "const TodoList = (props: TodoListProps) => {\n"
                    "  return <ul>{props.items.map((t, i) => <li key={i}>{t}</li>)}</ul>;\n"
                    "};\nexport default TodoList;"
                ),
                "type": "tsx",
            },
            {
                "name": "package.json",
                "path": "package.json",
                "content": '{"name":"todo-app","dependencies":{"react":"^18.0.0","react-dom":"^18.0.0"}}',  # noqa: E501
                "type": "json",
            },
            {
                "name": "tsconfig.json",
                "path": "tsconfig.json",
                "content": '{"compilerOptions":{"jsx":"react-jsx","strict":true}}',
                "type": "json",
            },
        ],
        "dependencies": ["react", "react-dom"],
        "setup_commands": ["npm install"],
    }
)

_MLOPS_RESULT = json.dumps(
    {
        "env_vars_required": [],
        "ports_exposed": [],
        "approach": "Docker production build with security best practices",
        "code": "FROM python:3.11-slim",
        "files": [
            {
                "name": "Dockerfile",
                "path": "Dockerfile",
                "content": (
                    "FROM python:3.11-slim\n"
                    "WORKDIR /app\n"
                    "COPY requirements.txt .\n"
                    "RUN pip install --no-cache-dir -r requirements.txt\n"
                    "COPY . .\n"
                    "USER nobody\n"
                    'CMD ["uvicorn", "main:app", "--host", "0.0.0.0"]\n'
                ),
                "type": "dockerfile",
            },
            {
                "name": ".dockerignore",
                "path": ".dockerignore",
                "content": "__pycache__\n*.pyc\n.env\n.git\n",
                "type": "text",
            },
        ],
        "dependencies": [],
        "setup_commands": [],
    }
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def infra() -> AsyncGenerator[tuple[SharedWorkspace, MockMessageQueue, SQLiteStorage], None]:
    storage = SQLiteStorage(":memory:")
    await storage.init()
    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    queue = MockMessageQueue()
    yield workspace, queue, storage
    await storage.close()


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_cto_strategy_and_decompose(
    infra: tuple[SharedWorkspace, MockMessageQueue, SQLiteStorage],
) -> None:
    workspace, queue, _ = infra
    llm = MockLLMProvider(responses=[_STRATEGY, _DECOMPOSE])
    config = SystemConfig(run_id="integ-01")
    factory = AgentFactory(config=config, llm=llm, workspace=workspace, queue=queue)

    cto = factory.create_cto()
    strategy = await cto.create_strategy("Build a simple todo app")

    assert strategy.project_name == "Todo App"
    assert "FastAPI" in strategy.tech_stack

    tasks = await cto.decompose_tasks(strategy)
    assert len(tasks) == 3
    roles = {t.agent_role.value for t in tasks}
    assert roles == {"backend", "frontend", "mlops"}


async def test_all_tasks_execute_successfully(
    infra: tuple[SharedWorkspace, MockMessageQueue, SQLiteStorage],
    tmp_path: Path,
) -> None:
    workspace, queue, _ = infra
    llm = MockLLMProvider(
        responses=[
            _STRATEGY,
            _DECOMPOSE,
            _BACKEND_RESULT,
            _FRONTEND_RESULT,
            _MLOPS_RESULT,
        ]
    )
    config = SystemConfig(run_id="integ-02", output_dir=tmp_path)
    factory = AgentFactory(config=config, llm=llm, workspace=workspace, queue=queue)

    team = {
        "backend": factory.create_backend(),
        "frontend": factory.create_frontend(),
        "mlops": factory.create_mlops(),
    }
    cto = factory.create_cto(team=team)

    strategy = await cto.create_strategy("Build a simple todo app")
    tasks = await cto.decompose_tasks(strategy)

    results = await asyncio.gather(*[team[t.agent_role.value].execute_task(t) for t in tasks])

    assert all(r.success for r in results)
    # 1 backend file + 3 frontend files (tsx, package.json, tsconfig.json) + 2 mlops files
    assert sum(len(r.files) for r in results) == 6


async def test_file_storage_writes_output(
    infra: tuple[SharedWorkspace, MockMessageQueue, SQLiteStorage],
    tmp_path: Path,
) -> None:
    workspace, queue, _ = infra
    llm = MockLLMProvider(
        responses=[
            _STRATEGY,
            _DECOMPOSE,
            _BACKEND_RESULT,
            _FRONTEND_RESULT,
            _MLOPS_RESULT,
        ]
    )
    config = SystemConfig(run_id="integ-03", output_dir=tmp_path)
    factory = AgentFactory(config=config, llm=llm, workspace=workspace, queue=queue)

    team = {
        "backend": factory.create_backend(),
        "frontend": factory.create_frontend(),
        "mlops": factory.create_mlops(),
    }
    cto = factory.create_cto(team=team)

    strategy = await cto.create_strategy("Build a simple todo app")
    tasks = await cto.decompose_tasks(strategy)
    results = list(await asyncio.gather(*[team[t.agent_role.value].execute_task(t) for t in tasks]))

    fs = FileStorage()
    project_dir = fs.save_result_files(
        project_name=strategy.project_name,
        results=results,
        output_dir=tmp_path,
    )
    readme_path = fs.write_readme(
        project_name=strategy.project_name,
        strategy=strategy,
        results=results,
        output_dir=tmp_path,
    )

    assert project_dir.exists()
    assert (project_dir / "backend" / "main.py").exists()
    assert (project_dir / "frontend" / "src" / "components" / "TodoList.tsx").exists()
    assert (project_dir / "Dockerfile").exists()
    assert readme_path.exists()
    assert "Todo App" in readme_path.read_text(encoding="utf-8")


async def test_file_storage_generate_readme_content() -> None:
    from domain.contracts import Strategy, TaskResult
    from domain.contracts.task_result import FileInfo

    strategy = Strategy(
        project_name="Blog",
        description="A blogging platform",
        tech_stack=["FastAPI", "PostgreSQL"],
        constraints=["No auth required"],
    )
    results = [
        TaskResult(
            task_id="t1",
            agent_id="backend",
            approach="REST",
            code="...",
            files=[FileInfo(name="api.py", path="backend/api.py", content="", type="python")],
            dependencies=[],
            setup_commands=["pip install fastapi"],
            success=True,
        )
    ]

    fs = FileStorage()
    readme = fs.generate_readme("Blog", strategy, results)

    assert "# Blog" in readme
    assert "A blogging platform" in readme
    assert "FastAPI" in readme
    assert "backend/api.py" in readme
    assert "pip install fastapi" in readme
