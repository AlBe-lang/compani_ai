"""Reviewer selection strategies for peer review (Part 7 Stage 2).

Pluggable selector pattern so Stage 3 can add DNA-weighted / load-balanced /
conflict-of-interest rules without modifying PeerReviewCoordinator. Rule 10
§3 — implementation hidden behind the ``ReviewerSelector`` Protocol.

Stage 2 ships one concrete strategy:
  ``FixedWithKGFallbackSelector``
    - Default: rotating mapping (backend→frontend, frontend→backend,
      mlops→backend). Deterministic, test-friendly.
    - Opportunistic KG: if ``knowledge_graph.find_best_responder`` returns a
      role different from the producer, use it. Else fall back to fixed map.

Stage 3 will add e.g. ``DNAAwareSelector`` that factors in collaboration
EMA and recent-review load — same Protocol, no Coordinator rewrite.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from domain.ports import KnowledgeGraphPort
from observability.logger import get_logger

log = get_logger(__name__)

# Rotating fixed map. Keys are producer roles; values are fallback reviewer roles.
# Chosen to cover every role and avoid backend↔frontend deadlock on both sides.
_FIXED_REVIEWER_MAP: dict[str, str] = {
    "backend": "frontend",
    "frontend": "backend",
    "mlops": "backend",
}
_KNOWN_ROLES: frozenset[str] = frozenset(_FIXED_REVIEWER_MAP.keys())


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
