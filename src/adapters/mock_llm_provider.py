"""Mock implementation of LLMProvider for tests."""

from __future__ import annotations

from domain.ports import LLMMessage


class MockLLMProvider:
    """Return preconfigured responses without external calls."""

    def __init__(
        self,
        response: str = '{"ok": true}',
        responses: list[str] | None = None,
    ) -> None:
        self._responses = responses[:] if responses else [response]
        self._cursor = 0
        self.calls: list[dict[str, object]] = []

    async def generate(
        self,
        model: str,
        messages: list[LLMMessage],
        **kwargs: object,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        index = min(self._cursor, len(self._responses) - 1)
        self._cursor += 1
        return self._responses[index]
