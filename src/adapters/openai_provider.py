"""OpenAI Chat Completions API adapter — Part 8 Stage 3-2½.

One of three optional external providers alongside Anthropic (recommended)
and Gemini. API key from ``OPENAI_API_KEY`` environment variable.

See https://platform.openai.com/docs/api-reference/chat for the schema.
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

_BASE_URL = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SEC = 300
_MAX_TIMEOUT_SEC = 300


class OpenAIProvider:
    """LLMProvider implementation calling OpenAI's chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _BASE_URL,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self._api_key:
            raise AdapterError(
                ErrorCode.E_LLM_UNAVAILABLE,
                "OPENAI_API_KEY not set — provide api_key kwarg or export the env var",
            )
        self._base_url = base_url
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> OpenAIProvider:
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
        """Generate chat completion via OpenAI /v1/chat/completions."""
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

        # OpenAI accepts LLMMessage shape as-is (role/content), so no
        # translation is required — unlike Anthropic and Gemini.
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

        log.info("openai.call", model=model, timeout_sec=timeout_sec)
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
                    f"openai status={resp.status} body={body[:200]}",
                )
            data = await resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise AdapterError(
                    ErrorCode.E_LLM_UNAVAILABLE,
                    "openai response had no choices",
                )
            content: str = choices[0].get("message", {}).get("content", "")
            log.info("openai.response", model=model)
            return content

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise AdapterError(
                ErrorCode.E_LLM_UNAVAILABLE,
                "OpenAIProvider session not started — use 'async with' or inject a session",
            )
        return self._session
