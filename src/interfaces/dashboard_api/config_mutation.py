"""SystemConfig runtime mutation — Part 8 Stage 2 (Q3 hot-reload classification).

3-category classification for every SystemConfig field:

  * ``hot_reloadable`` — component reads directly from SystemConfig on each
    call, so mutation takes effect on the very next invocation. UI shows
    green "즉시 적용" badge.
  * ``restart_required`` — component captured the value at __init__; mutation
    updates SystemConfig but current run still uses old value. UI shows
    yellow "다음 프로젝트부터" badge.
  * ``destructive`` — mutation requires collection recreation or model reload.
    UI shows red warning badge + confirmation modal (R-10D).

PATCH API routes through ``apply_mutation()`` which validates the field name,
classifies it, and applies the in-place update. Destructive fields require
``confirm=True`` in the request body.
"""

from __future__ import annotations

from dataclasses import fields
from enum import Enum
from typing import Any

from application.agent_factory import EmbeddingPreset, SystemConfig
from application.peer_review import PeerReviewMode
from observability.logger import get_logger

log = get_logger(__name__)


class ReloadCategory(str, Enum):
    HOT_RELOADABLE = "hot_reloadable"
    RESTART_REQUIRED = "restart_required"
    DESTRUCTIVE = "destructive"


# Classification maps — keep synchronised with Stage 1/2 refactors. Adding a
# field to ``HOT_RELOADABLE`` requires the corresponding component to read the
# value at call-time (not cache it at __init__). See 개발 일지(2).md §3.
HOT_RELOADABLE: frozenset[str] = frozenset(
    {
        # Peer review / rework — components now read via SystemConfig ref
        "peer_review_mode",
        "peer_review_critical_duration_sec",
        "reviewer_selector_mode",
        "rework_enabled",
        "rework_max_attempts",
        # LLM concurrency — limiter exposes update_limits() at runtime
        "llm_concurrency_cto",
        "llm_concurrency_slm",
        "llm_concurrency_mlops",
        "llm_concurrency_total",
        # Meeting timeouts — EmergencyMeeting reads on each convene()
        "meeting_response_timeout_sec",
        "meeting_cto_max_retries",
        "meeting_cto_retry_interval_sec",
    }
)

DESTRUCTIVE: frozenset[str] = frozenset(
    {
        # Changing embedding model requires Qdrant collection recreation
        "embedding_preset",
    }
)


def classify(field_name: str) -> ReloadCategory:
    if field_name in HOT_RELOADABLE:
        return ReloadCategory.HOT_RELOADABLE
    if field_name in DESTRUCTIVE:
        return ReloadCategory.DESTRUCTIVE
    return ReloadCategory.RESTART_REQUIRED


def serialise_config(config: SystemConfig) -> dict[str, Any]:
    """Dump SystemConfig as JSON-safe dict with per-field metadata.

    Return shape::

        {
            "fields": {
                "peer_review_mode": {
                    "value": "off",
                    "category": "hot_reloadable",
                    "type": "enum",
                    "options": ["off", "all", "critical"],
                },
                ...
            },
            "token_preview": "abc1…"   # first 4 chars only for UX hint
        }

    Sensitive-looking fields (tokens, passwords) are masked.
    """
    field_entries: dict[str, dict[str, Any]] = {}
    for f in fields(config):
        raw_value = getattr(config, f.name)
        value_json = _to_json(raw_value)
        category = classify(f.name)
        field_info: dict[str, Any] = {
            "value": value_json,
            "category": category.value,
            "type": _type_hint(raw_value),
        }
        options = _enum_options(raw_value)
        if options is not None:
            field_info["options"] = options
        if _is_sensitive(f.name):
            field_info["value"] = _mask(str(value_json))
            field_info["sensitive"] = True
        field_entries[f.name] = field_info
    return {"fields": field_entries}


class ConfigMutationError(ValueError):
    """Raised when a mutation request is invalid."""


def apply_mutation(
    config: SystemConfig,
    field_name: str,
    new_value: Any,
    *,
    confirm: bool = False,
) -> ReloadCategory:
    """Mutate ``config.<field_name>`` to ``new_value`` with validation.

    Returns the :class:`ReloadCategory` so the caller can inform the client
    whether the change applies immediately, on next run, or requires
    additional steps (collection recreation).

    Raises ``ConfigMutationError`` for unknown field, wrong type, or
    destructive mutation without ``confirm=True``.
    """
    field_meta = {f.name: f for f in fields(config)}
    if field_name not in field_meta:
        raise ConfigMutationError(f"unknown field: {field_name}")
    category = classify(field_name)
    if category is ReloadCategory.DESTRUCTIVE and not confirm:
        raise ConfigMutationError(f"'{field_name}' is destructive; include confirm=true to proceed")
    current = getattr(config, field_name)
    coerced = _coerce(current, new_value)
    setattr(config, field_name, coerced)
    log.info(
        "config.mutation",
        field=field_name,
        category=category.value,
        new_value=_to_json(coerced),
    )
    return category


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _to_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "as_posix"):  # pathlib.Path
        return value.as_posix()
    return value


def _type_hint(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, Enum):
        return "enum"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _enum_options(value: Any) -> list[str] | None:
    if isinstance(value, Enum):
        return [opt.value for opt in type(value)]
    return None


def _coerce(current: Any, new_value: Any) -> Any:
    """Coerce ``new_value`` to match the type of ``current``.

    Supports bool/int/float/str/Path/Enum. Enums accept their string value.
    Rejects None (fields aren't Optional in SystemConfig today).
    """
    if new_value is None:
        raise ConfigMutationError("null not allowed")
    if isinstance(current, Enum):
        enum_cls = type(current)
        if isinstance(new_value, enum_cls):
            return new_value
        try:
            return enum_cls(new_value)
        except ValueError as exc:
            raise ConfigMutationError(
                f"invalid enum value {new_value!r}; "
                f"expected one of {[o.value for o in enum_cls]}"
            ) from exc
    if isinstance(current, bool):
        if isinstance(new_value, bool):
            return new_value
        if isinstance(new_value, str):
            if new_value.lower() in ("true", "1"):
                return True
            if new_value.lower() in ("false", "0"):
                return False
        raise ConfigMutationError(f"cannot coerce {new_value!r} to bool")
    if isinstance(current, int) and not isinstance(current, bool):
        try:
            return int(new_value)
        except (TypeError, ValueError) as exc:
            raise ConfigMutationError(f"cannot coerce {new_value!r} to int") from exc
    if isinstance(current, float):
        try:
            return float(new_value)
        except (TypeError, ValueError) as exc:
            raise ConfigMutationError(f"cannot coerce {new_value!r} to float") from exc
    if isinstance(current, str):
        return str(new_value)
    if hasattr(current, "as_posix"):  # Path
        from pathlib import Path

        return Path(str(new_value))
    # Fallback — take as-is; caller is responsible for consistency.
    return new_value


_SENSITIVE_FIELD_NAMES: frozenset[str] = frozenset({"dashboard_token"})


def _is_sensitive(name: str) -> bool:
    return name in _SENSITIVE_FIELD_NAMES


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "…"
    return value[:4] + "…"


# Ensure the enums stay referenced so imports don't trip unused-import lint.
_ = PeerReviewMode, EmbeddingPreset
