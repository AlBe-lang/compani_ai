"""Ollama HTTP API adapter."""

from __future__ import annotations

from typing import Any

import aiohttp

from domain.ports import LLMMessage
from observability.error_codes import ErrorCode
from observability.logger import get_logger

from .errors import AdapterError

log = get_logger(__name__)

_BASE_URL = "http://localhost:11434"
# Default generate timeout (seconds). Callers can override via ``timeout_sec``
# kwarg to ``generate()``. Hard-capped at _MAX_TIMEOUT_SEC to respect
# 04_INFRASTRUCTURE_RULES.md I-02 ("300초 이상 금지, 메모리 고갈 위험").
_TIMEOUT_SEC = 300
_MAX_TIMEOUT_SEC = 300
_HEALTH_TIMEOUT_SEC = 5


class OllamaProvider:
    """LLMProvider implementation calling Ollama's /api/chat endpoint."""

    def __init__(
        self,
        base_url: str = _BASE_URL,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> OllamaProvider:
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
        """Generate chat completion. Part 8 Stage 1 (R-07C) added native
        ``timeout_sec`` kwarg — callers can control per-call timeout instead
        of wrapping with ``asyncio.wait_for`` externally. Hard-capped at
        300초 per 04_INFRASTRUCTURE_RULES.md I-02 (OOM 방지).
        """
        session = self._require_session()
        raw_temp = kwargs.get("temperature", 0.3)
        raw_tokens = kwargs.get("max_tokens", 4096)
        raw_timeout = kwargs.get("timeout_sec", _TIMEOUT_SEC)
        temperature = raw_temp if isinstance(raw_temp, float) else float(str(raw_temp))
        max_tokens = raw_tokens if isinstance(raw_tokens, int) else int(str(raw_tokens))
        timeout_sec = (
            raw_timeout if isinstance(raw_timeout, (int, float)) else float(str(raw_timeout))
        )
        # I-02 준수: 사용자가 300초 이상 요청해도 300으로 상한
        timeout_sec = min(float(timeout_sec), float(_MAX_TIMEOUT_SEC))
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        log.info("ollama.call", model=model, timeout_sec=timeout_sec)
        async with session.post(
            f"{self._base_url}/api/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise AdapterError(
                    ErrorCode.E_LLM_UNAVAILABLE,
                    f"ollama status={resp.status} body={body[:200]}",
                )
            data = await resp.json()
            content: str = data["message"]["content"]
            log.info("ollama.response", model=model)
            return content

    async def health_check(self) -> bool:
        """Return True if Ollama is reachable and has at least one model loaded."""
        session = self._require_session()
        try:
            async with session.get(
                f"{self._base_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=_HEALTH_TIMEOUT_SEC),
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                return len(data.get("models", [])) > 0
        except Exception:
            return False

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise AdapterError(
                ErrorCode.E_LLM_UNAVAILABLE,
                "OllamaProvider session not started — use 'async with' or inject a session",
            )
        return self._session
