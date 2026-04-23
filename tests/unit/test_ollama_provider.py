from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adapters.errors import AdapterError
from adapters.ollama_provider import OllamaProvider
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
    session.get = MagicMock(return_value=mock_cm)
    return session


async def test_generate_success() -> None:
    session = _make_mock_session(
        status=200,
        json_body={"message": {"content": "here is your code"}},
    )
    provider = OllamaProvider(session=session)
    result = await provider.generate(
        "llama3.2:3b",
        [{"role": "user", "content": "write hello world"}],
    )
    assert result == "here is your code"


async def test_generate_non_200_raises_adapter_error() -> None:
    session = _make_mock_session(status=503, text_body="service unavailable")
    provider = OllamaProvider(session=session)
    with pytest.raises(AdapterError) as exc_info:
        await provider.generate("llama3.2:3b", [{"role": "user", "content": "hi"}])
    assert exc_info.value.code is ErrorCode.E_LLM_UNAVAILABLE


async def test_generate_passes_model_and_options() -> None:
    session = _make_mock_session(
        status=200,
        json_body={"message": {"content": "ok"}},
    )
    provider = OllamaProvider(session=session)
    await provider.generate(
        "phi3.5",
        [{"role": "user", "content": "hi"}],
        temperature=0.1,
        max_tokens=2048,
    )
    call_kwargs = session.post.call_args
    payload = call_kwargs.kwargs["json"]
    assert payload["model"] == "phi3.5"
    assert payload["options"]["temperature"] == 0.1
    assert payload["options"]["num_predict"] == 2048
    assert payload["stream"] is False


async def test_health_check_returns_true_when_models_present() -> None:
    session = _make_mock_session(
        status=200,
        json_body={"models": [{"name": "llama3.2:3b"}]},
    )
    provider = OllamaProvider(session=session)
    assert await provider.health_check() is True


async def test_health_check_returns_false_when_no_models() -> None:
    session = _make_mock_session(status=200, json_body={"models": []})
    provider = OllamaProvider(session=session)
    assert await provider.health_check() is False


async def test_health_check_returns_false_on_non_200() -> None:
    session = _make_mock_session(status=500)
    provider = OllamaProvider(session=session)
    assert await provider.health_check() is False


async def test_health_check_returns_false_on_exception() -> None:
    session = MagicMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=mock_cm)

    provider = OllamaProvider(session=session)
    assert await provider.health_check() is False


async def test_generate_without_session_raises_adapter_error() -> None:
    provider = OllamaProvider()
    with pytest.raises(AdapterError) as exc_info:
        await provider.generate("llama3.2:3b", [{"role": "user", "content": "hi"}])
    assert exc_info.value.code is ErrorCode.E_LLM_UNAVAILABLE
