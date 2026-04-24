"""AnthropicProvider unit tests — Part 8 Stage 3-2½."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.anthropic_provider import AnthropicProvider
from adapters.errors import AdapterError
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


async def test_generate_success_joins_text_blocks() -> None:
    session = _make_mock_session(
        status=200,
        json_body={
            "content": [
                {"type": "text", "text": "hello "},
                {"type": "text", "text": "world"},
            ],
        },
    )
    provider = AnthropicProvider(api_key="sk-test", session=session)
    result = await provider.generate(
        "claude-opus-4-7",
        [{"role": "user", "content": "hi"}],
    )
    assert result == "hello world"


async def test_generate_splits_system_messages_from_conversation() -> None:
    session = _make_mock_session(
        status=200,
        json_body={"content": [{"type": "text", "text": "ok"}]},
    )
    provider = AnthropicProvider(api_key="sk-test", session=session)
    await provider.generate(
        "claude-opus-4-7",
        [
            {"role": "system", "content": "you are a CTO"},
            {"role": "system", "content": "be concise"},
            {"role": "user", "content": "what?"},
        ],
    )
    call_kwargs = session.post.call_args.kwargs
    body = call_kwargs["json"]
    assert body["system"] == "you are a CTO\n\nbe concise"
    assert body["messages"] == [{"role": "user", "content": "what?"}]


async def test_generate_non_200_raises_adapter_error() -> None:
    session = _make_mock_session(status=401, text_body="invalid api key")
    provider = AnthropicProvider(api_key="sk-bad", session=session)
    with pytest.raises(AdapterError) as exc_info:
        await provider.generate("claude-opus-4-7", [{"role": "user", "content": "hi"}])
    assert exc_info.value.code is ErrorCode.E_LLM_UNAVAILABLE


async def test_missing_api_key_raises_at_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(AdapterError) as exc_info:
        AnthropicProvider()
    assert exc_info.value.code is ErrorCode.E_LLM_UNAVAILABLE


async def test_generate_without_session_raises() -> None:
    provider = AnthropicProvider(api_key="sk-test")
    with pytest.raises(AdapterError) as exc_info:
        await provider.generate("claude-opus-4-7", [{"role": "user", "content": "hi"}])
    assert exc_info.value.code is ErrorCode.E_LLM_UNAVAILABLE
