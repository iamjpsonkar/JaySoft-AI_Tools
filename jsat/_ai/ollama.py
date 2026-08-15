"""jsat._ai.ollama — Ollama AI provider (jsat[local] extra)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from jsat._ai import AIProvider

if TYPE_CHECKING:
    from jsat._models import JSATConfig

DEFAULT_MODEL = "llama3.2"
DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(AIProvider):
    """AI provider backed by a local Ollama instance."""

    def __init__(self, cfg: JSATConfig) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        try:
            import ollama as _ollama  # type: ignore[import]
            self._ollama = _ollama
        except ImportError as e:
            from jsat._exceptions import ProfileError
            raise ProfileError(
                "Ollama package not installed.\nInstall: pip install 'jsat[local]'",
                required_extra="local",
            ) from e

        ai = cfg.ai
        self._model: str = getattr(ai, "model", None) or DEFAULT_MODEL
        self._base_url: str = getattr(ai, "base_url", None) or DEFAULT_BASE_URL
        self._max_tokens: int = getattr(ai, "max_tokens", 8192)
        self._timeout: int = getattr(ai, "timeout_seconds", 120)

        # Bind a client to the configured host — the module-level ollama.* helpers
        # always talk to localhost:11434 and would silently ignore cfg.ai.base_url.
        self._client = _ollama.Client(host=self._base_url)

        self._log.info("ollama_init", model=self._model, base_url=self._base_url)

    def _installed_models(self) -> list[str]:
        """Names of models pulled on the configured host ([] if unreachable)."""
        try:
            resp = self._client.list()
            models = getattr(resp, "models", None) or resp["models"]
            names = [getattr(m, "model", None) or m["model"] for m in models]
            return [n for n in names if n]
        except Exception:
            return []

    def _wrap_error(self, e: Exception) -> Exception:
        """Turn Ollama's opaque 404 into an actionable error listing what is installed."""
        status = getattr(e, "status_code", 0) or 0
        if status != 404:
            return e

        from jsat._exceptions import AIProviderError
        available = self._installed_models()
        if available:
            hint = "Installed models: " + ", ".join(available[:10]) + "\n" + (
                f"Use one: jsat ai use ollama --model {available[0]}"
            )
        else:
            hint = f"No models installed. Pull one: ollama pull {self._model}"

        return AIProviderError(
            f"Ollama model '{self._model}' not found at {self._base_url}.\n{hint}",
            provider="ollama", status_code=404,
        )

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        self._log.debug("ollama_complete", prompt_len=len(prompt), max_tokens=max_tokens)
        t0 = time.monotonic()
        try:
            resp = self._client.generate(
                model=self._model, prompt=prompt,
                options={"num_predict": max_tokens, "temperature": temperature},
            )
        except Exception as e:
            elapsed = round((time.monotonic() - t0) * 1000)
            self._log.error("ollama_complete_error", error=str(e), elapsed_ms=elapsed)
            wrapped = self._wrap_error(e)
            if wrapped is not e:
                raise wrapped from e
            from jsat._exceptions import AIProviderError
            raise AIProviderError(
                f"Ollama error: {e}", provider="ollama", status_code=0
            ) from e

        elapsed = round((time.monotonic() - t0) * 1000)
        text: str = resp["response"]
        self._log.info("ollama_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(
        self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1
    ) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        self._log.debug("ollama_stream_start", prompt_len=len(prompt))
        total = 0
        try:
            for chunk in self._client.generate(
                model=self._model, prompt=prompt,
                options={"num_predict": max_tokens}, stream=True,
            ):
                piece: str = chunk.get("response", "")
                if piece:
                    total += len(piece)
                    yield piece
        except Exception as e:
            self._log.error("ollama_stream_error", error=str(e), chars_so_far=total)
            wrapped = self._wrap_error(e)
            if wrapped is not e:
                raise wrapped from e
            raise
        self._log.info("ollama_stream_done", total_chars=total)

    def is_available(self) -> bool:
        try:
            import httpx
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=0.5)
            up = resp.status_code < 500
            self._log.debug("ollama_available", up=up, status=resp.status_code)
            return up
        except Exception as e:
            self._log.debug("ollama_unavailable", error=str(e))
            return False
