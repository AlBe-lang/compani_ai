"""Lightweight trace-ID propagation via contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def new_trace() -> str:
    """Start a new trace and return the generated trace_id."""
    tid = uuid4().hex[:16]
    _trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    """Return the current trace_id, or empty string if not set."""
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """Attach an existing trace_id to the current async context."""
    _trace_id_var.set(trace_id)
