"""Agent capability profile contract."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentDNA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    role: str
    expertise: list[str] = Field(default_factory=list)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_duration: float = Field(default=0.0, ge=0.0)
