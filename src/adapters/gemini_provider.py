"""Google Gemini API adapter — Part 8 Stage 3-2½.

One of three optional external providers alongside Anthropic (recommended)
and OpenAI. API key from ``GEMINI_API_KEY`` environment variable.

Gemini uses a distinct request schema: role values are "user" / "model"
(not "assistant"), messages are nested under ``contents[].parts[].text``,
and system prompts go in a separate ``systemInstruction`` field. We
translate the ``LLMMessage`` list at call time.

See https://ai.google.dev/api/generate-content for the full schema.
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

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_TIMEOUT_SEC = 300
_MAX_TIMEOUT_SEC = 300


class GeminiProvider:
    """LLMProvider implementation calling Google's Gemini generateContent API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _BASE_URL,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._api_key:
            raise AdapterError(
                ErrorCode.E_LLM_UNAVAILABLE,
                "GEMINI_API_KEY not set — provide api_key kwarg or export the env var",
            )
        self._base_url = base_url
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> GeminiProvider:
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
        """Generate chat completion via Gemini's generateContent endpoint."""
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

        system_text, contents = _translate_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        url = f"{self._base_url}/{model}:generateContent?key={self._api_key}"
        headers = {"content-type": "application/json"}

        log.info("gemini.call", model=model, timeout_sec=timeout_sec)
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise AdapterError(
                    ErrorCode.E_LLM_UNAVAILABLE,
                    f"gemini status={resp.status} body={body[:200]}",
                )
            data = await resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise AdapterError(
                    ErrorCode.E_LLM_UNAVAILABLE,
                    "gemini response had no candidates",
                )
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts)
            log.info("gemini.response", model=model)
            return text

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise AdapterError(
                ErrorCode.E_LLM_UNAVAILABLE,
                "GeminiProvider session not started — use 'async with' or inject a session",
            )
        return self._session


def _translate_messages(messages: list[LLMMessage]) -> tuple[str, list[dict[str, Any]]]:
    """Convert ``LLMMessage`` list to Gemini's ``contents`` format.

    Returns (system_prompt, contents). Role ``assistant`` becomes ``model``.
    """
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "system":
            system_parts.append(m["content"])
            continue
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": m["content"]}]})
    return "\n\n".join(system_parts), contents
