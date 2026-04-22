"""Adapter-layer error contract."""

from __future__ import annotations

from domain.contracts.error_codes import ErrorCode


class AdapterError(RuntimeError):
    """Infrastructure / adapter error with classified code."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
