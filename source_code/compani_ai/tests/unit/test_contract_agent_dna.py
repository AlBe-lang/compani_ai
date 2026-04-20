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
