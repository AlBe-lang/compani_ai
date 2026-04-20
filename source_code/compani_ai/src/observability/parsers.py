"""Helpers for parsing model responses into strict JSON payloads."""

from __future__ import annotations

import json
import re
from typing import Any

from observability.error_codes import ErrorCode

_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_PLAIN_FENCE_RE = re.compile(r"```\s*(.*?)\s*```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


class ParseResponseError(ValueError):
    """Raised when a model response cannot be parsed into valid JSON."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def parse_json_response(text: str) -> dict[str, object]:
    """Parse a model response and return a JSON object payload."""
    candidate = _extract_candidate(text)
    if not candidate:
        raise ParseResponseError(ErrorCode.E_PARSE_EMPTY, "empty response body")

    for attempt in _recovery_candidates(candidate):
        parsed = _parse_object(attempt)
        if parsed is not None:
            return parsed

    repaired = _repair_with_json_repair(candidate)
    if repaired is not None:
        parsed = _parse_object(repaired)
        if parsed is not None:
            return parsed

    raise ParseResponseError(ErrorCode.E_PARSE_JSON, "invalid JSON response")


def _extract_candidate(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""

    json_match = _JSON_FENCE_RE.search(stripped)
    if json_match:
        return json_match.group(1).strip()

    plain_match = _PLAIN_FENCE_RE.search(stripped)
    if plain_match:
        return plain_match.group(1).strip()

    return stripped


def _recovery_candidates(candidate: str) -> list[str]:
    attempts: list[str] = []

    def add(value: str | None) -> None:
        if value is None:
            return
        normalized = value.strip()
        if normalized and normalized not in attempts:
            attempts.append(normalized)

    add(candidate)
    sliced = _slice_first_object(candidate)
    add(sliced)
    add(_remove_trailing_commas(sliced or candidate))
    add(_append_missing_closers(sliced or candidate))
    add(_append_missing_closers(_remove_trailing_commas(sliced or candidate)))
    return attempts


def _parse_object(text: str) -> dict[str, object] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _slice_first_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    end = text.rfind("}")
    if end < start:
        return text[start:]
    return text[start : end + 1]


def _remove_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _append_missing_closers(text: str) -> str:
    missing_brackets = max(0, text.count("[") - text.count("]"))
    missing_braces = max(0, text.count("{") - text.count("}"))
    return text + ("]" * missing_brackets) + ("}" * missing_braces)


def _repair_with_json_repair(candidate: str) -> str | None:
    try:
        from json_repair import repair_json
    except ImportError:
        return None

    try:
        repaired: str | dict[str, Any] = repair_json(candidate)
    except TypeError:
        try:
            repaired = repair_json(candidate, return_objects=False)
        except Exception:
            return None
    except Exception:
        return None

    if isinstance(repaired, str):
        return repaired.strip()

    try:
        return json.dumps(repaired, ensure_ascii=False)
    except TypeError:
        return None
