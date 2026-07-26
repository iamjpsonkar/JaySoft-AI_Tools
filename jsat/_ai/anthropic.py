"""jsat._ai.anthropic — Anthropic/Claude AI provider (jsat[anthropic] extra)."""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from jsat._ai import AIProvider
from jsat._exceptions import AIAuthError, AIRateLimitError, AITimeoutError, ProfileError

if TYPE_CHECKING:
    from jsat._models import JSATConfig


class AnthropicProvider(AIProvider):
    """AI provider backed by the Anthropic SDK."""

    def __init__(self, cfg: JSATConfig) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)
        try:
            import anthropic as _anthropic
            self._anthropic = _anthropic
        except ImportError as e:
            raise ProfileError(
                "Anthropic SDK not installed.\nInstall: pip install 'jsat[anthropic]'",
                required_extra="anthropic",
            ) from e

        self._model: str = cfg.ai.model or "claude-sonnet-4-6"
        api_key_env = cfg.ai.api_key_env or "ANTHROPIC_API_KEY"
        self._client = self._anthropic.Anthropic(api_key=os.environ.get(api_key_env))
        self._log.info("anthropic_init", model=self._model,
                       api_key_set=bool(os.environ.get(api_key_env)))

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        self._log.debug("anthropic_complete", prompt_len=len(prompt), max_tokens=max_tokens)
        t0 = time.monotonic()
        try:
            resp = self._client.messages.create(
                model=self._model, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        except self._anthropic.RateLimitError as e:
            raise AIRateLimitError("Anthropic rate limit", provider="anthropic") from e
        except self._anthropic.AuthenticationError as e:
            raise AIAuthError(provider="anthropic") from e
        except self._anthropic.APITimeoutError as e:
            raise AITimeoutError("Anthropic timeout", provider="anthropic",
                                  timeout_seconds=120) from e
        elapsed = round((time.monotonic() - t0) * 1000)
        text: str = resp.content[0].text
        self._log.info("anthropic_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(
        self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1
    ) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        with self._client.messages.stream(
            model=self._model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as s:
            yield from s.text_stream

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:
            return False
