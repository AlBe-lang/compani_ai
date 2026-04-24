"""Anthropic Claude API adapter — Part 8 Stage 3-2½.

Primary recommended external provider (see Q7 decision, 개발 일지(3)).
Direct HTTP via aiohttp to keep dependency surface minimal and parallel
with OllamaProvider style. API key is read from ``ANTHROPIC_API_KEY``
environment variable; callers may also inject it explicitly for tests.

The Claude Messages API takes ``system`` as a top-level field rather than
a message with role=system, so we split incoming ``LLMMessage`` list at
construction time and forward accordingly.

See https://docs.anthropic.com/en/api/messages for the request schema.
"""

from __future__ import annotations

import os
from typing import Any

import aiohttp

from domain.ports import LLMMessage
from observability.error_codes import ErrorCode
from observability.logger import get_logger

from .errors import AdapterError

log = get_logger(__name__)

_BASE_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_TIMEOUT_SEC = 300
_MAX_TIMEOUT_SEC = 300


class AnthropicProvider:
    """LLMProvider implementation calling Anthropic's Messages API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _BASE_URL,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self._api_key:
            raise AdapterError(
                ErrorCode.E_LLM_UNAVAILABLE,
                "ANTHROPIC_API_KEY not set — provide api_key kwarg or export the env var",
            )
        self._base_url = base_url
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> AnthropicProvider:
        if self._owns_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def generate(
        self,
        model: str,
        messages: list[LLMMessage],
        **kwargs: object,
    ) -> str:
        """Generate chat completion via Anthropic Messages API."""
        session = self._require_session()
        raw_temp = kwargs.get("temperature", 0.3)
        raw_tokens = kwargs.get("max_tokens", 4096)
        raw_timeout = kwargs.get("timeout_sec", _DEFAULT_TIMEOUT_SEC)
        temperature = raw_temp if isinstance(raw_temp, float) else float(str(raw_temp))
        max_tokens = raw_tokens if isinstance(raw_tokens, int) else int(str(raw_tokens))
        timeout_sec = min(
            (
                float(raw_timeout)
                if isinstance(raw_timeout, (int, float))
                else float(str(raw_timeout))
            ),
            float(_MAX_TIMEOUT_SEC),
        )

        system_text, conversation = _split_system(messages)
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": conversation,
        }
        if system_text:
            payload["system"] = system_text

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        log.info("anthropic.call", model=model, timeout_sec=timeout_sec)
        async with session.post(
            self._base_url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise AdapterError(
                    ErrorCode.E_LLM_UNAVAILABLE,
                    f"anthropic status={resp.status} body={body[:200]}",
                )
            data = await resp.json()
            # content is a list of blocks; we concatenate text blocks.
            blocks = data.get("content", [])
            text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            log.info("anthropic.response", model=model)
            return "".join(text_parts)

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise AdapterError(
                ErrorCode.E_LLM_UNAVAILABLE,
                "AnthropicProvider session not started — use 'async with' or inject a session",
            )
        return self._session


def _split_system(messages: list[LLMMessage]) -> tuple[str, list[LLMMessage]]:
    """Separate system messages (joined with blank lines) from the chat turns."""
    system_parts: list[str] = []
    conversation: list[LLMMessage] = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            conversation.append(m)
    return "\n\n".join(system_parts), conversation
