"""Composition root — assembles the full agent team from concrete adapters."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from application.backend_agent import BackendSLMAgent, BackendSLMConfig
from application.cto_agent import CTOAgent, CTOConfig
from application.emergency_meeting import EmergencyMeeting, EmergencyMeetingConfig
from application.frontend_agent import FrontendSLMAgent, FrontendSLMConfig
from application.mlops_agent import MLOpsSLMAgent, MLOpsSLMConfig
from application.peer_review import PeerReviewConfig, PeerReviewCoordinator, PeerReviewMode
from domain.ports import (
    AgentPort,
    EventBusPort,
    KnowledgeGraphPort,
    LLMProvider,
    MessageQueuePort,
    StoragePort,
    WorkSpacePort,
)

if TYPE_CHECKING:
    from adapters.qdrant_storage import QdrantStorage
    from application.dna_manager import DNAManager
    from observability.metrics import MetricsCollector

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
    # Part 7 Stage 1 — EmergencyMeeting 설정
    meeting_response_timeout_sec: float = 30.0
    meeting_cto_max_retries: int = 3
    meeting_cto_retry_interval_sec: float = 2.0
    # Part 7 Stage 2 — PeerReview 설정. 기본 OFF. VRAM이 아닌 "감내 가능한 추가
    # 실행 시간"을 기준으로 사용자가 모드 선택 (CEO 대시보드(Part 8)에서 runtime
    # 토글 예정). CRITICAL은 의존성 보유 또는 duration ≥ 임계값 Task만 리뷰.
    peer_review_mode: PeerReviewMode = PeerReviewMode.OFF
    peer_review_critical_duration_sec: float = 60.0


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

    def create_emergency_meeting(
        self,
        *,
        storage: StoragePort,
        knowledge_graph: KnowledgeGraphPort | None = None,
        qdrant: "QdrantStorage | None" = None,
        metrics: "MetricsCollector | None" = None,
    ) -> EmergencyMeeting:
        """Part 7 Stage 1 — wire EmergencyMeeting with current infrastructure."""
        return EmergencyMeeting(
            queue=self._queue,
            storage=storage,
            knowledge_graph=knowledge_graph,
            llm=self._llm,
            run_id=self._config.run_id,
            config=EmergencyMeetingConfig(
                response_timeout_sec=self._config.meeting_response_timeout_sec,
                cto_max_retries=self._config.meeting_cto_max_retries,
                cto_retry_interval_sec=self._config.meeting_cto_retry_interval_sec,
                cto_model=self._config.cto_model,
            ),
            dna_manager=self._dna_manager,
            qdrant=qdrant,
            metrics=metrics,
        )

    def create_peer_review_coordinator(
        self,
        *,
        storage: StoragePort,
        event_bus: EventBusPort,
        knowledge_graph: KnowledgeGraphPort | None = None,
        qdrant: "QdrantStorage | None" = None,
        metrics: "MetricsCollector | None" = None,
    ) -> PeerReviewCoordinator:
        """Part 7 Stage 2 — wire PeerReviewCoordinator. Subscribes to
        ``task.completed`` on the given event_bus when mode != OFF.

        Reviewer models are mapped per role from SystemConfig's existing model
        slots: backend/frontend use slm_model, mlops uses mlops_model, cto uses
        cto_model (cto is rarely picked as reviewer but kept for completeness).
        """
        return PeerReviewCoordinator(
            workspace=self._workspace,
            storage=storage,
            event_bus=event_bus,
            llm=self._llm,
            reviewer_model_by_role={
                "backend": self._config.slm_model,
                "frontend": self._config.slm_model,
                "mlops": self._config.mlops_model,
                "cto": self._config.cto_model,
            },
            run_id=self._config.run_id,
            config=PeerReviewConfig(
                mode=self._config.peer_review_mode,
                critical_duration_sec=self._config.peer_review_critical_duration_sec,
            ),
            knowledge_graph=knowledge_graph,
            dna_manager=self._dna_manager,
            qdrant=qdrant,
            metrics=metrics,
        )
