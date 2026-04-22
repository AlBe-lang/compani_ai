from __future__ import annotations

import json
from typing import cast

import pytest

from adapters.mock_llm_provider import MockLLMProvider
from adapters.mock_workspace import MockWorkSpace
from application.cto_agent import CTOAgent, CTOAgentError, CTOConfig
from observability.error_codes import ErrorCode
from observability.logger import configure_logging


@pytest.mark.asyncio
async def test_create_strategy_returns_strategy_from_valid_json() -> None:
    llm = MockLLMProvider(
        response=(
            '```json\n'
            '{"project_name":"Todo","description":"Task app","tech_stack":["FastAPI"],'
            '"constraints":["local only"]}\n'
            "```"
        )
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_test",
    )

    strategy = await agent.create_strategy("Build a todo app")

    assert strategy.project_name == "Todo"
    assert strategy.tech_stack == ["FastAPI"]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_create_strategy_retries_after_parse_error() -> None:
    llm = MockLLMProvider(
        responses=[
            "this is not json",
            (
                '```json\n'
                '{"project_name":"Blog","description":"Blog app","tech_stack":["React"],'
                '"constraints":["single machine"]}\n'
                "```"
            ),
        ]
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_retry",
    )

    strategy = await agent.create_strategy("Build a blog app")

    assert strategy.project_name == "Blog"
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_create_strategy_raises_after_three_parse_failures() -> None:
    llm = MockLLMProvider(responses=["bad", "still bad", "not json"])
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_fail",
    )

    with pytest.raises(CTOAgentError) as exc_info:
        await agent.create_strategy("Failure scenario")

    assert exc_info.value.code is ErrorCode.E_PARSE_JSON
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_create_strategy_recovers_from_partial_json() -> None:
    llm = MockLLMProvider(
        response=(
            '{"project_name":"Todo","description":"Task app","tech_stack":["FastAPI"],'
            '"constraints":["local only"]'
        )
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_partial_json",
    )

    strategy = await agent.create_strategy("Build a todo app")

    assert strategy.project_name == "Todo"
    assert strategy.constraints == ["local only"]
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_create_strategy_system_prompt_contains_few_shot_example() -> None:
    llm = MockLLMProvider(
        response='{"project_name":"Todo","description":"Task app","tech_stack":[],"constraints":[]}'
    )
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id="run_prompt_check",
    )

    await agent.create_strategy("Build a todo app")

    call = llm.calls[0]
    messages = cast(list[dict[str, object]], call["messages"])
    system_prompt = cast(str, messages[0]["content"])
    assert "Few-shot example" in system_prompt
    assert "Example Output" in system_prompt
    assert 'prefix "clarify:"' in system_prompt


@pytest.mark.asyncio
async def test_create_strategy_logs_include_run_id_and_agent_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(force=True)
    llm = MockLLMProvider(
        response='{"project_name":"Todo","description":"Task app","tech_stack":[],"constraints":[]}'
    )
    run_id = "run_logging_test"
    agent = CTOAgent(
        llm=llm,
        workspace=MockWorkSpace(),
        team={},
        config=CTOConfig(retry_delays=(0.0, 0.0, 0.0)),
        run_id=run_id,
    )

    await agent.create_strategy("Todo app")

    lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    payloads = [json.loads(line) for line in lines]

    assert any(payload.get("run_id") == run_id for payload in payloads)
    assert any(payload.get("agent_id") == "cto" for payload in payloads)
    assert any(payload.get("event") == "cto.strategy.done" and payload.get("task_count") == 0 for payload in payloads)
    assert any(
        payload.get("event") == "cto.strategy.done"
        and isinstance(payload.get("response_chars"), int)
        and int(payload["response_chars"]) > 0
        for payload in payloads
    )
