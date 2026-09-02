"""jsat._ai.anthropic — Anthropic/Claude AI provider (jsat[anthropic] extra)."""
from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from jsat._ai import AIProvider
from jsat._exceptions import (
    AIAuthError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
    ProfileError,
)

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

        self._model: str | None = cfg.ai.model
        api_key_env = cfg.ai.api_key_env or "ANTHROPIC_API_KEY"
        try:
            self._client = self._anthropic.Anthropic(api_key=os.environ.get(api_key_env))
        except Exception as e:
            self._log.error("anthropic_client_init_failed", error=str(e))
            raise AIAuthError(provider="anthropic") from e
        self._log.info("anthropic_init", model=self._model,
                       api_key_set=bool(os.environ.get(api_key_env)))

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model or "not selected"

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        self._log.debug("anthropic_complete", prompt_len=len(prompt), max_tokens=max_tokens)
        t0 = time.monotonic()
        try:
            from jsat._ai import require_explicit_model

            # `temperature` is deliberately NOT sent. Sampling parameters were
            # removed from the Messages API on the current models (Opus 5,
            # Opus 4.7/4.8, Sonnet 5, Fable 5/5.1 all return 400), and the
            # 1.x SDK dropped the keyword outright — passing it raised
            # `TypeError: Messages.create() got an unexpected keyword
            # argument 'temperature'`, so this provider failed on every
            # single call regardless of the key. The parameter stays in the
            # signature because the AIProvider interface defines it and the
            # other providers still honour it.
            resp = self._client.messages.create(
                model=require_explicit_model("anthropic", self._model),
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        except self._anthropic.RateLimitError as e:
            raise AIRateLimitError("Anthropic rate limit", provider="anthropic") from e
        except self._anthropic.AuthenticationError as e:
            raise AIAuthError(provider="anthropic") from e
        except self._anthropic.APITimeoutError as e:
            raise AITimeoutError("Anthropic timeout", provider="anthropic",
                                  timeout_seconds=120) from e
        except self._anthropic.APIConnectionError as e:
            raise AIProviderError(
                f"Anthropic connection error: {e}", provider="anthropic", status_code=0
            ) from e
        except self._anthropic.APIStatusError as e:
            raise AIProviderError(
                f"Anthropic API error: {e}", provider="anthropic",
                status_code=getattr(e, "status_code", 0) or 0,
            ) from e
        except TypeError as e:
            # The 1.x SDK raises a bare TypeError for two very different
            # things, and neither is caught by the SDK's own exception types:
            #
            #   * missing credentials — "Could not resolve authentication
            #     method" is raised before any HTTP request, so
            #     `except AuthenticationError` never sees it;
            #   * a request parameter this SDK version does not accept.
            #
            # Both used to escape untyped, crashing callers that catch AIError
            # to degrade. Classify and re-raise in jsat's family.
            message = str(e)
            lowered = message.lower()
            if "unexpected keyword argument" in lowered:
                version = getattr(self._anthropic, "__version__", "unknown")
                raise AIProviderError(
                    f"Anthropic SDK {version} rejected a request parameter: "
                    f"{message}. Upgrade jsat, or pin an SDK version it "
                    "supports.",
                    provider="anthropic", status_code=0,
                ) from e
            if any(t in lowered for t in
                   ("authentication", "api_key", "auth_token", "credentials")):
                raise AIAuthError(provider="anthropic") from e
            raise AIProviderError(
                f"Anthropic SDK call failed: {message}",
                provider="anthropic", status_code=0,
            ) from e
        elapsed = round((time.monotonic() - t0) * 1000)
        # content[] holds mixed blocks (text, thinking, tool_use, ...) and
        # thinking is on by default on current models, so the first block is
        # frequently NOT the answer. Indexing [0] raised AttributeError on a
        # thinking block; take the text blocks and join them.
        text = "".join(
            getattr(b, "text", "") for b in resp.content
            if getattr(b, "type", None) == "text"
        )
        if not text:
            raise AIProviderError(
                "Anthropic returned no text block "
                f"(stop_reason={getattr(resp, 'stop_reason', None)!r}, "
                f"blocks={[getattr(b, 'type', '?') for b in resp.content]})",
                provider="anthropic", status_code=0,
            )
        self._log.info("anthropic_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(
        self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1
    ) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        from jsat._ai import require_explicit_model

        with self._client.messages.stream(
            model=require_explicit_model("anthropic", self._model), max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as s:
            yield from s.text_stream

    def is_available(self) -> bool:
        try:
            self._client.models.list()
            return True
        except Exception:
            return False
