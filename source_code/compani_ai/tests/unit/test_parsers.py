from __future__ import annotations

import pytest

from observability.error_codes import ErrorCode
from observability.parsers import ParseResponseError, parse_json_response


def test_parse_json_response_extracts_json_fence() -> None:
    raw = '```json\n{"project_name":"Todo","constraints":["local"]}\n```'

    payload = parse_json_response(raw)

    assert payload["project_name"] == "Todo"
    assert payload["constraints"] == ["local"]


def test_parse_json_response_extracts_plain_fence() -> None:
    raw = '```\n{"decision":"continue","reason":"done"}\n```'

    payload = parse_json_response(raw)

    assert payload["decision"] == "continue"


def test_parse_json_response_recovers_partial_json() -> None:
    raw = '{"project_name":"Todo","description":"Task app","constraints":["local"]'

    payload = parse_json_response(raw)

    assert payload["project_name"] == "Todo"
    assert payload["description"] == "Task app"


def test_parse_json_response_raises_empty_error() -> None:
    with pytest.raises(ParseResponseError) as exc_info:
        parse_json_response("   ")

    assert exc_info.value.code is ErrorCode.E_PARSE_EMPTY


def test_parse_json_response_raises_parse_json_error() -> None:
    with pytest.raises(ParseResponseError) as exc_info:
        parse_json_response("this is not json")

    assert exc_info.value.code is ErrorCode.E_PARSE_JSON
