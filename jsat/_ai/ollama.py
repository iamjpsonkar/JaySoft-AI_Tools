"""jsat._ai.ollama — Ollama AI provider (jsat[local] extra)."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Iterator

from jsat._ai import AIProvider

if TYPE_CHECKING:
    from jsat._models import JSATConfig


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
        self._model: str = getattr(ai, "model", None) or "llama3.2"
        self._base_url: str = getattr(ai, "base_url", None) or "http://localhost:11434"
        self._max_tokens: int = getattr(ai, "max_tokens", 8192)
        self._timeout: int = getattr(ai, "timeout_seconds", 120)

        self._log.info("ollama_init", model=self._model, base_url=self._base_url)

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
            resp = self._ollama.generate(
                model=self._model, prompt=prompt,
                options={"num_predict": max_tokens, "temperature": temperature},
            )
        except Exception as e:
            elapsed = round((time.monotonic() - t0) * 1000)
            self._log.error("ollama_complete_error", error=str(e), elapsed_ms=elapsed)
            from jsat._exceptions import AIProviderError
            raise AIProviderError(
                f"Ollama error: {e}", provider="ollama", status_code=0
            ) from e

        elapsed = round((time.monotonic() - t0) * 1000)
        text: str = resp["response"]
        self._log.info("ollama_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        self._log.debug("ollama_stream_start", prompt_len=len(prompt))
        total = 0
        try:
            for chunk in self._ollama.generate(
                model=self._model, prompt=prompt,
                options={"num_predict": max_tokens}, stream=True,
            ):
                piece: str = chunk.get("response", "")
                if piece:
                    total += len(piece)
                    yield piece
        except Exception as e:
            self._log.error("ollama_stream_error", error=str(e), chars_so_far=total)
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
