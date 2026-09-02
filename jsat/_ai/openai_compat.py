"""jsat._ai.openai_compat — Any OpenAI-compatible endpoint (LM Studio, vLLM, etc.)."""
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
)

if TYPE_CHECKING:
    from jsat._models import JSATConfig


def _as_jsat_error(exc: Exception, base_url: str) -> Exception:
    """Translate an SDK or HTTP failure into jsat's typed AI error family.

    OpenAI-compatible endpoints are arbitrary third-party servers, so the
    failure could come from the `openai` SDK, from httpx, or from a JSON body
    that does not match the schema. Whatever the source, the caller needs one
    of jsat's types to decide whether to retry, re-auth, or degrade.
    """
    name = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None) or 0
    if status in (401, 403) or "Authentication" in name or "PermissionDenied" in name:
        return AIAuthError(provider="openai_compat")
    if status == 429 or "RateLimit" in name:
        return AIRateLimitError("OpenAI-compatible endpoint rate limit",
                                provider="openai_compat")
    if "Timeout" in name:
        return AITimeoutError("OpenAI-compatible endpoint timed out",
                              provider="openai_compat", timeout_seconds=120)
    if "Connection" in name:
        return AIProviderError(
            f"Cannot reach the OpenAI-compatible endpoint at {base_url}: {exc}",
            provider="openai_compat", status_code=0,
        )
    return AIProviderError(
        f"OpenAI-compatible endpoint error ({name}): {exc}",
        provider="openai_compat", status_code=status,
    )


class OpenAICompatProvider(AIProvider):
    """Works with any OpenAI-compatible endpoint. Uses openai SDK or httpx fallback."""

    def __init__(self, cfg: JSATConfig) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        self._base_url: str = cfg.ai.base_url or "http://localhost:1234/v1"
        api_key_env = cfg.ai.api_key_env or "OPENAI_API_KEY"
        self._api_key: str = os.environ.get(api_key_env) or "not-needed"
        self._model: str | None = cfg.ai.model

        try:
            import openai as _openai
            self._openai = _openai
            self._client = _openai.OpenAI(base_url=self._base_url, api_key=self._api_key)
        except ImportError:
            self._openai = None  # type: ignore[assignment]
            self._client = None  # type: ignore[assignment]

        self._log.info("openai_compat_init", model=self._model, base_url=self._base_url,
                       sdk_available=self._client is not None)

    @property
    def provider_name(self) -> str:
        return "openai_compat"

    @property
    def model_name(self) -> str:
        return self._model or "not selected"

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        from jsat._ai import require_explicit_model

        model = require_explicit_model("openai_compat", self._model)
        t0 = time.monotonic()
        # Both paths below are wrapped: this provider previously had no error
        # translation at all, so a bad key or an unreachable base_url raised a
        # raw `openai.APIConnectionError`/`httpx.HTTPStatusError` straight
        # through. Callers catch jsat's AIError family to degrade, so an
        # untranslated exception crashes them instead.
        try:
            if self._client is not None:
                resp = self._client.chat.completions.create(
                    model=model, max_tokens=max_tokens, temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.choices[0].message.content or ""
            else:
                import httpx
                resp_h = httpx.post(
                    f"{self._base_url}/chat/completions",
                    json={"model": model, "max_tokens": max_tokens,
                          "temperature": temperature,
                          "messages": [{"role": "user", "content": prompt}]},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=120.0,
                )
                resp_h.raise_for_status()
                text = resp_h.json()["choices"][0]["message"]["content"]
        except Exception as e:
            raise _as_jsat_error(e, self._base_url) from e

        elapsed = round((time.monotonic() - t0) * 1000)
        self._log.info("openai_compat_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(
        self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1
    ) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        from jsat._ai import require_explicit_model

        model = require_explicit_model("openai_compat", self._model)
        if self._client:
            for chunk in self._client.chat.completions.create(
                model=model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}], stream=True,
            ):
                piece = chunk.choices[0].delta.content
                if piece:
                    yield piece
        else:
            import json

            import httpx
            with httpx.stream("POST", f"{self._base_url}/chat/completions",
                              json={"model": model, "max_tokens": max_tokens, "stream": True,
                                    "messages": [{"role": "user", "content": prompt}]},
                              headers={"Authorization": f"Bearer {self._api_key}"},
                              timeout=120.0) as r:
                for line in r.iter_lines():
                    if line.startswith("data: ") and not line.endswith("[DONE]"):
                        try:
                            d = json.loads(line[6:])
                            piece = d["choices"][0]["delta"].get("content", "")
                            if piece:
                                yield piece
                        except Exception:
                            pass

    def is_available(self) -> bool:
        try:
            import httpx
            r = httpx.get(f"{self._base_url}/models",
                          headers={"Authorization": f"Bearer {self._api_key}"}, timeout=2.0)
            return r.status_code < 400
        except Exception:
            return False
