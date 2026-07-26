"""jsat._ai.none — No-op AIProvider for CI mode."""
from __future__ import annotations

from collections.abc import Iterator

from jsat._ai import AIProvider

_warned = False
_MSG = (
    "No AI provider configured. "
    "Set ai.provider in .jsat.yaml or run: jsat init --profile solo"
)


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    import structlog
    structlog.get_logger(__name__).warning("noop_ai_provider_active", message=_MSG)


def _ai_error() -> type[Exception]:
    try:
        from jsat._exceptions import AIError
        return AIError
    except ImportError:
        return RuntimeError


class NoOpProvider(AIProvider):
    """No-op provider — raises AIError on every call. Used in CI mode."""

    @property
    def provider_name(self) -> str:
        return "none"

    @property
    def model_name(self) -> str:
        return "none"

    def is_available(self) -> bool:
        return False

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        _warn_once()
        raise _ai_error()(_MSG)

    async def complete_async(
        self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1
    ) -> str:
        _warn_once()
        raise _ai_error()(_MSG)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        _warn_once()
        return
        yield


__all__ = ["NoOpProvider"]
