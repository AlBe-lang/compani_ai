"""Integration test for Part 7 Stage 2 — SharedWorkspace.attach_result →
EventBus 'task.completed' → PeerReviewCoordinator.review_task.

Real InProcessEventBus, real SQLiteStorage, real SharedWorkspace, real
DNAManager. LLM is mocked (stub returning APPROVE JSON) so no Ollama needed.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.event_bus import InProcessEventBus
from adapters.shared_workspace import SharedWorkspace
from adapters.sqlite_storage import SQLiteStorage
from application.dna_manager import DNAManager
from application.peer_review import PeerReviewConfig, PeerReviewCoordinator, PeerReviewMode
from application.reviewer_selector import FixedWithKGFallbackSelector
from domain.contracts import FileInfo, TaskResult, WorkItem, WorkStatus


@pytest.fixture
async def storage() -> SQLiteStorage:
    s = SQLiteStorage(":memory:")
    await s.init()
    return s


@pytest.fixture
def event_bus() -> InProcessEventBus:
    return InProcessEventBus()


@pytest.fixture
def workspace(storage: SQLiteStorage, event_bus: InProcessEventBus) -> SharedWorkspace:
    return SharedWorkspace(storage, event_bus)


def _make_llm_returning(response: str) -> MagicMock:
    mock = MagicMock()

    async def _gen(*args: Any, **kwargs: Any) -> str:
        return response

    mock.generate = AsyncMock(side_effect=_gen)
    return mock


def _make_work_item(item_id: str, task_id: str, agent_id: str) -> WorkItem:
    return WorkItem(id=item_id, task_id=task_id, agent_id=agent_id)


def _make_task_result(agent_id: str, task_id: str, approach: str) -> TaskResult:
    return TaskResult(
        task_id=task_id,
        agent_id=agent_id,
        approach=approach,
        code="",
        files=[FileInfo(name="main.py", path="main.py", content="# ok", type="python")],
        success=True,
    )


async def test_attach_result_emits_task_completed_and_coordinator_reviews(
    storage: SQLiteStorage,
    event_bus: InProcessEventBus,
    workspace: SharedWorkspace,
) -> None:
    """End-to-end: WorkItem DONE → attach_result → task.completed → review."""
    dna_manager = DNAManager(storage)
    llm = _make_llm_returning('{"decision":"APPROVE","severity":"MINOR","comments":["looks good"]}')
    PeerReviewCoordinator(
        workspace=workspace,
        storage=storage,
        event_bus=event_bus,
        llm=llm,
        reviewer_model_by_role={
            "backend": "slm",
            "frontend": "slm",
            "mlops": "mlops-slm",
            "cto": "cto",
        },
        run_id="run_integration",
        config=PeerReviewConfig(
            mode=PeerReviewMode.ALL,
            call_timeout_sec=1.0,
            max_retries=1,
            retry_interval_sec=0.0,
        ),
        selector=FixedWithKGFallbackSelector(knowledge_graph=None),
        dna_manager=dna_manager,
    )

    # Set up a WorkItem reaching DONE
    item = _make_work_item("wi_int_1", "task_int_1", "backend_agent")
    await workspace.register(item)
    await workspace.set_status("wi_int_1", WorkStatus.IN_PROGRESS)
    await workspace.set_status("wi_int_1", WorkStatus.DONE)

    # Trigger — attach_result publishes task.completed, coordinator schedules review
    result = _make_task_result("backend_agent", "task_int_1", "built a REST endpoint")
    await workspace.attach_result("wi_int_1", result)

    # Wait for the coordinator's create_task to complete
    for _ in range(30):
        await asyncio.sleep(0.02)
        # storage should contain at least one peer_review:* key if review ran
        # (we query directly)
        break
    # Run pending tasks to completion
    await asyncio.sleep(0.1)

    # Verify review was persisted
    all_data = await storage.query()
    review_records = [r for r in all_data if str(r.get("review_id", "")).startswith("review_")]
    assert len(review_records) == 1
    record = review_records[0]
    assert record["decision"] == "APPROVE"
    assert record["author_agent_id"] == "backend_agent"
    assert record["reviewer_agent_id"] == "frontend"

    # Author DNA should have been updated (precision boosted)
    author_dna = await dna_manager.load("backend_agent", "backend")
    assert author_dna.genes["precision"] > 0.5  # APPROVE sample=1.0 pushes EMA up


async def test_off_mode_does_not_persist_review(
    storage: SQLiteStorage,
    event_bus: InProcessEventBus,
    workspace: SharedWorkspace,
) -> None:
    """PeerReviewMode.OFF — coordinator must not subscribe."""
    llm = _make_llm_returning('{"decision":"APPROVE","severity":"MINOR","comments":[]}')
    PeerReviewCoordinator(
        workspace=workspace,
        storage=storage,
        event_bus=event_bus,
        llm=llm,
        reviewer_model_by_role={
            "backend": "slm",
            "frontend": "slm",
            "mlops": "mlops-slm",
            "cto": "cto",
        },
        run_id="run_off",
        config=PeerReviewConfig(mode=PeerReviewMode.OFF),
    )

    item = _make_work_item("wi_off", "task_off", "backend_agent")
    await workspace.register(item)
    await workspace.set_status("wi_off", WorkStatus.IN_PROGRESS)
    await workspace.set_status("wi_off", WorkStatus.DONE)
    result = _make_task_result("backend_agent", "task_off", "stuff")
    await workspace.attach_result("wi_off", result)

    await asyncio.sleep(0.1)

    all_data = await storage.query()
    review_records = [r for r in all_data if str(r.get("review_id", "")).startswith("review_")]
    assert review_records == []
    # LLM should never have been called
    llm.generate.assert_not_called()
