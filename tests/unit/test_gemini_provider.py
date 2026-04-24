"""GeminiProvider unit tests — Part 8 Stage 3-2½."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.errors import AdapterError
from adapters.gemini_provider import GeminiProvider
from observability.error_codes import ErrorCode


def _make_mock_session(
    status: int = 200, json_body: object = None, text_body: str = ""
) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_body or {})
    mock_resp.text = AsyncMock(return_value=text_body)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=mock_cm)
    return session


async def test_generate_joins_parts() -> None:
    session = _make_mock_session(
        status=200,
        json_body={
            "candidates": [
                {"content": {"parts": [{"text": "hello "}, {"text": "world"}]}},
            ],
        },
    )
    provider = GeminiProvider(api_key="key-test", session=session)
    result = await provider.generate(
        "gemini-2.0-flash",
        [{"role": "user", "content": "hi"}],
    )
    assert result == "hello world"


async def test_generate_translates_roles_and_system_prompt() -> None:
    session = _make_mock_session(
        status=200,
        json_body={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
    )
    provider = GeminiProvider(api_key="key-test", session=session)
    await provider.generate(
        "gemini-2.0-flash",
        [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "prior"},
            {"role": "user", "content": "followup"},
        ],
    )
    body = session.post.call_args.kwargs["json"]
    assert body["systemInstruction"] == {"parts": [{"text": "rules"}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "q"}]},
        {"role": "model", "parts": [{"text": "prior"}]},
        {"role": "user", "parts": [{"text": "followup"}]},
    ]


async def test_generate_empty_candidates_raises() -> None:
    session = _make_mock_session(status=200, json_body={"candidates": []})
    provider = GeminiProvider(api_key="key-test", session=session)
    with pytest.raises(AdapterError):
        await provider.generate("gemini-2.0-flash", [{"role": "user", "content": "hi"}])


async def test_generate_non_200_raises_adapter_error() -> None:
    session = _make_mock_session(status=400, text_body="bad request")
    provider = GeminiProvider(api_key="key-test", session=session)
    with pytest.raises(AdapterError) as exc_info:
        await provider.generate("gemini-2.0-flash", [{"role": "user", "content": "hi"}])
    assert exc_info.value.code is ErrorCode.E_LLM_UNAVAILABLE


async def test_missing_api_key_raises_at_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(AdapterError):
        GeminiProvider()
