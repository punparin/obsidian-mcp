"""Tests for embedding backends and the get_backend() factory.

These don't exercise FastEmbedBackend (it would download a 100MB model
on first use); the FakeBackend covers determinism, and OllamaBackend
is tested with a stubbed urlopen so we never need a live Ollama server.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from obsidian_mcp import embeddings as emb
from obsidian_mcp.embeddings import (
    FakeBackend,
    OllamaBackend,
    batched,
    get_backend,
)


def _stub_response(payload: dict) -> io.BytesIO:
    """Return a context-manager-friendly stand-in for urlopen()."""
    body = json.dumps(payload).encode("utf-8")

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return _Resp(body)


class TestFakeBackend:
    def test_deterministic(self):
        b = FakeBackend(dim=16)
        v1 = b.embed(["hello world"])[0]
        v2 = b.embed(["hello world"])[0]
        assert v1 == v2

    def test_distinct_inputs_give_distinct_vectors(self):
        b = FakeBackend(dim=16)
        a, c = b.embed(["alpha", "charlie"])
        assert a != c

    def test_dim_respected(self):
        b = FakeBackend(dim=64)
        assert len(b.embed(["x"])[0]) == 64


class TestOllamaBackend:
    def test_embed_posts_correct_shape_and_probes_dim(self):
        backend = OllamaBackend(model_id="nomic-embed-text", base_url="http://x:11434")
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["method"] = req.get_method()
            return _stub_response({"embeddings": [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]})

        with patch("obsidian_mcp.embeddings.urlopen", fake_urlopen):
            vectors = backend.embed(["one", "two"])

        assert captured["url"] == "http://x:11434/api/embed"
        assert captured["method"] == "POST"
        assert captured["body"] == {"model": "nomic-embed-text", "input": ["one", "two"]}
        assert vectors == [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]]
        # Dim is probed from the first response.
        assert backend.dim == 4

    def test_empty_input_short_circuits(self):
        backend = OllamaBackend(model_id="nomic-embed-text")
        # Should not hit the network at all.
        with patch("obsidian_mcp.embeddings.urlopen", side_effect=AssertionError("called")):
            assert backend.embed([]) == []

    def test_strips_trailing_slash_from_base_url(self):
        b = OllamaBackend(model_id="m", base_url="http://x:11434/")
        assert b.base_url == "http://x:11434"

    def test_missing_embeddings_field_raises(self):
        backend = OllamaBackend(model_id="m")
        with patch(
            "obsidian_mcp.embeddings.urlopen",
            return_value=_stub_response({"error": "model not found"}),
        ):
            with pytest.raises(RuntimeError, match="no embeddings"):
                backend.embed(["x"])

    def test_requires_model_id(self):
        with pytest.raises(ValueError, match="model id"):
            OllamaBackend(model_id="")


class TestGetBackend:
    def test_default_returns_fastembed(self, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_EMBEDDER", raising=False)
        # Avoid actually loading fastembed — just check the type.
        b = get_backend()
        assert b.__class__.__name__ == "FastEmbedBackend"

    def test_explicit_fake(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "fake")
        b = get_backend()
        assert isinstance(b, FakeBackend)

    def test_ollama_requires_model(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "ollama")
        monkeypatch.delenv("OBSIDIAN_EMBEDDER_MODEL", raising=False)
        with pytest.raises(ValueError, match="OBSIDIAN_EMBEDDER_MODEL"):
            get_backend()

    def test_ollama_uses_env_url_and_model(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "ollama")
        monkeypatch.setenv("OBSIDIAN_EMBEDDER_MODEL", "mxbai-embed-large")
        monkeypatch.setenv("OLLAMA_URL", "http://desktop.local:11434")
        b = get_backend()
        assert isinstance(b, OllamaBackend)
        assert b.model_id == "mxbai-embed-large"
        assert b.base_url == "http://desktop.local:11434"

    def test_ollama_default_url(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "ollama")
        monkeypatch.setenv("OBSIDIAN_EMBEDDER_MODEL", "nomic-embed-text")
        monkeypatch.delenv("OLLAMA_URL", raising=False)
        b = get_backend()
        assert b.base_url == emb.DEFAULT_OLLAMA_URL

    def test_none_disables_semantic(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "none")
        with pytest.raises(ValueError, match="disables semantic"):
            get_backend()

    def test_unknown_falls_back_to_fastembed(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "garbage-value")
        b = get_backend()
        assert b.__class__.__name__ == "FastEmbedBackend"


class TestBatched:
    def test_packs_into_full_batches(self):
        out = list(batched(["a", "b", "c", "d", "e"], 2))
        assert out == [["a", "b"], ["c", "d"], ["e"]]

    def test_empty(self):
        assert list(batched([], 4)) == []
