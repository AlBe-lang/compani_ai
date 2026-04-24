from __future__ import annotations

from typing import cast

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_workspace import MockWorkSpace
from application.cto_agent import CTOAgent, CTOAgentError, CTOConfig
from domain.contracts import Strategy
from observability.error_codes import ErrorCode


def _strategy() -> Strategy:
    return Strategy(
        project_name="Todo",
        description="Todo service",
        tech_stack=["FastAPI", "React"],
        constraints=["local only"],
    )


@pytest.mark.asyncio
async def test_decompose_tasks_returns_topologically_sorted_tasks() -> None:
    llm = MockLLMProvider(
        response=(
            '{"tasks":['
            '{"id":"frontend-ui","title":"Build UI","description":"UI","agent_role":"frontend",'
            '"dependencies":["backend-api"],"priority":2},'
            '{"id":"backend-api","title":"Build API","description":"API","agent_role":"backend",'
            '"dependencies":[],"priority":1},'
            '{"id":"mlops-ci","title":"Setup CI","description":"CI","agent_role":"mlops",'
            '"dependencies":["backend-api"],"priority":3}'
            "]}"
        )
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_decompose_ok",
    )

    tasks = await agent.decompose_tasks(_strategy())

    assert [task.id for task in tasks] == ["backend-api", "frontend-ui", "mlops-ci"]
    kwargs = cast(dict[str, object], llm.calls[0]["kwargs"])
    assert kwargs["timeout_sec"] == 240
    call = llm.calls[0]
    messages = cast(list[dict[str, object]], call["messages"])
    system_prompt = cast(str, messages[0]["content"])
    assert "Few-shot example" in system_prompt
    assert "Example Output" in system_prompt
    assert 'prefix "CLARIFY:"' in system_prompt


@pytest.mark.asyncio
async def test_decompose_tasks_raises_deadlock_on_cycle() -> None:
    llm = MockLLMProvider(
        response=(
            '{"tasks":['
            '{"id":"backend-api","title":"Build API","description":"API","agent_role":"backend",'
            '"dependencies":["frontend-ui"],"priority":1},'
            '{"id":"frontend-ui","title":"Build UI","description":"UI","agent_role":"frontend",'
            '"dependencies":["backend-api"],"priority":2},'
            '{"id":"mlops-ci","title":"Setup CI","description":"CI","agent_role":"mlops",'
            '"dependencies":["backend-api"],"priority":3}'
            "]}"
        )
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(max_retries=1, retry_delays=(0.0,)),
        run_id="run_decompose_cycle",
    )

    with pytest.raises(CTOAgentError) as exc_info:
        await agent.decompose_tasks(_strategy())

    assert exc_info.value.code is ErrorCode.E_DEPS_DEADLOCK


@pytest.mark.asyncio
async def test_decompose_tasks_raises_parse_schema_on_unknown_dependency() -> None:
    llm = MockLLMProvider(
        response=(
            '{"tasks":['
            '{"id":"backend-api","title":"Build API","description":"API","agent_role":"backend",'
            '"dependencies":["missing-task"],"priority":1},'
            '{"id":"frontend-ui","title":"Build UI","description":"UI","agent_role":"frontend",'
            '"dependencies":[],"priority":2},'
            '{"id":"mlops-ci","title":"Setup CI","description":"CI","agent_role":"mlops",'
            '"dependencies":["backend-api"],"priority":3}'
            "]}"
        )
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(max_retries=1, retry_delays=(0.0,)),
        run_id="run_decompose_missing_dep",
    )

    with pytest.raises(CTOAgentError) as exc_info:
        await agent.decompose_tasks(_strategy())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA


@pytest.mark.asyncio
async def test_decompose_tasks_raises_parse_schema_on_task_count_rule() -> None:
    llm = MockLLMProvider(
        response=(
            '{"tasks":['
            '{"id":"backend-api","title":"Build API","description":"API","agent_role":"backend",'
            '"dependencies":[],"priority":1},'
            '{"id":"frontend-ui","title":"Build UI","description":"UI","agent_role":"frontend",'
            '"dependencies":["backend-api"],"priority":2}'
            "]}"
        )
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(max_retries=1, retry_delays=(0.0,)),
        run_id="run_decompose_count",
    )

    with pytest.raises(CTOAgentError) as exc_info:
        await agent.decompose_tasks(_strategy())

    assert exc_info.value.code is ErrorCode.E_PARSE_SCHEMA
