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


def test_agent_dna_genes_default_to_neutral() -> None:
    dna = AgentDNA(agent_id="backend-agent", role="backend")
    assert len(dna.genes) == 10
    for gene, value in dna.genes.items():
        assert value == 0.5, f"gene {gene} expected 0.5, got {value}"


def test_agent_dna_genes_are_independent_across_instances() -> None:
    dna_a = AgentDNA(agent_id="a", role="backend")
    dna_b = AgentDNA(agent_id="b", role="frontend")
    dna_a.genes["precision"] = 0.9
    assert dna_b.genes["precision"] == 0.5


def test_agent_dna_genes_roundtrip() -> None:
    dna = AgentDNA(agent_id="mlops", role="mlops", genes={"precision": 0.8, "speed": 0.3})
    restored = AgentDNA.model_validate_json(dna.model_dump_json())
    assert restored.genes["precision"] == 0.8
    assert restored.genes["speed"] == 0.3
