"""Embedding backends — thin abstraction so tests can swap in a fake.

Default backend is ``FastEmbedBackend`` (ONNX-based, local, ~100MB
download on first use). Set ``OBSIDIAN_EMBEDDER=ollama`` or
``OBSIDIAN_EMBEDDER=openai-compatible`` to point at a remote embedding
service instead — useful when the MCP runs on a low-power host (Pi) and
you want a beefier model running elsewhere. A ``FakeBackend`` is provided
for tests.

Selection is driven by environment variables:

    OBSIDIAN_EMBEDDER         fastembed | ollama | openai-compatible | fake | none
    OBSIDIAN_EMBEDDER_MODEL   model id (e.g. BAAI/bge-small-en-v1.5,
                              nomic-embed-text, mxbai-embed-large)
    OLLAMA_URL                base URL when EMBEDDER=ollama
                               (default http://localhost:11434)
    OPENAI_COMPATIBLE_URL     base URL when EMBEDDER=openai-compatible
                               (default https://localhost:11434)
    OPENAI_COMPATIBLE_API_KEY optional bearer token for OpenAI-compatible APIs

Switching models is safe: ``VectorStore`` detects the change at startup
and clears the index so the reconcile loop re-embeds the vault.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
from abc import ABC, abstractmethod
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OPENAI_COMPATIBLE_URL = "https://localhost:11434"


class EmbeddingBackend(ABC):
    """Every backend exposes a stable dim and a batch embed call."""

    model_id: str
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in order."""

    def health_check(self) -> tuple[bool, str]:
        """Cheap pre-flight verification run once at startup.

        Default impl: try a one-string embed and call any non-empty result a
        success. Backends that talk to a remote service should override with
        a lighter check (e.g. listing models) so we don't pay for a real
        embedding request just to confirm the service is up.

        Returns ``(ok, detail)``. The detail string is a short human-readable
        explanation of *why* — used in the warning logged on failure.
        """
        try:
            vectors = self.embed(["health-check"])
            if not vectors or not vectors[0]:
                return False, "backend returned no embedding for the health-check probe"
            return True, "ok"
        except Exception as exc:  # noqa: BLE001 — surfacing the message back to the user
            return False, str(exc)


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
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "fastembed is not installed. The Docker image and the base "
                "install no longer ship it. Either:\n"
                '  - install the extra: pip install ".[fastembed]"\n'
                "  - use a remote backend: OBSIDIAN_EMBEDDER=ollama or "
                "openai-compatible with OBSIDIAN_EMBEDDER_MODEL + provider URL\n"
                "  - disable semantic features: OBSIDIAN_EMBEDDER=none"
            ) from e

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


