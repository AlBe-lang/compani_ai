"""JSON structured logging setup."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from typing import Any

structlog: Any
try:
    structlog = importlib.import_module("structlog")
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    structlog = None

_CONFIGURED = False


class _DynamicStderr:
    """Write to sys.stderr at call time (not at configure time).

    Structlog's PrintLoggerFactory stores a file reference once. Using a proxy
    ensures tests that redirect sys.stderr (e.g. pytest capsys) are handled
    correctly without I/O-on-closed-file errors.
    """

    def write(self, s: str) -> int:
        return sys.stderr.write(s)

    def flush(self) -> None:
        try:
            sys.stderr.flush()
        except Exception:
            pass


class _FallbackLogger:
    """Minimal JSON logger used when structlog is unavailable."""

    def __init__(self, context: dict[str, Any] | None = None) -> None:
        self._context = context or {}

    def bind(self, **kwargs: Any) -> "_FallbackLogger":
        context = dict(self._context)
        context.update(kwargs)
        return _FallbackLogger(context)

    def _emit(self, level: str, event: str, **kwargs: Any) -> None:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            **self._context,
            **kwargs,
        }
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit("debug", event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit("info", event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._emit("warning", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._emit("error", event, **kwargs)


def configure_logging(force: bool = False) -> None:
    """Configure structlog once for JSON output."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    if structlog is not None:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            # stderr keeps logs separate from Rich Live's stdout display
            logger_factory=structlog.PrintLoggerFactory(file=_DynamicStderr()),
            cache_logger_on_first_use=False,
        )
    _CONFIGURED = True


def get_logger(component: str, run_id: str | None = None) -> Any:
    """Return a component logger with optional run context."""
    configure_logging()
    if structlog is not None:
        logger = structlog.get_logger().bind(component=component)
        if run_id:
            logger = logger.bind(run_id=run_id)
        return logger

    logger = _FallbackLogger().bind(component=component)
    if run_id:
        logger = logger.bind(run_id=run_id)
    return logger
