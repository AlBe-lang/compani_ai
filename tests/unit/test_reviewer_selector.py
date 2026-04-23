"""Tests for reviewer selection strategies — Part 7 Stage 2."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from application.reviewer_selector import FixedWithKGFallbackSelector


def _make_kg(result: str | None) -> MagicMock:
    mock = MagicMock()
    mock.find_best_responder = AsyncMock(return_value=result)
    return mock


async def test_fixed_fallback_when_no_kg() -> None:
    selector = FixedWithKGFallbackSelector(knowledge_graph=None)
    assert await selector.select("backend", {}) == "frontend"
    assert await selector.select("frontend", {}) == "backend"
    assert await selector.select("mlops", {}) == "backend"


async def test_fixed_fallback_when_kg_returns_none() -> None:
    selector = FixedWithKGFallbackSelector(knowledge_graph=_make_kg(None))
    assert await selector.select("backend", {"approach": "something"}) == "frontend"


async def test_kg_hit_overrides_fixed_when_different_role() -> None:
    selector = FixedWithKGFallbackSelector(knowledge_graph=_make_kg("mlops"))
    assert await selector.select("backend", {"approach": "deploy pipeline"}) == "mlops"


async def test_kg_ignored_when_same_role_as_author() -> None:
    """KG opportunistic — must never pick author's own role."""
    selector = FixedWithKGFallbackSelector(knowledge_graph=_make_kg("backend"))
    assert (
        await selector.select("backend", {"approach": "api stuff"}) == "frontend"
    )  # falls through to fixed map


async def test_kg_ignored_when_unknown_role() -> None:
    selector = FixedWithKGFallbackSelector(knowledge_graph=_make_kg("designer"))
    assert await selector.select("backend", {"approach": "ui wireframe"}) == "frontend"


async def test_unknown_author_role_returns_none() -> None:
    selector = FixedWithKGFallbackSelector(knowledge_graph=None)
    assert await selector.select("unknown_role", {}) is None


async def test_empty_context_text_skips_kg_path() -> None:
    """No approach/description → KG call should not be made."""
    kg = _make_kg("mlops")
    selector = FixedWithKGFallbackSelector(knowledge_graph=kg)
    result = await selector.select("backend", {})
    assert result == "frontend"
    kg.find_best_responder.assert_not_called()
