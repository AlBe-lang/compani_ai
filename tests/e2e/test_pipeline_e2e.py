"""E2E test — full pipeline with real Ollama (requires running Ollama instance).

Run with:
    pytest tests/e2e/ -m slow -v
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from adapters.event_bus import InProcessEventBus
from adapters.file_storage import FileStorage
from adapters.ollama_provider import OllamaProvider
from adapters.shared_workspace import SharedWorkspace
from adapters.sqlite_message_queue import SQLiteMessageQueue
from adapters.sqlite_storage import SQLiteStorage
from application.agent_factory import AgentFactory, SystemConfig


@pytest.fixture
async def ollama_provider() -> AsyncGenerator[OllamaProvider, None]:
    """Yield OllamaProvider if Ollama is available, otherwise skip the test."""
    async with OllamaProvider() as provider:
        healthy = await provider.health_check()
        if not healthy:
            pytest.skip("Ollama not available — start Ollama and pull required models")
        yield provider


@pytest.mark.slow
async def test_cto_strategy_with_real_ollama(ollama_provider: OllamaProvider) -> None:
    """CTO agent produces a valid Strategy object via real Ollama."""
    storage = SQLiteStorage(":memory:")
    await storage.init()
    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    queue = SQLiteMessageQueue(storage=storage)

    config = SystemConfig(run_id="e2e-strategy")
    factory = AgentFactory(config=config, llm=ollama_provider, workspace=workspace, queue=queue)
    cto = factory.create_cto()

    strategy = await cto.create_strategy("Build a simple REST API todo application")

    assert strategy.project_name
    assert strategy.description
    assert len(strategy.tech_stack) > 0

    await storage.close()


@pytest.mark.slow
async def test_full_pipeline_with_real_ollama(
    ollama_provider: OllamaProvider,
    tmp_path: Path,
) -> None:
    """Full pipeline: strategy → decompose → execute → save files via real Ollama."""
    storage = SQLiteStorage(":memory:")
    await storage.init()
    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    queue = SQLiteMessageQueue(storage=storage)

    config = SystemConfig(run_id="e2e-full", output_dir=tmp_path)
    factory = AgentFactory(config=config, llm=ollama_provider, workspace=workspace, queue=queue)

    team = {
        "backend": factory.create_backend(),
        "frontend": factory.create_frontend(),
        "mlops": factory.create_mlops(),
    }
    cto = factory.create_cto(team=team)

    strategy = await cto.create_strategy("Build a simple todo app with REST API")
    tasks = await cto.decompose_tasks(strategy)

    assert 3 <= len(tasks) <= 15

    results = await asyncio.gather(
        *[team[t.agent_role.value].execute_task(t) for t in tasks],
        return_exceptions=True,
    )

    successful = [r for r in results if not isinstance(r, BaseException) and r.success]
    assert len(successful) > 0, "At least one task must succeed"

    fs = FileStorage()
    project_dir = fs.save_result_files(
        project_name=strategy.project_name,
        results=successful,
        output_dir=tmp_path,
    )
    fs.write_readme(
        project_name=strategy.project_name,
        strategy=strategy,
        results=successful,
        output_dir=tmp_path,
    )

    assert project_dir.exists()
    readme = project_dir / "README.md"
    assert readme.exists()
    assert strategy.project_name in readme.read_text(encoding="utf-8")

    await storage.close()
