"""Agent capability profile contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# 10 DNA genes — all start at neutral 0.5 (Rule 10: EMA-based evolution)
_DEFAULT_GENES: dict[str, float] = {
    "creativity": 0.5,
    "precision": 0.5,
    "speed": 0.5,
    "collaboration": 0.5,
    "learning_rate": 0.5,
    "risk_taking": 0.5,
    "debugging_skill": 0.5,
    "innovation": 0.5,
    "code_quality": 0.5,
    "documentation": 0.5,
}


class AgentDNA(BaseModel):
    # BREAKING CHANGE: genes dict[str, float] added (Part 6 Stage 3)
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    role: str
    expertise: list[str] = Field(default_factory=list)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_duration: float = Field(default=0.0, ge=0.0)
    # BREAKING CHANGE: total_tasks added for correct rolling-average DNA evolution
    total_tasks: int = Field(default=0, ge=0)
    # BREAKING CHANGE: genes dict for 10 evolutionary traits (Part 6 Stage 3)
    genes: dict[str, float] = Field(default_factory=lambda: dict(_DEFAULT_GENES))
    # Part 7 Stage 1 — emergency meeting participation count (non-breaking, default 0).
    # Rule 10 §1: participation history is context worth preserving. Stage 2 will
    # use this along with collaboration gene EMA for weighted voting refinement.
    meeting_participation_count: int = Field(default=0, ge=0)
    # Part 7 Stage 2 — peer review participation count (non-breaking, default 0).
    # Incremented each time this agent reviews another's Task. Complements the
    # collaboration gene EMA: count tracks frequency, gene tracks quality signal.
    review_count: int = Field(default=0, ge=0)
