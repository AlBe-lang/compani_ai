"""DNAManager — TaskResult 기반 AgentDNA 진화 관리.

유전자 갱신 전략 (Rule 10: EMA α=0.2):
  precision       ← success 여부 (1.0 / 0.0)
  code_quality    ← success AND files 생성 여부
  debugging_skill ← error_code 없음 여부
  speed           ← 1 - clamp(duration / SPEED_REF_SEC, 0, 1)
  나머지 6개       ← 아직 갱신하지 않음 (향후 데이터 확보 시 확장)

success_rate / avg_duration / total_tasks 는 별도 롤링 평균으로 관리.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from domain.contracts import AgentDNA, PeerReviewDecision, PeerReviewSeverity, TaskResult
from observability.logger import get_logger

if TYPE_CHECKING:
    from domain.ports import StoragePort

log = get_logger(__name__)

_EMA_ALPHA = 0.2
# duration 기준값: 이 시간(초)보다 빠르면 speed=1.0, 느리면 0.0 방향으로 수렴
_SPEED_REF_SEC = 120.0
_DNA_KEY_PREFIX = "agent_dna:"

# precision > 이 임계값이면 시스템 프롬프트에 정확성 강조 지시어 추가
_PRECISION_THRESHOLD = 0.7
_CODE_QUALITY_THRESHOLD = 0.7
_CREATIVITY_THRESHOLD = 0.7
_COLLABORATION_THRESHOLD = 0.7

# temperature 조정 한계
_TEMP_MIN = 0.05
_TEMP_MAX = 0.9
_TEMP_PRECISION_DELTA = -0.1  # precision 높을수록 temperature 낮춤
_TEMP_CREATIVITY_DELTA = +0.1  # creativity 높을수록 temperature 높임


class DNAManager:
    """AgentDNA 로드·갱신·저장·변환 책임.

    StoragePort를 통해 SQLite에 DNA를 영속화한다.
    인메모리 캐시로 반복 로드 비용을 줄인다.
    """

    def __init__(self, storage: "StoragePort") -> None:
        self._storage = storage
        self._cache: dict[str, AgentDNA] = {}

    # ------------------------------------------------------------------
    # 퍼블릭 API
    # ------------------------------------------------------------------

    async def load(self, agent_id: str, role: str) -> AgentDNA:
        """저장된 DNA를 반환한다. 없으면 기본값으로 생성."""
        if agent_id in self._cache:
            return self._cache[agent_id].model_copy(deep=True)

        data = await self._storage.load(_DNA_KEY_PREFIX + agent_id)
        if data is not None:
            dna = AgentDNA.model_validate(data)
        else:
            dna = AgentDNA(agent_id=agent_id, role=role)

        self._cache[agent_id] = dna
        return dna.model_copy(deep=True)

    async def update(
        self,
        dna: AgentDNA,
        result: TaskResult,
        duration_sec: float,
    ) -> AgentDNA:
        """TaskResult를 바탕으로 DNA를 갱신하고 저장 후 반환한다."""
        updated = dna.model_copy(deep=True)

        # --- 집계 지표 롤링 평균 ---
        n = updated.total_tasks
        updated.total_tasks = n + 1
        # 누적 평균: new_avg = (old_avg * n + new_val) / (n + 1)
        success_val = 1.0 if result.success else 0.0
        updated.success_rate = (updated.success_rate * n + success_val) / updated.total_tasks
        updated.avg_duration = (updated.avg_duration * n + duration_sec) / updated.total_tasks

        # --- 유전자 EMA 갱신 ---
        self._ema_update(updated.genes, "precision", success_val)

        code_quality_val = 1.0 if (result.success and len(result.files) > 0) else 0.0
        self._ema_update(updated.genes, "code_quality", code_quality_val)

        debug_val = 1.0 if result.error_code is None else 0.0
        self._ema_update(updated.genes, "debugging_skill", debug_val)

        speed_val = max(0.0, 1.0 - duration_sec / _SPEED_REF_SEC)
        self._ema_update(updated.genes, "speed", speed_val)

        self._cache[dna.agent_id] = updated
        await self._save(updated)

        log.info(
            "dna_manager.updated",
            agent_id=dna.agent_id,
            total_tasks=updated.total_tasks,
            success_rate=round(updated.success_rate, 3),
            precision=round(updated.genes.get("precision", 0.5), 3),
            speed=round(updated.genes.get("speed", 0.5), 3),
        )
        return updated

    def to_system_prompt_modifier(self, dna: AgentDNA) -> str:
        """DNA 수치를 LLM 시스템 프롬프트 앞에 붙일 지시어로 변환한다.

        임계값을 초과한 유전자만 지시어를 생성해 프롬프트가 불필요하게 길어지는 것을 방지.
        """
        modifiers: list[str] = []

        if dna.genes.get("precision", 0.5) > _PRECISION_THRESHOLD:
            modifiers.append(
                "정확성을 최우선으로 합니다. 모든 출력은 스펙에 정확히 부합해야 합니다."
            )
        if dna.genes.get("code_quality", 0.5) > _CODE_QUALITY_THRESHOLD:
            modifiers.append(
                "높은 코드 품질을 유지합니다. 엣지 케이스와 오류 처리를 반드시 포함합니다."
            )
        if dna.genes.get("creativity", 0.5) > _CREATIVITY_THRESHOLD:
            modifiers.append("창의적이고 혁신적인 접근을 선호합니다.")
        if dna.genes.get("collaboration", 0.5) > _COLLABORATION_THRESHOLD:
            modifiers.append("자주 소통하고 피드백을 요청합니다.")

        if not modifiers:
            return ""
        return "[에이전트 행동 지침]\n" + "\n".join(f"- {m}" for m in modifiers) + "\n\n"

    def to_generation_params(self, dna: AgentDNA, base_temperature: float) -> dict[str, float]:
        """DNA → LLM 생성 파라미터 오버라이드를 반환한다."""
        temperature = base_temperature

        precision = dna.genes.get("precision", 0.5)
        if precision > _PRECISION_THRESHOLD:
            temperature += (
                _TEMP_PRECISION_DELTA
                * (precision - _PRECISION_THRESHOLD)
                / (1.0 - _PRECISION_THRESHOLD)
            )

        creativity = dna.genes.get("creativity", 0.5)
        if creativity > _CREATIVITY_THRESHOLD:
            temperature += (
                _TEMP_CREATIVITY_DELTA
                * (creativity - _CREATIVITY_THRESHOLD)
                / (1.0 - _CREATIVITY_THRESHOLD)
            )

        temperature = max(_TEMP_MIN, min(_TEMP_MAX, temperature))
        return {"temperature": round(temperature, 3)}

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _ema_update(genes: dict[str, float], gene: str, sample: float) -> None:
        prev = genes.get(gene, 0.5)
        genes[gene] = _EMA_ALPHA * sample + (1 - _EMA_ALPHA) * prev

    async def update_meeting_participation(self, agent_id: str, role: str) -> AgentDNA:
        """Part 7 Stage 1 — emergency meeting 참여 시 카운트만 +1.

        Stage 1에서는 판정 기반 collaboration 유전자 EMA 반영은 하지 않는다
        (정답 기준이 Stage 2 피어 리뷰와 얽혀 있어 그때 통합 설계). 단순
        참여 횟수만 누적해 향후 통계·라우팅 신호로 활용 가능하게 둔다.
        """
        dna = await self.load(agent_id, role)
        updated = dna.model_copy(deep=True)
        updated.meeting_participation_count += 1
        self._cache[agent_id] = updated
        await self._save(updated)
        log.info(
            "dna_manager.meeting_participation",
            agent_id=agent_id,
            count=updated.meeting_participation_count,
        )
        return updated

    async def update_review_feedback(
        self,
        *,
        reviewer_agent_id: str,
        reviewer_role: str,
        author_agent_id: str,
        author_role: str,
        decision: PeerReviewDecision,
        severity: PeerReviewSeverity,
    ) -> None:
        """Part 7 Stage 2 — apply peer-review outcome to both participants' DNA.

        Reviewer side:
          - review_count += 1 (frequency, independent of vote quality)
          - collaboration EMA sample = 1.0 (participated meaningfully;
            Stage 1의 Q5 C 유보 항목 "판정 기반 collaboration"을 여기서 해소)

        Author side:
          - precision EMA sample from decision (APPROVE=1.0, REQUEST_CHANGES=0.5, REJECT=0.0)
          - code_quality EMA sample from severity when REQUEST_CHANGES
            (APPROVE=1.0, MINOR=0.8, MAJOR=0.5, CRITICAL=0.2, REJECT=0.0)

        Both updates are independent; a failure in one side does not roll back
        the other (EMA is self-healing over enough samples).
        """
        # Reviewer
        reviewer_dna = await self.load(reviewer_agent_id, reviewer_role)
        reviewer_updated = reviewer_dna.model_copy(deep=True)
        reviewer_updated.review_count += 1
        self._ema_update(reviewer_updated.genes, "collaboration", 1.0)
        self._cache[reviewer_agent_id] = reviewer_updated
        await self._save(reviewer_updated)

        # Author
        author_dna = await self.load(author_agent_id, author_role)
        author_updated = author_dna.model_copy(deep=True)
        precision_sample = _decision_to_precision_sample(decision)
        code_quality_sample = _decision_severity_to_code_quality_sample(decision, severity)
        self._ema_update(author_updated.genes, "precision", precision_sample)
        self._ema_update(author_updated.genes, "code_quality", code_quality_sample)
        self._cache[author_agent_id] = author_updated
        await self._save(author_updated)

        log.info(
            "dna_manager.review_feedback",
            reviewer=reviewer_agent_id,
            author=author_agent_id,
            decision=decision.value,
            severity=severity.value,
            reviewer_review_count=reviewer_updated.review_count,
            author_precision=round(author_updated.genes.get("precision", 0.5), 3),
            author_code_quality=round(author_updated.genes.get("code_quality", 0.5), 3),
        )

    async def _save(self, dna: AgentDNA) -> None:
        payload: dict[str, object] = {
            "agent_id": dna.agent_id,
            "role": dna.role,
            "expertise": dna.expertise,
            "success_rate": dna.success_rate,
            "avg_duration": dna.avg_duration,
            "total_tasks": dna.total_tasks,
            "genes": dna.genes,
            "meeting_participation_count": dna.meeting_participation_count,
            "review_count": dna.review_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._storage.save(_DNA_KEY_PREFIX + dna.agent_id, payload)


# ----------------------------------------------------------------------
# Module-level helpers for review feedback mapping (Part 7 Stage 2).
# Exposed at module scope so tests can validate the table without needing
# a full DNAManager instance.
# ----------------------------------------------------------------------


_PRECISION_SAMPLE = {
    PeerReviewDecision.APPROVE: 1.0,
    PeerReviewDecision.REQUEST_CHANGES: 0.5,
    PeerReviewDecision.REJECT: 0.0,
}

_CODE_QUALITY_REQUEST_CHANGES = {
    PeerReviewSeverity.MINOR: 0.8,
    PeerReviewSeverity.MAJOR: 0.5,
    PeerReviewSeverity.CRITICAL: 0.2,
}


def _decision_to_precision_sample(decision: PeerReviewDecision) -> float:
    return _PRECISION_SAMPLE[decision]


def _decision_severity_to_code_quality_sample(
    decision: PeerReviewDecision, severity: PeerReviewSeverity
) -> float:
    if decision is PeerReviewDecision.APPROVE:
        return 1.0
    if decision is PeerReviewDecision.REJECT:
        return 0.0
    return _CODE_QUALITY_REQUEST_CHANGES[severity]
