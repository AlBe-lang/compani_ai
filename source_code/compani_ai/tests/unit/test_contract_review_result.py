from __future__ import annotations

from domain.contracts import ReviewDecision, ReviewResult


def test_review_result_serialization_roundtrip() -> None:
    result = ReviewResult(
        decision=ReviewDecision.REPLAN,
        reason="Need to replan failed tasks",
        new_tasks=[],
    )

    restored = ReviewResult.model_validate_json(result.model_dump_json())

    assert restored.decision is ReviewDecision.REPLAN
    assert restored.reason.startswith("Need to")
    assert restored.new_tasks == []
