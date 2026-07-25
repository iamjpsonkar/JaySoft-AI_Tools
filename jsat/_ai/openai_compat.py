"""jsat._ai.openai_compat — Any OpenAI-compatible endpoint (LM Studio, vLLM, etc.)."""
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Any, Iterator

from jsat._ai import AIProvider

if TYPE_CHECKING:
    from jsat._models import JSATConfig


class OpenAICompatProvider(AIProvider):
    """Works with any OpenAI-compatible endpoint. Uses openai SDK or httpx fallback."""

    def __init__(self, cfg: JSATConfig) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)

        self._base_url: str = cfg.ai.base_url or "http://localhost:1234/v1"
        api_key_env = cfg.ai.api_key_env or "OPENAI_API_KEY"
        self._api_key: str = os.environ.get(api_key_env) or "not-needed"
        self._model: str = cfg.ai.model or "local-model"

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
        return self._model

    def complete(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        t0 = time.monotonic()
        if self._client is not None:
            resp = self._client.chat.completions.create(
                model=self._model, max_tokens=max_tokens, temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.choices[0].message.content or ""
        else:
            import httpx, json
            resp_h = httpx.post(
                f"{self._base_url}/chat/completions",
                json={"model": self._model, "max_tokens": max_tokens,
                      "temperature": temperature,
                      "messages": [{"role": "user", "content": prompt}]},
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=120.0,
            )
            resp_h.raise_for_status()
            text = resp_h.json()["choices"][0]["message"]["content"]

        elapsed = round((time.monotonic() - t0) * 1000)
        self._log.info("openai_compat_complete_done", response_len=len(text), duration_ms=elapsed)
        return text

    async def complete_async(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.1) -> str:
        return await asyncio.to_thread(self.complete, prompt, max_tokens, temperature)

    def stream(self, prompt: str, max_tokens: int = 2048) -> Iterator[str]:
        if self._client:
            for chunk in self._client.chat.completions.create(
                model=self._model, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}], stream=True,
            ):
                piece = chunk.choices[0].delta.content
                if piece:
                    yield piece
        else:
            import httpx, json
            with httpx.stream("POST", f"{self._base_url}/chat/completions",
                              json={"model": self._model, "max_tokens": max_tokens, "stream": True,
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
