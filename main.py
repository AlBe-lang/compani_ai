"""Application entry point — runs the multi-agent project generation pipeline."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from adapters.event_bus import InProcessEventBus
from adapters.file_storage import FileStorage
from adapters.ollama_provider import OllamaProvider
from adapters.qdrant_storage import QdrantStorage
from adapters.redis_cache import RedisCache
from adapters.shared_workspace import SharedWorkspace
from adapters.sqlite_message_queue import SQLiteMessageQueue
from adapters.sqlite_storage import SQLiteStorage
from application.agent_factory import AgentFactory, SystemConfig
from application.dna_manager import DNAManager
from application.knowledge_graph import KnowledgeGraph
from application.stage_gate import GateConfig, GateVerdict, StageGateMeeting
from domain.contracts import AgentRole, Strategy, Task, TaskResult
from domain.ports import AgentPort
from observability.logger import get_logger


@dataclass
class ProjectResult:
    """Summary of a completed project generation run."""

    project_name: str
    success: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    output_dir: Path
    files_generated: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


_ROLE_KEY: dict[AgentRole, str] = {
    AgentRole.BACKEND: "backend",
    AgentRole.FRONTEND: "frontend",
    AgentRole.MLOPS: "mlops",
}


async def orchestrate_project(
    request: str,
    config: SystemConfig,
    storage: SQLiteStorage,
    workspace: SharedWorkspace,
    queue: SQLiteMessageQueue,
    llm: OllamaProvider,
    knowledge_graph: KnowledgeGraph | None = None,
    dna_manager: DNAManager | None = None,
    stage_gate: StageGateMeeting | None = None,
) -> ProjectResult:
    """Run the full project generation pipeline and return a summary."""
    logger = get_logger(component="orchestrator", run_id=config.run_id)
    t_start = time.monotonic()

    factory = AgentFactory(
        config=config,
        llm=llm,
        workspace=workspace,
        queue=queue,
        dna_manager=dna_manager,
    )
    team: dict[str, AgentPort] = factory.create_team()
    cto = factory.create_cto(team=team)

    logger.info("orchestrator.strategy.start", request_length=len(request))
    strategy: Strategy = await cto.create_strategy(request)
    logger.info("orchestrator.strategy.done", project_name=strategy.project_name)

    tasks: list[Task] = await cto.decompose_tasks(strategy)
    logger.info("orchestrator.decompose.done", task_count=len(tasks))

    async def _run_task(task: Task) -> TaskResult:
        agent_key = _ROLE_KEY[task.agent_role]
        return await team[agent_key].execute_task(task)

    cto_qa_task = asyncio.create_task(cto.handle_questions(queue))
    try:
        results: list[TaskResult | BaseException] = list(
            await asyncio.gather(*[_run_task(t) for t in tasks], return_exceptions=True)
        )
    finally:
        cto_qa_task.cancel()
        try:
            await cto_qa_task
        except asyncio.CancelledError:
            pass

    successful: list[TaskResult] = [r for r in results if isinstance(r, TaskResult) and r.success]
    failed_count = len(tasks) - len(successful)

    if knowledge_graph is not None:
        for result in successful:
            await knowledge_graph.store_task_result(result, run_id=config.run_id)

    # Stage Gate 평가 — 실패율 초과 시 CTO 위임
    if stage_gate is not None:
        all_work_items = [
            item
            for task in tasks
            if (item := await workspace.get_by_task_id(task.id)) is not None
        ]
        gate_result = await stage_gate.evaluate(all_work_items)
        logger.info(
            "orchestrator.gate",
            verdict=gate_result.verdict.value,
            failure_rate=round(gate_result.failure_rate, 3),
            reason=gate_result.reason,
        )
        if gate_result.verdict is GateVerdict.ABORT:
            logger.error("orchestrator.gate.abort", reason=gate_result.reason)

    file_storage = FileStorage()
    project_dir = file_storage.save_result_files(
        project_name=strategy.project_name,
        results=successful,
        output_dir=config.output_dir,
    )
    file_storage.write_readme(
        project_name=strategy.project_name,
        strategy=strategy,
        results=successful,
        output_dir=config.output_dir,
    )

    files_generated = [fi.path for r in successful for fi in r.files]
    duration = time.monotonic() - t_start

    logger.info(
        "orchestrator.done",
        project_name=strategy.project_name,
        completed=len(successful),
        failed=failed_count,
        files=len(files_generated),
        duration_s=round(duration, 1),
    )

    return ProjectResult(
        project_name=strategy.project_name,
        success=failed_count == 0,
        total_tasks=len(tasks),
        completed_tasks=len(successful),
        failed_tasks=failed_count,
        output_dir=project_dir,
        files_generated=files_generated,
        duration_seconds=duration,
    )


async def app_main(request: str | None = None) -> None:
    """Bootstrap infrastructure and run the orchestration pipeline."""
    import argparse

    if request is None:
        parser = argparse.ArgumentParser(description="CompaniAI multi-agent code generator")
        parser.add_argument("request", nargs="?", default=None, help="Project description")
        args = parser.parse_args()
        request = args.request

    if not request:
        print("Usage: python main.py \"<project description>\"")
        return

    config = SystemConfig()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)

    storage = SQLiteStorage(config.db_path)
    await storage.init()

    qdrant = QdrantStorage(path="data/qdrant")
    await qdrant.init()

    cache = RedisCache(redis_url="redis://localhost:6379", fallback=storage)
    await cache.connect()

    knowledge_graph = KnowledgeGraph(qdrant=qdrant)
    dna_manager = DNAManager(storage=storage)

    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    queue = SQLiteMessageQueue(storage=storage, knowledge_graph=knowledge_graph)

    async with OllamaProvider(base_url=config.ollama_base_url) as llm:
        healthy = await llm.health_check()
        if not healthy:
            print(f"Ollama not available at {config.ollama_base_url}. Start Ollama and retry.")
            await storage.close()
            await qdrant.close()
            await cache.close()
            return

        gate_config = GateConfig(
            max_failure_rate=config.gate_max_failure_rate,
            max_avg_duration=config.gate_max_avg_duration,
        )
        # StageGateMeeting은 CTO 인스턴스가 필요하므로 factory를 통해 생성
        _gate_factory = AgentFactory(config=config, llm=llm, workspace=workspace, queue=queue)
        _gate_cto = _gate_factory.create_cto()
        stage_gate = StageGateMeeting(
            cto=_gate_cto,
            event_bus=bus,
            storage=storage,
            run_id=config.run_id,
            config=gate_config,
        )

        result = await orchestrate_project(
            request=request,
            config=config,
            storage=storage,
            workspace=workspace,
            queue=queue,
            llm=llm,
            knowledge_graph=knowledge_graph,
            dna_manager=dna_manager,
            stage_gate=stage_gate,
        )

    await storage.close()
    await qdrant.close()
    await cache.close()

    print(f"\nProject: {result.project_name}")
    print(f"Status:  {'SUCCESS' if result.success else 'PARTIAL'}")
    print(f"Tasks:   {result.completed_tasks}/{result.total_tasks} completed")
    print(f"Files:   {len(result.files_generated)} generated → {result.output_dir}")
    print(f"Time:    {result.duration_seconds:.1f}s")


def main() -> int:
    asyncio.run(app_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
