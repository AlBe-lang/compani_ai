"""Composition root — assembles the full agent team from concrete adapters."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from application.backend_agent import BackendSLMAgent, BackendSLMConfig
from application.cto_agent import CTOAgent, CTOConfig
from application.frontend_agent import FrontendSLMAgent, FrontendSLMConfig
from application.mlops_agent import MLOpsSLMAgent, MLOpsSLMConfig
from domain.ports import AgentPort, LLMProvider, MessageQueuePort, WorkSpacePort

if TYPE_CHECKING:
    from application.dna_manager import DNAManager

_DEFAULT_CTO_MODEL = "llama3.1:8b"
_DEFAULT_SLM_MODEL = "gemma4:e4b"
_DEFAULT_MLOPS_MODEL = "llama3.2:3b"


@dataclass
class SystemConfig:
    """Top-level runtime configuration for the multi-agent system."""

    cto_model: str = _DEFAULT_CTO_MODEL
    slm_model: str = _DEFAULT_SLM_MODEL
    mlops_model: str = _DEFAULT_MLOPS_MODEL
    ollama_base_url: str = "http://localhost:11434"
    output_dir: Path = field(default_factory=lambda: Path("outputs"))
    db_path: str = "data/compani.db"
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    # Stage Gate 통과 기준 (Part 6 Stage 3)
    gate_max_failure_rate: float = 0.3
    gate_max_avg_duration: float = 120.0


class AgentFactory:
    """Create concrete agent instances wired with the given infrastructure adapters."""

    def __init__(
        self,
        config: SystemConfig,
        llm: LLMProvider,
        workspace: WorkSpacePort,
        queue: MessageQueuePort,
        dna_manager: "DNAManager | None" = None,
    ) -> None:
        self._config = config
        self._llm = llm
        self._workspace = workspace
        self._queue = queue
        self._dna_manager = dna_manager

    def create_cto(self, team: Mapping[str, AgentPort] | None = None) -> CTOAgent:
        return CTOAgent(
            llm=self._llm,
            workspace=self._workspace,
            team=dict(team) if team else {},
            config=CTOConfig(model=self._config.cto_model),
            run_id=self._config.run_id,
        )

    def create_backend(self) -> BackendSLMAgent:
        return BackendSLMAgent(
            llm=self._llm,
            workspace=self._workspace,
            queue=self._queue,
            run_id=self._config.run_id,
            config=BackendSLMConfig(model=self._config.slm_model),
            dna_manager=self._dna_manager,
        )

    def create_frontend(self) -> FrontendSLMAgent:
        return FrontendSLMAgent(
            llm=self._llm,
            workspace=self._workspace,
            queue=self._queue,
            run_id=self._config.run_id,
            config=FrontendSLMConfig(model=self._config.slm_model),
            dna_manager=self._dna_manager,
        )

    def create_mlops(self) -> MLOpsSLMAgent:
        return MLOpsSLMAgent(
            llm=self._llm,
            workspace=self._workspace,
            queue=self._queue,
            run_id=self._config.run_id,
            config=MLOpsSLMConfig(model=self._config.mlops_model),
            dna_manager=self._dna_manager,
        )

    def create_team(self) -> dict[str, AgentPort]:
        return {
            "backend": self.create_backend(),
            "frontend": self.create_frontend(),
            "mlops": self.create_mlops(),
        }
