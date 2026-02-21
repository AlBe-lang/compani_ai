"""Planning contracts emitted by CTO agent."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Strategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str
    description: str
    tech_stack: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    description: str
    agent_role: str
    dependencies: list[str] = Field(default_factory=list)
    priority: int = Field(default=3, ge=1, le=5)
