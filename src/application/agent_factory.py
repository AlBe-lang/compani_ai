"""Composition root — assembles the full agent team from concrete adapters."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from application.backend_agent import BackendSLMAgent, BackendSLMConfig
from application.concurrency import LLMConcurrencyLimiter
from application.cto_agent import CTOAgent, CTOConfig
from application.emergency_meeting import EmergencyMeeting, EmergencyMeetingConfig
from application.frontend_agent import FrontendSLMAgent, FrontendSLMConfig
from application.mlops_agent import MLOpsSLMAgent, MLOpsSLMConfig
from application.peer_review import PeerReviewConfig, PeerReviewCoordinator, PeerReviewMode
from application.reviewer_selector import (
    DNAAwareSelector,
    FixedWithKGFallbackSelector,
    ReviewerSelector,
)
from application.rework_scheduler import ReworkConfig, ReworkScheduler
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

_DEFAULT_CTO_MODEL = "qwen3:8b"
_DEFAULT_SLM_MODEL = "gemma4:e4b"
_DEFAULT_MLOPS_MODEL = "llama3.2:3b"


class EmbeddingPreset(str, Enum):
    """Part 8 Stage 1 (R-05B/C) — Qdrant 임베딩 모델 선택지.

    전환 시 벡터 차원이 달라지므로 기존 컬렉션은 재생성 필요 (R-05C 자동 통합
    — QdrantStorage.init이 차원 불일치 감지 시 WARN 후 재생성).

    기본값 근거: MTEB 다국어 벤치에서 mpnet-base-v2 이 MiniLM 대비 +15% 품질.
    Mac Mini M4 16GB 기준 메모리 여유 0.8GB 로 수용 가능. 실전 E2E 에서 swap
    감지되면 MINILM_FAST 로 복원 (1줄 변경). E5_BEST 는 2.24GB 로 Mac Mini
    에선 불가 — Windows 32GB+ 전용.
    """

    MINILM_FAST = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"  # 384d
    MPNET_BALANCED = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"  # 768d
    E5_BEST = "intfloat/multilingual-e5-large"  # 1024d


# Embedding preset → vector dimension (Qdrant VectorParams.size).
# Hardcoded from model cards; kept in sync with EmbeddingPreset literal values.
_PRESET_DIMENSIONS: dict[EmbeddingPreset, int] = {
    EmbeddingPreset.MINILM_FAST: 384,
    EmbeddingPreset.MPNET_BALANCED: 768,
    EmbeddingPreset.E5_BEST: 1024,
}


def preset_vector_size(preset: EmbeddingPreset) -> int:
    """Return the vector dimension for the given preset."""
    return _PRESET_DIMENSIONS[preset]


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
    # Part 7 Stage 3 — 자동 리뷰어 선정 + rework. 기본 off: Stage 2와 동일한
    # backward-compat 동작을 유지. DNA_AWARE 선택 시 DNAAwareSelector가 주입되며
    # COI 필터로 후보가 0이면 FixedWithKGFallbackSelector로 자동 폴백.
    reviewer_selector_mode: str = "fixed"  # "fixed" | "dna_aware"
    rework_enabled: bool = False
    rework_max_attempts: int = 2
    # Part 8 Stage 1 — 임베딩 모델 선택지 (R-05B/C)
    embedding_preset: EmbeddingPreset = EmbeddingPreset.MPNET_BALANCED
    # 차원 불일치 시 자동 컬렉션 재생성 허용 여부. False 면 명확한 오류 메시지
    # 로 실패(사용자가 명시 opt-in 해야 데이터 손실 가능 전환 수행).
    allow_embedding_collection_recreate: bool = True
    # Part 8 Stage 1 — LLM 동시성 상한 (Q5)
    # 기본값은 Mac Mini M4 16GB 기준 안전값. 32GB+ 데스크탑에선 slm=2/total=3 권장.
    llm_concurrency_cto: int = 1
    llm_concurrency_slm: int = 1
    llm_concurrency_mlops: int = 1
    llm_concurrency_total: int = 2
    # Part 8 Stage 2 — CEO 대시보드 서버 (Q5 — Jupyter-style token, localhost bind)
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000
    # 기본값 빈 문자열 = create_app()이 자동 생성. CLI/env 로 명시 토큰 고정 가능.
    dashboard_token: str = ""
    # WebSocket metrics_tick 주기 (초). 0 이면 tick 루프 비활성화.
    dashboard_poll_interval_sec: float = 5.0
    # Part 8 Stage 2 (R-09B): 새 프로젝트 실행 시 WorkItem.rework_count 리셋 여부.
    # True 면 각 run 시작 시 rework_count=0 으로 시작, False 면 누적.
    rework_reset_on_new_run: bool = True


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

    def create_concurrency_limiter(self) -> LLMConcurrencyLimiter:
        """Part 8 Stage 1 — per-role + total LLM concurrency limiter."""
        return LLMConcurrencyLimiter(
            cto=self._config.llm_concurrency_cto,
            slm=self._config.llm_concurrency_slm,
            mlops=self._config.llm_concurrency_mlops,
            total=self._config.llm_concurrency_total,
        )

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
        """Part 7 Stage 2-3 — wire PeerReviewCoordinator.

        Subscribes to ``task.completed`` on the given event_bus when mode != OFF.
        Reviewer model mapping uses SystemConfig's existing slots (backend/frontend
        → slm_model, mlops → mlops_model, cto → cto_model). Stage 3 selects
        ``DNAAwareSelector`` when ``reviewer_selector_mode == "dna_aware"`` and
        a DNAManager is available; falls back to ``FixedWithKGFallbackSelector``.
        """
        primary_selector: ReviewerSelector | None = self._build_reviewer_selector(
            knowledge_graph=knowledge_graph
        )
        fallback_selector = FixedWithKGFallbackSelector(knowledge_graph=knowledge_graph)
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
            selector=primary_selector,
            fallback_selector=fallback_selector,
            knowledge_graph=knowledge_graph,
            dna_manager=self._dna_manager,
            qdrant=qdrant,
            metrics=metrics,
        )

    def _build_reviewer_selector(
        self, *, knowledge_graph: KnowledgeGraphPort | None
    ) -> ReviewerSelector:
        """Part 7 Stage 3 — pick primary selector based on SystemConfig."""
        mode = (self._config.reviewer_selector_mode or "fixed").lower()
        if mode == "dna_aware" and self._dna_manager is not None:
            return DNAAwareSelector(dna_manager=self._dna_manager)
        return FixedWithKGFallbackSelector(knowledge_graph=knowledge_graph)

    def create_rework_scheduler(
        self,
        *,
        storage: StoragePort,
        event_bus: EventBusPort,
        agents: Mapping[str, AgentPort],
        metrics: "MetricsCollector | None" = None,
    ) -> ReworkScheduler:
        """Part 7 Stage 3 — wire ReworkScheduler.

        Subscribes to ``review.rework_requested`` when ``rework_enabled=True``.
        ``agents`` is the same role→AgentPort map as ``create_team()`` returns.
        """
        return ReworkScheduler(
            workspace=self._workspace,
            storage=storage,
            event_bus=event_bus,
            agents=agents,
            run_id=self._config.run_id,
            config=ReworkConfig(
                enabled=self._config.rework_enabled,
                max_attempts=self._config.rework_max_attempts,
            ),
            metrics=metrics,
        )
