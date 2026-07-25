"""jsat._ai.openai — OpenAI AI provider (jsat[openai] extra)."""
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Iterator

from jsat._ai import AIProvider
from jsat._exceptions import AIAuthError, AIRateLimitError, AITimeoutError, ProfileError

if TYPE_CHECKING:
    from jsat._models import JSATConfig


class OpenAIProvider(AIProvider):
    """AI provider backed by the OpenAI SDK."""

    def __init__(self, cfg: JSATConfig) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)
        try:
            import openai as _openai
            self._openai = _openai
        except ImportError as e:
            raise ProfileError(
                "OpenAI SDK not installed.\nInstall: pip install 'jsat[openai]'",
                required_extra="openai",
            ) from e

        api_key_env = cfg.ai.api_key_env or "OPENAI_API_KEY"
        self._model: str = cfg.ai.model or "gpt-4o"
        self._client = self._openai.OpenAI(api_key=os.environ.get(api_key_env))
        self._log.info("openai_init", model=self._model,
                       api_key_set=bool(os.environ.get(api_key_env)))

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        self._log.debug("openai_complete", prompt_len=len(prompt), max_tokens=max_tokens)
        t0 = time.monotonic()
        try:
            resp = self._client.chat.completions.create(
                model=self._model, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        except self._openai.RateLimitError as e:
            raise AIRateLimitError("OpenAI rate limit", provider="openai") from e
        except self._openai.AuthenticationError as e:
            raise AIAuthError(provider="openai") from e
        except self._openai.APITimeoutError as e:
            raise AITimeoutError("OpenAI timeout", provider="openai", timeout_seconds=120) from e
        elapsed = round((time.monotonic() - t0) * 1000)
        text: str = resp.choices[0].message.content or ""
        self._log.info("openai_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        for chunk in self._client.chat.completions.create(
            model=self._model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}], stream=True,
        ):
            piece = chunk.choices[0].delta.content
            if piece:
                yield piece

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:
            return False
