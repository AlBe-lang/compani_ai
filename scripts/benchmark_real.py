"""Real-Ollama pipeline benchmark — Part 8 Stage 1 (Q1 real half).

ROLE: **absolute latency measurement** reflecting real user experience. Run
at Stage boundaries to compare before/after numbers. Do NOT compare with
mock benchmark outputs (``make bench-mock``) — the modes measure different
things (mock = regression guard, real = absolute wall-clock).

Usage:
    python scripts/benchmark_real.py [--iterations N] [--request "..."] [--output PATH]

Requires a running Ollama server with the configured models loaded. Report
is written to ``benchmarks/reports/real/<timestamp>.json`` by default.

First 3 lines of the JSON include the mode banner so reviewers can't
accidentally compare to mock reports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is importable when running as script
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from main import orchestrate_project  # noqa: E402

from adapters.event_bus import InProcessEventBus  # noqa: E402
from adapters.ollama_provider import OllamaProvider  # noqa: E402
from adapters.qdrant_storage import QdrantStorage  # noqa: E402
from adapters.redis_cache import RedisCache  # noqa: E402
from adapters.shared_workspace import SharedWorkspace  # noqa: E402
from adapters.sqlite_message_queue import SQLiteMessageQueue  # noqa: E402
from adapters.sqlite_storage import SQLiteStorage  # noqa: E402
from application.agent_factory import SystemConfig  # noqa: E402
from application.dna_manager import DNAManager  # noqa: E402
from application.knowledge_graph import KnowledgeGraph  # noqa: E402

_DEFAULT_REQUEST = "Create a simple Todo list REST API with CRUD endpoints"
_DEFAULT_ITERATIONS = 3
_DEFAULT_OUTPUT_DIR = _ROOT / "benchmarks" / "reports" / "real"


async def _single_run(request: str) -> dict[str, float | int | str]:
    """Run one orchestrate_project call and capture wall-clock + task counts."""
    config = SystemConfig(db_path=":memory:")

    storage = SQLiteStorage(":memory:")
    await storage.init()

    qdrant = QdrantStorage(
        path=":memory:",
        embedding_model=config.embedding_preset.value,
    )
    await qdrant.init()

    cache = RedisCache(redis_url="redis://localhost:6379", fallback=storage)
    await cache.connect()

    knowledge_graph = KnowledgeGraph(qdrant=qdrant, storage=storage)
    dna_manager = DNAManager(storage=storage)

    bus = InProcessEventBus()
    workspace = SharedWorkspace(storage=storage, event_bus=bus)
    queue = SQLiteMessageQueue(storage=storage, knowledge_graph=knowledge_graph)

    start = time.perf_counter()
    async with OllamaProvider(base_url=config.ollama_base_url) as llm:
        healthy = await llm.health_check()
        if not healthy:
            raise RuntimeError(f"Ollama unreachable at {config.ollama_base_url}")

        result = await orchestrate_project(
            request=request,
            config=config,
            storage=storage,
            workspace=workspace,
            queue=queue,
            llm=llm,
            knowledge_graph=knowledge_graph,
            dna_manager=dna_manager,
            stage_gate=None,
        )
    elapsed = time.perf_counter() - start

    await storage.close()
    await qdrant.close()
    await cache.close()

    return {
        "duration_sec": round(elapsed, 2),
        "project_name": result.project_name,
        "total_tasks": result.total_tasks,
        "completed_tasks": result.completed_tasks,
        "failed_tasks": result.failed_tasks,
        "files_generated": len(result.files_generated),
    }


async def run_benchmark(request: str, iterations: int, output_path: Path) -> dict[str, object]:
    """Run N iterations and aggregate results. Writes JSON report."""
    print(f"[bench real] Running {iterations} iterations of: {request[:60]!r}")
    print(f"[bench real] MODE: real (absolute wall-clock, Ollama required)")
    print(f"[bench real] NOTE: Do not compare with `make bench-mock` outputs.\n")

    runs: list[dict[str, float | int | str]] = []
    for i in range(1, iterations + 1):
        print(f"  Iteration {i}/{iterations} ...", end=" ", flush=True)
        try:
            result = await _single_run(request)
            runs.append(result)
            print(
                f"{result['duration_sec']}s "
                f"({result['completed_tasks']}/{result['total_tasks']} tasks)"
            )
        except Exception as exc:
            print(f"FAILED: {exc}")
            runs.append({"error": str(exc)})

    durations = [float(r["duration_sec"]) for r in runs if "duration_sec" in r]
    report: dict[str, object] = {
        "mode": "real",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request": request,
        "iterations": iterations,
        "runs": runs,
        "summary": {
            "mean_sec": round(statistics.mean(durations), 2) if durations else None,
            "median_sec": round(statistics.median(durations), 2) if durations else None,
            "min_sec": round(min(durations), 2) if durations else None,
            "max_sec": round(max(durations), 2) if durations else None,
            "failures": len(runs) - len(durations),
        },
        "warning": (
            "These numbers are wall-clock real Ollama latency. Do NOT compare "
            "with mock benchmark reports in benchmarks/reports/mock/."
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[bench real] Report written to {output_path}")
    summary = report["summary"]
    assert isinstance(summary, dict)
    print(
        f"[bench real] Summary: mean={summary['mean_sec']}s "
        f"median={summary['median_sec']}s "
        f"(failures {summary['failures']}/{iterations})"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Real Ollama benchmark")
    parser.add_argument("--iterations", type=int, default=_DEFAULT_ITERATIONS)
    parser.add_argument("--request", default=_DEFAULT_REQUEST)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path (default: benchmarks/reports/real/<timestamp>.json)",
    )
    args = parser.parse_args()

    output_path = args.output or (
        _DEFAULT_OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    asyncio.run(run_benchmark(args.request, args.iterations, output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
