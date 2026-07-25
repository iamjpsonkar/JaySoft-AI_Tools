"""jsat._embed.openai — OpenAI embeddings (jsat[openai] extra)."""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from jsat._embed import Embedder
from jsat._exceptions import ProfileError

if TYPE_CHECKING:
    from jsat._models import JSATConfig


class OpenAIEmbedder(Embedder):
    """Embedder via OpenAI text-embedding API."""

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

        api_key_env = cfg.embeddings.api_key_env or "OPENAI_API_KEY"
        self._client = self._openai.OpenAI(api_key=os.environ.get(api_key_env))
        self._model: str = cfg.embeddings.model or "text-embedding-3-small"
        self._dims: int = cfg.embeddings.dimensions or 1536
        self._batch_size: int = cfg.embeddings.batch_size or 64
        self._log.info("openai_embedder_init", model=self._model, dims=self._dims)

    @property
    def dimensions(self) -> int:
        return self._dims

    @property
    def model_name(self) -> str:
        return self._model

    def embed(self, text: str) -> list[float]:
        t0 = time.monotonic()
        resp = self._client.embeddings.create(model=self._model, input=text)
        vec: list[float] = resp.data[0].embedding
        elapsed = round((time.monotonic() - t0) * 1000)
        self._log.debug("openai_embed", text_len=len(text), dim=len(vec), duration_ms=elapsed)
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            chunk = texts[i:i + self._batch_size]
            resp = self._client.embeddings.create(model=self._model, input=chunk)
            for item in sorted(resp.data, key=lambda d: d.index):
                results.append(item.embedding)
        self._log.info("openai_embed_batch", n=len(texts), batches=len(texts) // self._batch_size + 1)
        return results
