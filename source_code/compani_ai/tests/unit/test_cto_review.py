from __future__ import annotations

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_workspace import MockWorkSpace
from application.cto_agent import CTOAgent, CTOAgentError, CTOConfig
from domain.contracts import ReviewDecision, Strategy, WorkItem, WorkStatus
from observability.error_codes import ErrorCode


def _strategy_response() -> str:
    return (
        '{"project_name":"Todo","description":"Task app",'
        '"tech_stack":["FastAPI","React"],"constraints":["local only"]}'
    )


def _work_item(item_id: str, task_id: str, status: WorkStatus) -> WorkItem:
    return WorkItem(id=item_id, task_id=task_id, agent_id="backend", status=status)


@pytest.mark.asyncio
async def test_review_progress_continue_when_all_done() -> None:
    llm = MockLLMProvider(
        response='{"decision":"continue","reason":"all done","new_tasks":[{"bad":"shape"}]}',
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_review_continue",
    )

    result = await agent.review_progress(
        [
            _work_item("w1", "backend-api", WorkStatus.DONE),
            _work_item("w2", "frontend-ui", WorkStatus.DONE),
        ]
    )

    assert result.decision is ReviewDecision.CONTINUE
    assert result.new_tasks == []


@pytest.mark.asyncio
async def test_review_progress_replan_excludes_done_tasks() -> None:
    llm = MockLLMProvider(
        responses=[
            _strategy_response(),
            '{"decision":"replan","reason":"one task failed","new_tasks":[]}',
            (
                '{"tasks":['
                '{"id":"frontend-ui","title":"Build UI","description":"UI","agent_role":"frontend",'
                '"dependencies":["backend-api"],"priority":2},'
                '{"id":"backend-api","title":"Build API","description":"API","agent_role":"backend",'
                '"dependencies":[],"priority":1},'
                '{"id":"mlops-ci","title":"Setup CI","description":"CI","agent_role":"mlops",'
                '"dependencies":["backend-api"],"priority":3}'
                "]}"
            ),
        ]
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_review_replan",
    )

    strategy = await agent.create_strategy("Build a todo app")
    assert isinstance(strategy, Strategy)

    result = await agent.review_progress(
        [
            _work_item("w1", "backend-api", WorkStatus.DONE),
            _work_item("w2", "frontend-ui", WorkStatus.FAILED),
        ]
    )

    assert result.decision is ReviewDecision.REPLAN
    assert [task.id for task in result.new_tasks] == ["frontend-ui", "mlops-ci"]


@pytest.mark.asyncio
async def test_review_progress_abort_when_failed_ratio_above_half() -> None:
    llm = MockLLMProvider(
        response='{"decision":"continue","reason":"unused","new_tasks":[]}',
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_review_abort",
    )

    result = await agent.review_progress(
        [
            _work_item("w1", "backend-api", WorkStatus.FAILED),
            _work_item("w2", "frontend-ui", WorkStatus.FAILED),
            _work_item("w3", "mlops-ci", WorkStatus.DONE),
        ]
    )

    assert result.decision is ReviewDecision.ABORT
    assert result.new_tasks == []
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_review_progress_raises_system_config_when_replan_without_strategy() -> None:
    llm = MockLLMProvider(
        response='{"decision":"replan","reason":"need replanning"}',
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(max_retries=1, retry_delays=(0.0,)),
        run_id="run_review_no_strategy",
    )

    with pytest.raises(CTOAgentError) as exc_info:
        await agent.review_progress(
            [
                _work_item("w1", "backend-api", WorkStatus.FAILED),
                _work_item("w2", "frontend-ui", WorkStatus.DONE),
                _work_item("w3", "mlops-ci", WorkStatus.DONE),
            ]
        )

    assert exc_info.value.code is ErrorCode.E_SYSTEM_CONFIG
