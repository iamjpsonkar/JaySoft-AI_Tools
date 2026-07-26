"""jsat._ai — AIProvider ABC and factory."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator


class AIProvider(ABC):
    """Contract all AI/LLM backends must implement."""

    @abstractmethod
    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str: ...

    @abstractmethod
    async def complete_async(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str: ...

    @abstractmethod
    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]: ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    def is_available(self) -> bool:
        return True


def get_ai_provider(cfg: Any) -> AIProvider:
    """Factory: returns the right AIProvider based on cfg.ai.provider."""
    import structlog
    log = structlog.get_logger(__name__)

    provider_name: str = getattr(getattr(cfg, "ai", None), "provider", "none") or "none"
    log.info("ai_provider_factory", provider=provider_name)

    if provider_name == "none":
        from jsat._ai.none import NoOpProvider
        return NoOpProvider()

    if provider_name == "claude_cli":
        from jsat._ai.claude_cli import ClaudeCliProvider
        return ClaudeCliProvider(cfg)

    if provider_name == "bob_cli":
        from jsat._ai.bob_cli import BobCliProvider
        return BobCliProvider(cfg)

    if provider_name == "ollama":
        try:
            from jsat._ai.ollama import OllamaProvider
            return OllamaProvider(cfg)
        except ImportError as e:
            _profile_error("ollama", "local", e)

    if provider_name == "anthropic":
        try:
            from jsat._ai.anthropic import AnthropicProvider  # type: ignore[import]
            return AnthropicProvider(cfg)
        except ImportError as e:
            _profile_error("anthropic", "anthropic", e)

    if provider_name == "openai":
        try:
            from jsat._ai.openai import OpenAIProvider  # type: ignore[import]
            return OpenAIProvider(cfg)
        except ImportError as e:
            _profile_error("openai", "openai", e)

    if provider_name == "openai_compat":
        try:
            from jsat._ai.openai_compat import OpenAICompatProvider  # type: ignore[import]
            return OpenAICompatProvider(cfg)
        except ImportError as e:
            _profile_error("openai_compat", "openai", e)

    raise ValueError(
        f"Unknown ai.provider '{provider_name}'. "
        "Valid: none, claude_cli, bob_cli, ollama, anthropic, openai, openai_compat. "
        "Run: jsat init --profile solo"
    )


def _profile_error(provider: str, extra: str, cause: ImportError) -> None:
    import structlog
    structlog.get_logger(__name__).error(
        "ai_provider_import_failed", provider=provider, extra=extra, error=str(cause)
    )
    try:
        from jsat._exceptions import ProfileError
        raise ProfileError(
            f"AI provider '{provider}' requires jsat[{extra}].\n"
            f"Install: pip install 'jsat[{extra}]'"
        ) from cause
    except ImportError:
        raise ImportError(f"Install: pip install 'jsat[{extra}]'") from cause


__all__ = ["AIProvider", "get_ai_provider"]
