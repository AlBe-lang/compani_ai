"""OpenAIProvider unit tests — Part 8 Stage 3-2½."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.errors import AdapterError
from adapters.openai_provider import OpenAIProvider
from domain.ports import LLMMessage
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


async def test_generate_returns_first_choice_content() -> None:
    session = _make_mock_session(
        status=200,
        json_body={"choices": [{"message": {"content": "answer"}}]},
    )
    provider = OpenAIProvider(api_key="sk-test", session=session)
    result = await provider.generate(
        "gpt-4o",
        [{"role": "user", "content": "hi"}],
    )
    assert result == "answer"


async def test_generate_forwards_messages_unchanged() -> None:
    session = _make_mock_session(
        status=200,
        json_body={"choices": [{"message": {"content": "ok"}}]},
    )
    provider = OpenAIProvider(api_key="sk-test", session=session)
    messages: list[LLMMessage] = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi"},
    ]
    await provider.generate("gpt-4o", messages)
    body = session.post.call_args.kwargs["json"]
    assert body["messages"] == messages


async def test_generate_empty_choices_raises() -> None:
    session = _make_mock_session(status=200, json_body={"choices": []})
    provider = OpenAIProvider(api_key="sk-test", session=session)
    with pytest.raises(AdapterError):
        await provider.generate("gpt-4o", [{"role": "user", "content": "hi"}])


async def test_generate_non_200_raises_adapter_error() -> None:
    session = _make_mock_session(status=429, text_body="rate limited")
    provider = OpenAIProvider(api_key="sk-test", session=session)
    with pytest.raises(AdapterError) as exc_info:
        await provider.generate("gpt-4o", [{"role": "user", "content": "hi"}])
    assert exc_info.value.code is ErrorCode.E_LLM_UNAVAILABLE


async def test_missing_api_key_raises_at_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(AdapterError):
        OpenAIProvider()
