"""Unit tests for DNAManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from application.dna_manager import _EMA_ALPHA, _SPEED_REF_SEC, DNAManager
from domain.contracts import AgentDNA, TaskResult
from domain.contracts.error_codes import ErrorCode

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


def _make_storage(existing_data: dict[str, object] | None = None) -> MagicMock:
    mock = MagicMock()
    mock.load = AsyncMock(return_value=existing_data)
    mock.save = AsyncMock()
    return mock


def _make_result(
    success: bool = True,
    file_count: int = 2,
    error_code: ErrorCode | None = None,
) -> TaskResult:
    from domain.contracts import FileInfo

    files = [
        FileInfo(name=f"f{i}.py", path=f"src/f{i}.py", content="", type="python")
        for i in range(file_count)
    ]
    return TaskResult(
        task_id="task_001",
        agent_id="backend",
        approach="implement FastAPI endpoint",
        code="",
        files=files,
        success=success,
        error_code=error_code,
    )


@pytest.fixture
def manager() -> DNAManager:
    return DNAManager(storage=_make_storage())


# ------------------------------------------------------------------
# load
# ------------------------------------------------------------------


async def test_load_returns_default_dna_when_not_persisted(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    assert dna.agent_id == "backend"
    assert dna.total_tasks == 0
    assert len(dna.genes) == 10


async def test_load_restores_persisted_dna() -> None:
    stored = AgentDNA(agent_id="frontend", role="frontend", total_tasks=5, success_rate=0.8)
    storage = _make_storage(existing_data=stored.model_dump(mode="json"))
    manager = DNAManager(storage=storage)
    dna = await manager.load("frontend", "frontend")
    assert dna.total_tasks == 5
    assert dna.success_rate == 0.8


async def test_load_uses_cache_on_second_call(manager: DNAManager) -> None:
    await manager.load("backend", "backend")
    await manager.load("backend", "backend")
    # storage.load should be called only once (second hit is from cache)
    assert manager._storage.load.call_count == 1  # type: ignore[attr-defined]


# ------------------------------------------------------------------
# update — 집계 지표
# ------------------------------------------------------------------


async def test_update_increments_total_tasks(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    updated = await manager.update(dna, _make_result(success=True), duration_sec=10.0)
    assert updated.total_tasks == 1


async def test_update_rolling_success_rate(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    # 2 successes
    dna = await manager.update(dna, _make_result(success=True), duration_sec=5.0)
    dna = await manager.update(dna, _make_result(success=False), duration_sec=5.0)
    assert dna.success_rate == pytest.approx(0.5)


async def test_update_rolling_avg_duration(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    dna = await manager.update(dna, _make_result(), duration_sec=10.0)
    dna = await manager.update(dna, _make_result(), duration_sec=20.0)
    assert dna.avg_duration == pytest.approx(15.0)


# ------------------------------------------------------------------
# update — genes EMA
# ------------------------------------------------------------------


async def test_update_precision_gene_rises_on_success(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    updated = await manager.update(dna, _make_result(success=True), duration_sec=5.0)
    expected = _EMA_ALPHA * 1.0 + (1 - _EMA_ALPHA) * 0.5
    assert updated.genes["precision"] == pytest.approx(expected)


async def test_update_precision_gene_falls_on_failure(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    updated = await manager.update(dna, _make_result(success=False), duration_sec=5.0)
    expected = _EMA_ALPHA * 0.0 + (1 - _EMA_ALPHA) * 0.5
    assert updated.genes["precision"] == pytest.approx(expected)


async def test_update_code_quality_falls_when_no_files(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    updated = await manager.update(dna, _make_result(success=True, file_count=0), duration_sec=5.0)
    # code_quality sample = 0 (success but no files)
    expected = _EMA_ALPHA * 0.0 + (1 - _EMA_ALPHA) * 0.5
    assert updated.genes["code_quality"] == pytest.approx(expected)


async def test_update_debugging_skill_falls_on_error_code(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    updated = await manager.update(
        dna,
        _make_result(success=False, error_code=ErrorCode.E_LLM_TIMEOUT),
        duration_sec=5.0,
    )
    expected = _EMA_ALPHA * 0.0 + (1 - _EMA_ALPHA) * 0.5
    assert updated.genes["debugging_skill"] == pytest.approx(expected)


async def test_update_speed_gene_fast_task(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    # 10초 작업은 speed=1 - 10/120 ≈ 0.917
    speed_sample = max(0.0, 1.0 - 10.0 / _SPEED_REF_SEC)
    updated = await manager.update(dna, _make_result(), duration_sec=10.0)
    expected = _EMA_ALPHA * speed_sample + (1 - _EMA_ALPHA) * 0.5
    assert updated.genes["speed"] == pytest.approx(expected)


async def test_update_persists_to_storage(manager: DNAManager) -> None:
    dna = await manager.load("backend", "backend")
    await manager.update(dna, _make_result(), duration_sec=5.0)
    assert manager._storage.save.called  # type: ignore[attr-defined]


# ------------------------------------------------------------------
# to_system_prompt_modifier
# ------------------------------------------------------------------


def test_prompt_modifier_empty_when_all_neutral(manager: DNAManager) -> None:
    dna = AgentDNA(agent_id="x", role="backend")  # all genes = 0.5
    result = manager.to_system_prompt_modifier(dna)
    assert result == ""


def test_prompt_modifier_precision_above_threshold(manager: DNAManager) -> None:
    dna = AgentDNA(agent_id="x", role="backend", genes={"precision": 0.8})
    modifier = manager.to_system_prompt_modifier(dna)
    assert "정확성" in modifier


def test_prompt_modifier_multiple_active_genes(manager: DNAManager) -> None:
    dna = AgentDNA(
        agent_id="x",
        role="backend",
        genes={"precision": 0.9, "code_quality": 0.9},
    )
    modifier = manager.to_system_prompt_modifier(dna)
    assert "정확성" in modifier
    assert "코드 품질" in modifier


# ------------------------------------------------------------------
# to_generation_params
# ------------------------------------------------------------------


def test_generation_params_neutral_genes_returns_base_temp(manager: DNAManager) -> None:
    dna = AgentDNA(agent_id="x", role="backend")
    params = manager.to_generation_params(dna, base_temperature=0.2)
    assert params["temperature"] == pytest.approx(0.2, abs=0.01)


def test_generation_params_high_precision_lowers_temperature(manager: DNAManager) -> None:
    dna = AgentDNA(agent_id="x", role="backend", genes={"precision": 1.0})
    params = manager.to_generation_params(dna, base_temperature=0.2)
    assert params["temperature"] < 0.2


def test_generation_params_temperature_clamped_to_min(manager: DNAManager) -> None:
    dna = AgentDNA(agent_id="x", role="backend", genes={"precision": 1.0, "creativity": 0.5})
    params = manager.to_generation_params(dna, base_temperature=0.05)
    assert params["temperature"] >= 0.05
