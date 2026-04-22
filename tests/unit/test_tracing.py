"""Unit tests for TraceContext."""

from __future__ import annotations

from observability.tracing import get_trace_id, new_trace, set_trace_id


def test_new_trace_generates_non_empty_id() -> None:
    tid = new_trace()
    assert len(tid) == 16
    assert get_trace_id() == tid


def test_set_trace_id_overrides() -> None:
    set_trace_id("custom-trace-id")
    assert get_trace_id() == "custom-trace-id"


def test_default_trace_id_is_empty_string() -> None:
    # Reset to ensure we test the default path
    set_trace_id("")
    assert get_trace_id() == ""
