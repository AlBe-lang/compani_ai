"""Unit tests for DNAAwareSelector — Part 7 Stage 3.

Covers:
  1. Scoring formula — (collab*0.5 + prec*0.5) * exp(-recent/k)
  2. COI Tier 1 hard exclude (author + dep source roles)
  3. COI Tier 2 soft penalty (*0.7 for transitive roles)
  4. Load decay via record_review()
  5. Fallback behavior: returns None when all candidates excluded
  6. Deterministic tie-break (role asc)
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

from application.reviewer_selector import DNAAwareSelector
from domain.contracts import AgentDNA


def _make_dna_manager(gene_overrides: dict[str, tuple[float, float]] | None = None) -> MagicMock:
    """(role: (collab, precision)). Default neutral 0.5/0.5."""
    overrides = gene_overrides or {}
    mock = MagicMock()

    async def _load(agent_id: str, role: str) -> AgentDNA:
        collab, prec = overrides.get(agent_id, (0.5, 0.5))
        dna = AgentDNA(agent_id=agent_id, role=role)
        dna.genes["collaboration"] = collab
        dna.genes["precision"] = prec
        return dna

    mock.load = AsyncMock(side_effect=_load)
    return mock


async def test_scoring_neutral_all_equal_picks_alphabetical() -> None:
    selector = DNAAwareSelector(
        _make_dna_manager(), candidate_roles=("frontend", "backend", "mlops")
    )
    # author=frontend excluded; backend & mlops tied (0.5 × 1.0) → backend wins (A-Z)
    role = await selector.select("frontend", {})
    assert role == "backend"


async def test_higher_dna_wins_over_neutral() -> None:
    selector = DNAAwareSelector(_make_dna_manager({"backend": (0.9, 0.9), "mlops": (0.5, 0.5)}))
    role = await selector.select("frontend", {})
    assert role == "backend"  # 0.9 > 0.5


async def test_load_decay_shifts_winner() -> None:
    selector = DNAAwareSelector(_make_dna_manager({"backend": (0.9, 0.9), "mlops": (0.5, 0.5)}))
    # Without load: backend wins (0.9 vs 0.5)
    # With heavy backend load: backend decays below mlops
    for _ in range(10):
        selector.record_review("backend")
    role = await selector.select("frontend", {})
    # backend score = 0.9 * exp(-10/5) = 0.9 * 0.1353 ≈ 0.122
    # mlops score   = 0.5 * 1.0 = 0.5
    # → mlops wins
    assert role == "mlops"


async def test_tier1_excludes_author() -> None:
    selector = DNAAwareSelector(_make_dna_manager())
    role = await selector.select("backend", {})
    # backend excluded; frontend and mlops tied → frontend (alphabetical)
    assert role in ("frontend", "mlops")
    assert role != "backend"


async def test_tier1_excludes_dep_source_roles() -> None:
    selector = DNAAwareSelector(_make_dna_manager())
    role = await selector.select("mlops", {"dep_source_roles": ["backend"]})
    # mlops (author) + backend (dep source) excluded → only frontend remains
    assert role == "frontend"


async def test_tier2_soft_penalty_applied() -> None:
    # Both backend and mlops have neutral DNA (0.5/0.5). Backend is transitive,
    # so score 0.5 × 0.7 = 0.35 vs mlops 0.5. mlops wins.
    selector = DNAAwareSelector(_make_dna_manager())
    role = await selector.select("frontend", {"transitive_roles": ["backend"]})
    assert role == "mlops"


async def test_tier1_plus_tier2_combined() -> None:
    # author=backend → exclude backend (Tier 1)
    # dep_source=frontend → also exclude frontend (Tier 1)
    # → only mlops remains
    selector = DNAAwareSelector(_make_dna_manager())
    role = await selector.select(
        "backend",
        {"dep_source_roles": ["frontend"], "transitive_roles": ["mlops"]},
    )
    # mlops is transitive → still selected (single candidate)
    assert role == "mlops"


async def test_all_excluded_returns_none() -> None:
    # Exclude every role via Tier 1 — no candidate survives
    selector = DNAAwareSelector(_make_dna_manager())
    role = await selector.select(
        "backend",
        {"dep_source_roles": ["frontend", "mlops"]},
    )
    assert role is None


async def test_record_review_increments_load() -> None:
    dna_mgr = _make_dna_manager({"backend": (1.0, 1.0), "mlops": (1.0, 1.0)})
    selector = DNAAwareSelector(dna_mgr)
    # Same DNA — initially backend wins (alphabetical tie-break, since both 1.0)
    role1 = await selector.select("frontend", {})
    assert role1 == "backend"
    # After 5 backend reviews, mlops should overtake (exp(-5/5) = 0.37)
    for _ in range(5):
        selector.record_review("backend")
    role2 = await selector.select("frontend", {})
    # backend: 1.0 * 0.37 = 0.37; mlops: 1.0 * 1.0 = 1.0 → mlops wins
    assert role2 == "mlops"


async def test_reset_load_clears_counter() -> None:
    selector = DNAAwareSelector(_make_dna_manager({"backend": (0.9, 0.9), "mlops": (0.5, 0.5)}))
    for _ in range(10):
        selector.record_review("backend")
    # After reset, backend regains full score → wins again
    selector.reset_load()
    role = await selector.select("frontend", {})
    assert role == "backend"


async def test_dna_load_error_falls_back_to_zero() -> None:
    mock = MagicMock()
    mock.load = AsyncMock(side_effect=RuntimeError("boom"))
    selector = DNAAwareSelector(mock, candidate_roles=("backend",))
    # Every load fails → every score is 0 → None returned
    role = await selector.select("frontend", {})
    assert role is None


async def test_scoring_formula_matches_spec() -> None:
    """Validate exact formula: (collab*0.5 + prec*0.5) * exp(-recent/5)."""
    selector = DNAAwareSelector(
        _make_dna_manager({"backend": (0.8, 0.6)}),
        candidate_roles=("backend",),
    )
    selector.record_review("backend")
    selector.record_review("backend")
    # Internal _score_role:
    expected = (0.5 * 0.8 + 0.5 * 0.6) * math.exp(-2 / 5.0)
    score = await selector._score_role("backend")
    assert abs(score - expected) < 1e-9
