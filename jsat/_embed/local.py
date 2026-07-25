"""jsat._embed.local — Ollama-backed local embedder (jsat[local] extra)."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from jsat._embed import Embedder
from jsat._exceptions import ProfileError

if TYPE_CHECKING:
    from jsat._models import JSATConfig


class LocalEmbedder(Embedder):
    """Local embedder via Ollama. Default model: nomic-embed-code (768-dim)."""

    def __init__(self, cfg: JSATConfig) -> None:
        import structlog
        self._log = structlog.get_logger(__name__)
        try:
            import ollama as _ollama
            self._ollama = _ollama
        except ImportError as e:
            raise ProfileError(
                "Ollama SDK not installed.\nInstall: pip install 'jsat[local]'",
                required_extra="local",
            ) from e

        self._model: str = cfg.embeddings.model or "nomic-embed-code"
        self._resolved_dims: int | None = None
        self._log.info("local_embedder_init", model=self._model)

    @property
    def dimensions(self) -> int:
        return self._resolved_dims if self._resolved_dims is not None else 768

    @property
    def model_name(self) -> str:
        return self._model

    def embed(self, text: str) -> list[float]:
        t0 = time.monotonic()
        resp = self._ollama.embeddings(model=self._model, prompt=text)
        vec: list[float] = resp["embedding"]
        if self._resolved_dims is None:
            self._resolved_dims = len(vec)
        elapsed = round((time.monotonic() - t0) * 1000)
        self._log.debug("local_embed", text_len=len(text), dim=len(vec), duration_ms=elapsed)
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._log.debug("local_embed_batch", n=len(texts))
        return [self.embed(t) for t in texts]
