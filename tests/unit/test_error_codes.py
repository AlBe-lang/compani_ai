from __future__ import annotations

from observability.error_codes import ErrorCode


def test_error_codes_have_expected_prefix() -> None:
    for code in ErrorCode:
        assert code.value.startswith("E-")

