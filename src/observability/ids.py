"""Identifier helpers for traceability."""

from __future__ import annotations

from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def generate_run_id() -> str:
    """Create a run-scoped unique identifier."""
    return _new_id("run")


def generate_task_id() -> str:
    """Create a task-scoped unique identifier."""
    return _new_id("task")


def generate_message_id() -> str:
    """Create a message-scoped unique identifier."""
    return _new_id("msg")

