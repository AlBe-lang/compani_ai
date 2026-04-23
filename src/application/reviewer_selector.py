"""Reviewer selection strategies for peer review (Part 7 Stage 2-3).

Pluggable selector pattern: Coordinator stays unchanged while strategies
evolve. Rule 10 §3 — implementation hidden behind the ``ReviewerSelector``
Protocol.

Implementations:
  Stage 2: ``FixedWithKGFallbackSelector``
    - Default: rotating mapping (backend→frontend, frontend→backend,
      mlops→backend). Deterministic, test-friendly.
    - Opportunistic KG: if ``knowledge_graph.find_best_responder`` returns a
      role different from the producer, use it. Else fall back to fixed map.

  Stage 3: ``DNAAwareSelector``
    - Scoring: (collab×0.5 + precision×0.5) × exp(-recent/k)  (승법 감쇠)
    - COI Tier 1 (hard exclude): author + direct dependency source roles
    - COI Tier 2 (soft penalty ×0.7): in-run transitive ancestor roles
    - Fallback: caller cascades to ``FixedWithKGFallbackSelector`` when this
      returns None so the system never stalls.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING, Iterable, Protocol, runtime_checkable

from domain.ports import KnowledgeGraphPort
from observability.logger import get_logger

if TYPE_CHECKING:
    from application.dna_manager import DNAManager

log = get_logger(__name__)

# Rotating fixed map. Keys are producer roles; values are fallback reviewer roles.
# Chosen to cover every role and avoid backend↔frontend deadlock on both sides.
_FIXED_REVIEWER_MAP: dict[str, str] = {
    "backend": "frontend",
    "frontend": "backend",
    "mlops": "backend",
}
_KNOWN_ROLES: frozenset[str] = frozenset(_FIXED_REVIEWER_MAP.keys())

# DNAAwareSelector parameters (documented in Stage 3 journal §3).
_DNA_WEIGHT_COLLAB = 0.5
_DNA_WEIGHT_PRECISION = 0.5
_LOAD_DECAY_K = 5.0  # exp(-recent/k): recent=k → decay≈0.37, recent=2k → ≈0.14
_TIER2_PENALTY = 0.7  # multiplier for transitive-ancestor soft penalty


@runtime_checkable
class ReviewerSelector(Protocol):
    """Contract for selecting a reviewer role given a producer role + context."""

    async def select(self, author_role: str, context: dict[str, object]) -> str | None:
        """Return a reviewer role string (e.g. 'frontend'), or None if no
        suitable reviewer can be chosen. ``context`` may include the task
        description / approach for semantic matching."""


class FixedWithKGFallbackSelector:
    """Stage 2 default selector — rotating map, optionally overridden by KG.

    The KG result is treated as **opportunistic**: applied only when it differs
    from the author role AND is a known role. This intentionally keeps Stage 3
    scope meaningful (DNA weighting, load balancing, COI rules all still open).
    """

    def __init__(self, knowledge_graph: KnowledgeGraphPort | None = None) -> None:
        self._kg = knowledge_graph

    async def select(self, author_role: str, context: dict[str, object]) -> str | None:
        # 1. KG opportunistic match on the approach/description text
        if self._kg is not None:
            hint = str(context.get("approach") or context.get("description") or "")
            if hint:
                try:
                    kg_role = await self._kg.find_best_responder(hint)
                except Exception as exc:  # pragma: no cover — defensive
                    log.warning("reviewer_selector.kg_error", detail=str(exc))
                    kg_role = None
                if kg_role and kg_role != author_role and kg_role in _KNOWN_ROLES:
                    log.info(
                        "reviewer_selector.selected.kg",
                        author=author_role,
                        reviewer=kg_role,
                    )
                    return kg_role

        # 2. Fixed fallback map
        reviewer = _FIXED_REVIEWER_MAP.get(author_role)
        if reviewer is None:
            log.warning("reviewer_selector.unknown_role", author=author_role)
            return None
        log.info(
            "reviewer_selector.selected.fixed",
            author=author_role,
            reviewer=reviewer,
        )
        return reviewer


class DNAAwareSelector:
    """Stage 3 selector — DNA-weighted scoring with load decay and COI filter.

    Formula (Q1 채택 B 승법 감쇠):
        base  = 0.5 * collab + 0.5 * precision
        decay = exp(-recent_review_count / 5.0)
        score = base * decay        # ∈ (0, 1]

    COI (Q2 채택 Tier 1 + Tier 2 hybrid):
        Tier 1 hard exclude: author role + direct-dep source roles
        Tier 2 soft penalty (×0.7): transitive-ancestor roles active in run

    ``context`` consumed by ``select``:
        - "dep_source_roles":  Iterable[str]  — direct-dep source (Tier 1)
        - "transitive_roles":  Iterable[str]  — broader ancestor set (Tier 2)

    If every role is excluded or scores zero, returns ``None``; callers
    cascade to ``FixedWithKGFallbackSelector`` to keep the pipeline live.
    """

    def __init__(
        self,
        dna_manager: "DNAManager",
        *,
        candidate_roles: Iterable[str] = _KNOWN_ROLES,
        decay_k: float = _LOAD_DECAY_K,
        tier2_penalty: float = _TIER2_PENALTY,
    ) -> None:
        self._dna = dna_manager
        self._candidates: tuple[str, ...] = tuple(candidate_roles)
        self._decay_k = decay_k
        self._tier2_penalty = tier2_penalty
        # Per-role running review count within the current run.
        self._recent_counts: dict[str, int] = defaultdict(int)

    def record_review(self, reviewer_role: str) -> None:
        """Increment in-run counter after a review completes."""
        self._recent_counts[reviewer_role] += 1

    def reset_load(self) -> None:
        """Clear the in-run counter (e.g. at the start of a new project run)."""
        self._recent_counts.clear()

    async def select(self, author_role: str, context: dict[str, object]) -> str | None:
        dep_source_roles = _coerce_role_set(context.get("dep_source_roles"))
        transitive_roles = _coerce_role_set(context.get("transitive_roles"))
        tier1_excluded = {author_role} | dep_source_roles

        scored: list[tuple[str, float]] = []
        for role in self._candidates:
            if role in tier1_excluded:
                continue
            score = await self._score_role(role)
            if role in transitive_roles:
                score *= self._tier2_penalty
            if score > 0.0:
                scored.append((role, score))

        if not scored:
            log.warning(
                "reviewer_selector.dna.no_candidates",
                author=author_role,
                tier1_excluded=sorted(tier1_excluded),
                transitive=sorted(transitive_roles),
            )
            return None

        # Deterministic tie-break: score desc, role asc.
        scored.sort(key=lambda rs: (-rs[1], rs[0]))
        best_role, best_score = scored[0]
        log.info(
            "reviewer_selector.selected.dna",
            author=author_role,
            reviewer=best_role,
            score=round(best_score, 4),
            tier1_excluded=sorted(tier1_excluded),
            transitive=sorted(transitive_roles),
        )
        return best_role

    async def _score_role(self, role: str) -> float:
        """Compute `(collab*0.5 + precision*0.5) * exp(-recent/k)`."""
        try:
            dna = await self._dna.load(role, role)
        except Exception as exc:
            log.warning("reviewer_selector.dna_load_error", role=role, detail=str(exc))
            return 0.0
        collab = float(dna.genes.get("collaboration", 0.5))
        precision = float(dna.genes.get("precision", 0.5))
        base = _DNA_WEIGHT_COLLAB * collab + _DNA_WEIGHT_PRECISION * precision
        decay = math.exp(-self._recent_counts[role] / self._decay_k)
        return base * decay


def _coerce_role_set(raw: object) -> set[str]:
    """Defensive coercion — context values may arrive as list/tuple/set/None."""
    if raw is None:
        return set()
    if isinstance(raw, (list, tuple, set, frozenset)):
        return {str(x) for x in raw if x}
    return set()
