from __future__ import annotations

from domain.contracts import AgentDNA


def test_agent_dna_serialization_roundtrip() -> None:
    dna = AgentDNA(
        agent_id="backend-agent",
        role="backend",
        expertise=["fastapi", "sqlalchemy"],
        success_rate=0.92,
        avg_duration=13.5,
    )

    restored = AgentDNA.model_validate_json(dna.model_dump_json())

    assert restored.agent_id == "backend-agent"
    assert restored.expertise == ["fastapi", "sqlalchemy"]
    assert restored.success_rate == 0.92


def test_agent_dna_total_tasks_defaults_to_zero() -> None:
    dna = AgentDNA(agent_id="backend-agent", role="backend")
    assert dna.total_tasks == 0


def test_agent_dna_total_tasks_set_explicitly() -> None:
    dna = AgentDNA(agent_id="backend-agent", role="backend", total_tasks=42)
    assert dna.total_tasks == 42
    restored = AgentDNA.model_validate_json(dna.model_dump_json())
    assert restored.total_tasks == 42
