"""jsat._embed.none — No-op embedder for CI mode."""
from __future__ import annotations

from jsat._embed import Embedder

_DIMENSIONS = 768  # matches nomic-embed-code for drop-in compatibility
_warned = False


def _warn_once() -> None:
    global _warned
    if _warned:
        return
    _warned = True
    import structlog
    structlog.get_logger(__name__).warning(
        "noop_embedder_active",
        message="NoOpEmbedder active — all embeddings are zero vectors (CI mode).",
    )


class NoOpEmbedder(Embedder):
    """Returns zero vectors. Used in CI mode when embeddings are skipped."""

    @property
    def dimensions(self) -> int:
        return _DIMENSIONS

    @property
    def model_name(self) -> str:
        return "none"

    def embed(self, text: str) -> list[float]:
        _warn_once()
        return [0.0] * _DIMENSIONS

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        _warn_once()
        return [[0.0] * _DIMENSIONS for _ in texts]


__all__ = ["NoOpEmbedder"]
