"""jsat._embed — Embedder ABC."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod


class Embedder(ABC):
    """Contract all embedding backends must implement."""

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Pure-Python cosine similarity. No numpy required."""
        if len(a) != len(b):
            raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
        dot = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(y * y for y in b))
        if mag_a == 0.0 or mag_b == 0.0:
            return 0.0
        return dot / (mag_a * mag_b)


__all__ = ["Embedder"]
