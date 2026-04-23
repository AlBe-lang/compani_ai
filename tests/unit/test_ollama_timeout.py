"""Unit tests for OllamaProvider.generate timeout_sec kwarg — Part 8 Stage 1 (R-07C)."""

from __future__ import annotations

import aiohttp

from adapters.ollama_provider import _MAX_TIMEOUT_SEC, OllamaProvider


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.status = 200

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def json(self) -> dict[str, object]:
        return self._payload

    async def text(self) -> str:
        return ""


class _FakeSession:
    """Capture the ClientTimeout passed to session.post."""

    def __init__(self) -> None:
        self.last_timeout: aiohttp.ClientTimeout | None = None
        self.last_payload: dict[str, object] | None = None

    def post(
        self,
        url: str,
        json: dict[str, object] | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> _FakeResponse:
        self.last_timeout = timeout
        self.last_payload = json
        return _FakeResponse({"message": {"content": "ok"}})


async def test_default_timeout_used_when_not_specified() -> None:
    session = _FakeSession()
    provider = OllamaProvider(session=session)  # type: ignore[arg-type]
    await provider.generate(model="test", messages=[{"role": "user", "content": "hi"}])
    assert session.last_timeout is not None
    assert session.last_timeout.total == 300.0  # _TIMEOUT_SEC default


async def test_timeout_sec_kwarg_applied() -> None:
    session = _FakeSession()
    provider = OllamaProvider(session=session)  # type: ignore[arg-type]
    await provider.generate(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
        timeout_sec=45,
    )
    assert session.last_timeout is not None
    assert session.last_timeout.total == 45.0


async def test_timeout_sec_capped_at_infrastructure_rule_limit() -> None:
    """I-02 (04_INFRASTRUCTURE_RULES.md): timeout must not exceed 300s.
    Any request for > 300s is silently capped."""
    session = _FakeSession()
    provider = OllamaProvider(session=session)  # type: ignore[arg-type]
    await provider.generate(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
        timeout_sec=9999,
    )
    assert session.last_timeout is not None
    assert session.last_timeout.total == float(_MAX_TIMEOUT_SEC)
    assert session.last_timeout.total == 300.0


async def test_timeout_sec_accepts_float() -> None:
    session = _FakeSession()
    provider = OllamaProvider(session=session)  # type: ignore[arg-type]
    await provider.generate(
        model="test",
        messages=[{"role": "user", "content": "hi"}],
        timeout_sec=12.5,
    )
    assert session.last_timeout is not None
    assert session.last_timeout.total == 12.5
