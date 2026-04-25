"""Embedding backends — thin abstraction so tests can swap in a fake.

The default backend is ``FastEmbedBackend`` (ONNX-based, local, ~100MB
download on first use). A ``FakeBackend`` is provided for tests so they
don't pay model-download or inference cost.

Backend selection is driven by the ``OBSIDIAN_EMBEDDER`` environment
variable. Unknown or missing values fall back to fastembed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import struct
from abc import ABC, abstractmethod
from typing import Iterable

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384


class EmbeddingBackend(ABC):
    """Every backend exposes a stable dim and a batch embed call."""

    model_id: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in order."""


class FastEmbedBackend(EmbeddingBackend):
    """Local, ONNX-backed embeddings. Lazy-loads the model on first embed."""

    def __init__(self, model_id: str = DEFAULT_MODEL):
        self.model_id = model_id
        # fastembed reports dim once the model is materialised; we'll set it lazily.
        self.dim: int = DEFAULT_DIM
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from fastembed import TextEmbedding

        logger.info("loading embedder model %s (first call may download)", self.model_id)
        self._model = TextEmbedding(model_name=self.model_id)
        # Probe the dim from the first embedding if the default guess was wrong.
        probe = next(self._model.embed(["probe"]))
        self.dim = len(probe)
        logger.info("embedder ready (dim=%d)", self.dim)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_model()
        # fastembed returns a generator of numpy arrays; normalise to list[list[float]].
        vectors = list(self._model.embed(texts))  # type: ignore[union-attr]
        return [v.tolist() for v in vectors]


class FakeBackend(EmbeddingBackend):
    """Deterministic pseudo-embedding for tests.

    The vector is derived from SHA-1 of the input so two identical texts
    produce identical vectors, and distinct texts produce different ones.
    Cosine similarity is not semantically meaningful — tests should rely
    on determinism, not quality.
    """

    def __init__(self, dim: int = 32):
        self.model_id = f"fake@{dim}"
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            digest = hashlib.sha1(t.encode("utf-8", errors="replace")).digest()
            # Stretch/repeat the digest to fill `dim` floats in [-1, 1].
            floats: list[float] = []
            ix = 0
            while len(floats) < self.dim:
                chunk = digest[ix % len(digest) : ix % len(digest) + 4]
                if len(chunk) < 4:
                    chunk = (chunk + digest)[:4]
                val = struct.unpack("<i", chunk)[0] / (2**31)
                floats.append(val)
                ix += 4
            # Unit-normalise so cosine dist is well-defined.
            norm = sum(f * f for f in floats) ** 0.5 or 1.0
            out.append([f / norm for f in floats[: self.dim]])
        return out


def get_backend(name: str | None = None) -> EmbeddingBackend:
    """Factory. Respects ``OBSIDIAN_EMBEDDER`` if ``name`` is None."""
    choice = (name or os.environ.get("OBSIDIAN_EMBEDDER") or "fastembed").lower()
    if choice in ("fastembed", "fast-embed", "default", ""):
        model = os.environ.get("OBSIDIAN_EMBEDDER_MODEL", DEFAULT_MODEL)
        return FastEmbedBackend(model_id=model)
    if choice == "fake":
        return FakeBackend()
    if choice == "none":
        raise ValueError("OBSIDIAN_EMBEDDER=none disables semantic features")
    logger.warning("unknown OBSIDIAN_EMBEDDER=%r, falling back to fastembed", choice)
    return FastEmbedBackend()


def batched(seq: Iterable[str], size: int) -> Iterable[list[str]]:
    """Simple batch helper — embedders work better on small batches than singletons."""
    batch: list[str] = []
    for item in seq:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
