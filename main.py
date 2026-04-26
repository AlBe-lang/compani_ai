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
from application.agent_factory import (
    AgentFactory,
    LLMProviderKind,
    SystemConfig,
    create_llm_provider,
)
from application.dna_manager import DNAManager
from application.knowledge_graph import KnowledgeGraph
from application.stage_gate import GateConfig, GateVerdict, StageGateMeeting
from domain.contracts import AgentRole, Strategy, Task, TaskResult
from domain.ports import AgentPort, LLMProvider
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
    llm: LLMProvider,
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
    # Part 8 Stage 1: per-role + total LLM concurrency limiter.
    limiter = factory.create_concurrency_limiter()
    logger.info(
        "orchestrator.concurrency",
        **limiter.config,
    )

    logger.info("orchestrator.strategy.start", request_length=len(request))
    strategy: Strategy = await cto.create_strategy(request)
    logger.info("orchestrator.strategy.done", project_name=strategy.project_name)

    tasks: list[Task] = await cto.decompose_tasks(strategy)
    logger.info("orchestrator.decompose.done", task_count=len(tasks))

    async def _run_task(task: Task) -> TaskResult:
        agent_key = _ROLE_KEY[task.agent_role]
        # Part 8 Stage 1: acquire role + total semaphore before LLM call
        # to respect Mac Mini 16GB memory budget (I-04, §7.3).
        async with limiter.limit(agent_key):
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
            item for task in tasks if (item := await workspace.get_by_task_id(task.id)) is not None
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


async def app_main(request: str | None = None, dashboard_only: bool = False) -> None:
    """Bootstrap infrastructure and run the orchestration pipeline.

    Part 8 Stage 2: ``--dashboard`` flag starts the CEO Dashboard HTTP/WS
    server WITHOUT invoking the generation pipeline, so operators can observe
    a running project (or a fresh one) without kicking off a new run.
    """
    import argparse

    if request is None and not dashboard_only:
        parser = argparse.ArgumentParser(description="CompaniAI multi-agent code generator")
        parser.add_argument("request", nargs="?", default=None, help="Project description")
        parser.add_argument(
            "--dashboard",
            action="store_true",
            help="Run the CEO Dashboard HTTP/WS server only (no pipeline).",
        )
        args = parser.parse_args()
        request = args.request
        dashboard_only = args.dashboard

    if dashboard_only:
        await _run_dashboard_server()
        return

    if not request:
        print('Usage: python main.py "<project description>"   OR   --dashboard')
        return

    config = SystemConfig()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)

    storage = SQLiteStorage(config.db_path)
    await storage.init()

    # Part 8 Stage 1: embedding model driven by SystemConfig (EmbeddingPreset)
    qdrant = QdrantStorage(
        path="data/qdrant",
        embedding_model=config.embedding_preset.value,
        allow_recreate=config.allow_embedding_collection_recreate,
    )
    await qdrant.init()

    cache = RedisCache(redis_url="redis://localhost:6379", fallback=storage)
    await cache.connect()

    knowledge_graph = KnowledgeGraph(qdrant=qdrant, storage=storage)
    await knowledge_graph.load_expertise()
    dna_manager = DNAManager(storage=storage)

    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    queue = SQLiteMessageQueue(storage=storage, knowledge_graph=knowledge_graph)

    async with create_llm_provider(config) as llm:
        # Local Ollama: verify service availability up-front so the user gets a
        # clear error before decomposition begins. Cloud providers raise on
        # first call instead (no cheap /api/tags equivalent across vendors).
        if config.llm_provider is LLMProviderKind.OLLAMA and isinstance(llm, OllamaProvider):
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


async def _run_dashboard_server() -> None:
    """Launch the CEO Dashboard HTTP/WS server (Part 8 Stage 2).

    Creates a minimal infrastructure stack so the dashboard has live
    objects to observe, even when no pipeline is running. When the user
    wants dashboard + pipeline simultaneously they should run two terminals
    (``python main.py --dashboard`` + ``python main.py "<request>"``) — a
    concurrent-pipeline-and-dashboard single command is deferred to Stage 3.
    """
    import uvicorn

    from interfaces.dashboard_api import DashboardDeps, create_app
    from interfaces.dashboard_api.runner import RunManager
    from observability.metrics import MetricsCollector

    config = SystemConfig()
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)

    storage = SQLiteStorage(config.db_path)
    await storage.init()

    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    dna_manager = DNAManager(storage=storage)
    metrics = MetricsCollector()
    factory = AgentFactory(
        config=config,
        llm=None,  # type: ignore[arg-type]
        workspace=workspace,
        queue=None,  # type: ignore[arg-type]
    )
    limiter = factory.create_concurrency_limiter()

    import uuid as _uuid

    token = config.dashboard_token or _uuid.uuid4().hex
    # v1.1 demo entry — RunManager spawns ``main.py "<request>"`` as a child
    # when the dashboard receives POST /api/run. Subprocess approach is
    # interim until R-11B (single-process SharedWorkspace) lands in v2.0.
    run_manager = RunManager(project_root=Path.cwd())
    deps = DashboardDeps(
        config=config,
        auth_token=token,
        workspace=workspace,
        dna_manager=dna_manager,
        metrics=metrics,
        event_bus=bus,
        limiter=limiter,
        run_manager=run_manager,
        poll_interval_sec=config.dashboard_poll_interval_sec,
    )
    # Keep config in sync with the actual token used so /api/config shows the
    # real (masked) value and subsequent mutations don't reset it.
    config.dashboard_token = token

    app = create_app(deps, print_banner=True)

    uvicorn_config = uvicorn.Config(
        app,
        host=config.dashboard_host,
        port=config.dashboard_port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    try:
        await server.serve()
    finally:
        await storage.close()


def main() -> int:
    asyncio.run(app_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
