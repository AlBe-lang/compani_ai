"""Task result contract produced by execution agents."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    content: str
    type: str


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    approach: str
    code: str
    files: list[FileInfo] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    setup_commands: list[str] = Field(default_factory=list)
    success: bool = True
    error_code: str | None = None