class OllamaBackend(EmbeddingBackend):
    """Embeddings via a remote Ollama server.

    Hits the batch endpoint ``POST /api/embed`` with ``{model, input}``;
    expects ``{embeddings: [[...], ...]}`` back. Dim is probed from the
    first response so we don't need to hard-code it per model.
    """

    def __init__(
        self,
        model_id: str,
        base_url: str = DEFAULT_OLLAMA_URL,
        timeout: float = 60.0,
    ):
        if not model_id:
            raise ValueError("OllamaBackend requires a model id")
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Probed lazily on the first embed call. Zero is a sentinel meaning
        # "ask the server before opening any vector store sized to this dim".
        self.dim: int = 0

    def _post(self, inputs: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model_id, "input": inputs}).encode("utf-8")
        req = Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            raise RuntimeError(
                f"Ollama returned HTTP {e.code} from {self.base_url}: {e.read().decode('utf-8', errors='replace')}"
            ) from e
        except URLError as e:
            raise RuntimeError(f"could not reach Ollama at {self.base_url}: {e.reason}") from e
        embeddings = body.get("embeddings")
        if not embeddings:
            raise RuntimeError(f"Ollama returned no embeddings (model={self.model_id}): {body}")
        return embeddings

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._post(texts)
        if self.dim == 0:
            self.dim = len(vectors[0])
            logger.info(
                "ollama embedder ready (model=%s, url=%s, dim=%d)",
                self.model_id,
                self.base_url,
                self.dim,
            )
        return vectors

    def health_check(self) -> tuple[bool, str]:
        """Confirm the Ollama server is up *and* has the configured model.

        Hits ``GET /api/tags`` (cheap, no embedding work) and checks the
        configured ``model_id`` is in the pulled list. Returns actionable
        messages for the two common failure modes — server unreachable, or
        server up but model not pulled — instead of letting the user discover
        them on the first ``semantic_search`` call.
        """
        try:
            req = Request(
                f"{self.base_url}/api/tags",
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except URLError as e:
            return False, (
                f"could not reach Ollama at {self.base_url}: {e.reason}. "
                "Set OBSIDIAN_EMBEDDER=none to disable semantic features, "
                "or fix OLLAMA_URL / start the server."
            )
        except HTTPError as e:
            return False, f"Ollama returned HTTP {e.code} from {self.base_url}/api/tags"
        except Exception as e:  # noqa: BLE001
            return False, f"unexpected error talking to Ollama at {self.base_url}: {e}"

        pulled = {m.get("name", "") for m in (body.get("models") or [])}
        # Ollama lists models as `name:tag`; users may pass either form.
        if self.model_id in pulled:
            return True, "ok"
        if ":" not in self.model_id and f"{self.model_id}:latest" in pulled:
            return True, "ok"
        pulled_summary = ", ".join(sorted(pulled)) or "(none)"
        return False, (
            f"Ollama at {self.base_url} is reachable but model "
            f"{self.model_id!r} is not pulled. Available models: "
            f"{pulled_summary}. Run `ollama pull {self.model_id}` on the "
            "Ollama host to fix."
        )


class OpenAICompatibleBackend(EmbeddingBackend):
    """Embeddings via an OpenAI-compatible ``POST /v1/embeddings`` API."""

    def __init__(
        self,
        model_id: str,
        base_url: str = DEFAULT_OPENAI_COMPATIBLE_URL,
        api_key: str | None = None,
        timeout: float = 60.0,
    ):
        if not model_id:
            raise ValueError("OpenAICompatibleBackend requires a model id")
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.dim: int = 0

    @property
    def embeddings_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/embeddings"
        return f"{self.base_url}/v1/embeddings"

    def _post(self, inputs: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model_id, "input": inputs}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = Request(
            self.embeddings_url,
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            raise RuntimeError(
                f"OpenAI-compatible embedder returned HTTP {e.code} from {self.base_url}: "
                f"{e.read().decode('utf-8', errors='replace')}"
            ) from e
        except URLError as e:
            raise RuntimeError(f"could not reach OpenAI-compatible embedder at {self.base_url}: {e.reason}") from e

        data = body.get("data")
        if not data:
            raise RuntimeError(f"OpenAI-compatible embedder returned no embeddings (model={self.model_id}): {body}")
        embeddings = [item.get("embedding") for item in data]
        if len(embeddings) != len(inputs) or any(not vector for vector in embeddings):
            raise RuntimeError(
                f"OpenAI-compatible embedder returned malformed embeddings (model={self.model_id}): {body}"
            )
        return embeddings

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._post(texts)
        if self.dim == 0:
            self.dim = len(vectors[0])
            logger.info(
                "openai-compatible embedder ready (model=%s, url=%s, dim=%d)",
                self.model_id,
                self.base_url,
                self.dim,
            )
        return vectors


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
    if choice == "ollama":
        model = os.environ.get("OBSIDIAN_EMBEDDER_MODEL")
        if not model:
            raise ValueError(
                "OBSIDIAN_EMBEDDER=ollama requires OBSIDIAN_EMBEDDER_MODEL "
                "(e.g. nomic-embed-text, mxbai-embed-large, bge-m3)"
            )
        base_url = os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
        return OllamaBackend(model_id=model, base_url=base_url)
    if choice in ("openai-compatible", "openai_compatible"):
        model = os.environ.get("OBSIDIAN_EMBEDDER_MODEL")
        if not model:
            raise ValueError(
                "OBSIDIAN_EMBEDDER=openai-compatible requires OBSIDIAN_EMBEDDER_MODEL (e.g. text-embedding-3-small)"
            )
        base_url = os.environ.get("OPENAI_COMPATIBLE_URL", DEFAULT_OPENAI_COMPATIBLE_URL)
        api_key = os.environ.get("OPENAI_COMPATIBLE_API_KEY")
        return OpenAICompatibleBackend(model_id=model, base_url=base_url, api_key=api_key)
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
