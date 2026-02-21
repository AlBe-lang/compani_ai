"""Centralized error code catalog."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    # LLM
    E_LLM_TIMEOUT = "E-LLM-TIMEOUT"
    E_LLM_UNAVAILABLE = "E-LLM-UNAVAILABLE"
    E_LLM_MODEL_MISSING = "E-LLM-MODEL-MISSING"

    # Parsing
    E_PARSE_JSON = "E-PARSE-JSON"
    E_PARSE_SCHEMA = "E-PARSE-SCHEMA"
    # Model response existed but became empty after code-fence cleanup/trimming.
    E_PARSE_EMPTY = "E-PARSE-EMPTY"

    # Dependencies / workspace
    E_DEPS_BLOCKED = "E-DEPS-BLOCKED"
    E_DEPS_DEADLOCK = "E-DEPS-DEADLOCK"
    E_DEPS_TIMEOUT = "E-DEPS-TIMEOUT"

    # Messaging
    E_MSG_TIMEOUT = "E-MSG-TIMEOUT"
    E_MSG_NO_RESPONDER = "E-MSG-NO-RESPONDER"

    # Storage
    E_STORAGE_READ = "E-STORAGE-READ"
    E_STORAGE_WRITE = "E-STORAGE-WRITE"
    E_STORAGE_QUERY = "E-STORAGE-QUERY"

    # System
    E_SYSTEM_CONFIG = "E-SYSTEM-CONFIG"
    E_SYSTEM_OOM = "E-SYSTEM-OOM"
    E_SYSTEM_UNKNOWN = "E-SYSTEM-UNKNOWN"
