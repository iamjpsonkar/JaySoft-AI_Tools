"""jsat._ai.ollama — Ollama AI provider (local daemon or cloud routing)."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from jsat._ai import AIProvider
from jsat._ollama import DEFAULT_BASE_URL, ollama_model_kind, select_ollama_model

if TYPE_CHECKING:
    from jsat._models import JSATConfig


class _HttpOllamaClient:
    """Small native-API fallback when the optional ``ollama`` SDK is absent."""

    def __init__(self, host: str, timeout: int) -> None:
        self._host = host.rstrip("/")
        self._timeout = timeout

    def list(self) -> dict:
        import httpx

        response = httpx.get(f"{self._host}/api/tags", timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def generate(self, *, stream: bool = False, **payload):
        import httpx

        if not stream:
            response = httpx.post(
                f"{self._host}/api/generate",
                json={**payload, "stream": False},
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.json()

        def chunks():
            with httpx.stream(
                "POST",
                f"{self._host}/api/generate",
                json={**payload, "stream": True},
                timeout=self._timeout,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        yield json.loads(line)

        return chunks()


class OllamaProvider(AIProvider):
    """AI provider backed by an Ollama host.

    A local host can run local models itself or route cloud-suffixed models through
    Ollama Cloud after the user signs in with the Ollama CLI.
    """

    def __init__(self, cfg: JSATConfig) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        ai = cfg.ai
        self._model: str | None = getattr(ai, "model", None)
        self._base_url: str = getattr(ai, "base_url", None) or DEFAULT_BASE_URL
        self._max_tokens: int = getattr(ai, "max_tokens", 8192)
        self._timeout: int = getattr(ai, "timeout_seconds", 120)

        # Prefer the SDK when installed, but a running Ollama server is sufficient.
        try:
            import ollama as _ollama  # type: ignore[import]

            self._client = _ollama.Client(host=self._base_url)
        except ImportError:
            self._client = _HttpOllamaClient(self._base_url, self._timeout)

        self._log.info("ollama_init", model=self._model or "not-selected", base_url=self._base_url)

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
        response = getattr(e, "response", None)
        status = getattr(e, "status_code", 0) or getattr(response, "status_code", 0) or 0
        if status != 404:
            return e

        from jsat._exceptions import AIProviderError
        available = self._installed_models()
        if available:
            hint = "Installed models: " + ", ".join(available[:10]) + "\n" + (
                f"Use one: jsat ai use ollama --model {available[0]}"
            )
        else:
            model = self._require_model()
            if ollama_model_kind(model) == "cloud":
                hint = "No models available. Sign in with: ollama signin"
            else:
                hint = f"No models available. Pull it with: ollama pull {model}"

        return AIProviderError(
            f"Ollama model '{self._model}' not found at {self._base_url}.\n{hint}",
            provider="ollama", status_code=404,
        )

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model or "not selected"

    def _require_model(self) -> str:
        """Resolve the sole installed model or return actionable selection help."""
        try:
            self._model = select_ollama_model(self._model, self._installed_models())
        except ValueError as exc:
            from jsat._exceptions import AIProviderError

            raise AIProviderError(str(exc), provider="ollama", status_code=0) from exc
        return self._model

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        self._log.debug("ollama_complete", prompt_len=len(prompt), max_tokens=max_tokens)
        t0 = time.monotonic()
        try:
            resp = self._client.generate(
                model=self._require_model(), prompt=prompt,
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
                model=self._require_model(), prompt=prompt,
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
            if resp.status_code >= 400 or not self._model:
                self._log.debug(
                    "ollama_unavailable",
                    status=resp.status_code,
                    reason="server error or model not selected",
                )
                return False
            from jsat._ollama import ollama_models_match

            models = [item.get("name", "") for item in resp.json().get("models", [])]
            available = any(ollama_models_match(name, self._model) for name in models)
            self._log.debug(
                "ollama_available",
                up=available,
                status=resp.status_code,
                model=self._model,
            )
            return available
        except Exception as e:
            self._log.debug("ollama_unavailable", error=str(e))
            return False
