"""Tests for embedding backends and the get_backend() factory.

These don't exercise the real FastEmbedBackend model load (it would
download a 100MB model on first use); the FakeBackend covers determinism,
and OllamaBackend is tested with a stubbed urlopen so we never need a
live Ollama server. We do verify that ``FastEmbedBackend`` raises a
helpful error when the optional extra is missing.
"""

from __future__ import annotations

import builtins
import io
import json
from unittest.mock import patch

import pytest

from obsidian_mcp import embeddings as emb
from obsidian_mcp.embeddings import (
    FakeBackend,
    FastEmbedBackend,
    OllamaBackend,
    OpenAICompatibleBackend,
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


class TestFastEmbedBackend:
    def test_friendly_error_when_fastembed_missing(self, monkeypatch):
        """Missing optional extra surfaces a clear hint, not a bare ImportError.
        The error fires on first embed (during the warmup call in
        ``Vault.start_embedding_pipeline``) — early enough for users to spot."""
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "fastembed":
                raise ImportError("No module named 'fastembed'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        backend = FastEmbedBackend()
        with pytest.raises(RuntimeError, match=r"fastembed is not installed"):
            backend.embed(["x"])


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


class TestOllamaHealthCheck:
    """Pre-flight check that runs once at startup, before the warmup
    embed. Surfaces the two common setup failures (server unreachable,
    model not pulled) with actionable hints instead of letting the
    warmup raise on a confusing first query."""

    def test_passes_when_model_is_pulled(self):
        backend = OllamaBackend(model_id="qwen3-embedding:8b", base_url="http://x:11434")
        with patch(
            "obsidian_mcp.embeddings.urlopen",
            return_value=_stub_response(
                {
                    "models": [{"name": "qwen3-embedding:8b"}, {"name": "llama3:latest"}],
                }
            ),
        ):
            ok, detail = backend.health_check()
        assert ok
        assert detail == "ok"

    def test_passes_when_model_id_omits_tag_and_latest_is_pulled(self):
        """Users may pass `qwen3-embedding` without a tag; Ollama lists it
        as `qwen3-embedding:latest`. Both should resolve to ok."""
        backend = OllamaBackend(model_id="qwen3-embedding", base_url="http://x:11434")
        with patch(
            "obsidian_mcp.embeddings.urlopen",
            return_value=_stub_response({"models": [{"name": "qwen3-embedding:latest"}]}),
        ):
            ok, _ = backend.health_check()
        assert ok

    def test_fails_with_actionable_hint_when_server_unreachable(self):
        from urllib.error import URLError

        backend = OllamaBackend(model_id="m", base_url="http://nope.invalid:11434")
        with patch(
            "obsidian_mcp.embeddings.urlopen",
            side_effect=URLError("nodename nor servname provided"),
        ):
            ok, detail = backend.health_check()
        assert not ok
        assert "could not reach Ollama" in detail
        assert "OBSIDIAN_EMBEDDER=none" in detail  # disable hint
        assert "OLLAMA_URL" in detail  # fix hint

    def test_fails_with_pull_command_when_model_missing(self):
        backend = OllamaBackend(model_id="bge-m3", base_url="http://x:11434")
        with patch(
            "obsidian_mcp.embeddings.urlopen",
            return_value=_stub_response({"models": [{"name": "llama3:latest"}]}),
        ):
            ok, detail = backend.health_check()
        assert not ok
        assert "ollama pull bge-m3" in detail
        assert "llama3:latest" in detail  # lists what *is* available


class TestOpenAICompatibleBackend:
    def test_embed_posts_correct_shape_and_probes_dim(self):
        backend = OpenAICompatibleBackend(
            model_id="text-embedding-3-small",
            base_url="https://embedding.example.com/api",
            api_key="sk-test",
        )
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["method"] = req.get_method()
            captured["auth"] = req.headers["Authorization"]
            return _stub_response(
                {
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                        {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    ],
                    "model": "text-embedding-3-small",
                    "object": "list",
                }
            )

        with patch("obsidian_mcp.embeddings.urlopen", fake_urlopen):
            vectors = backend.embed(["one", "two"])

        assert captured["url"] == "https://embedding.example.com/api/v1/embeddings"
        assert captured["method"] == "POST"
        assert captured["body"] == {"model": "text-embedding-3-small", "input": ["one", "two"]}
        assert captured["auth"] == "Bearer sk-test"
        assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        assert backend.dim == 3

    def test_empty_input_short_circuits(self):
        backend = OpenAICompatibleBackend(model_id="text-embedding-3-small")
        with patch("obsidian_mcp.embeddings.urlopen", side_effect=AssertionError("called")):
            assert backend.embed([]) == []

    def test_strips_trailing_slash_from_base_url(self):
        b = OpenAICompatibleBackend(model_id="m", base_url="https://embedding.example.com/")
        assert b.base_url == "https://embedding.example.com"

    def test_accepts_v1_base_url(self):
        b = OpenAICompatibleBackend(model_id="m", base_url="https://embedding.example.com/v1")
        assert b.embeddings_url == "https://embedding.example.com/v1/embeddings"

    def test_missing_data_field_raises(self):
        backend = OpenAICompatibleBackend(model_id="m")
        with patch(
            "obsidian_mcp.embeddings.urlopen",
            return_value=_stub_response({"error": {"message": "model not found"}}),
        ):
            with pytest.raises(RuntimeError, match="no embeddings"):
                backend.embed(["x"])

    def test_malformed_embeddings_raise(self):
        backend = OpenAICompatibleBackend(model_id="m")
        with patch(
            "obsidian_mcp.embeddings.urlopen",
            return_value=_stub_response({"data": [{"index": 0, "embedding": [0.1]}]}),
        ):
            with pytest.raises(RuntimeError, match="malformed embeddings"):
                backend.embed(["x", "y"])

    def test_requires_model_id(self):
        with pytest.raises(ValueError, match="model id"):
            OpenAICompatibleBackend(model_id="")


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

    def test_openai_compatible_requires_model(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "openai-compatible")
        monkeypatch.delenv("OBSIDIAN_EMBEDDER_MODEL", raising=False)
        with pytest.raises(ValueError, match="OBSIDIAN_EMBEDDER_MODEL"):
            get_backend()

    def test_openai_compatible_uses_env_url_key_and_model(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "openai-compatible")
        monkeypatch.setenv("OBSIDIAN_EMBEDDER_MODEL", "text-embedding-3-small")
        monkeypatch.setenv("OPENAI_COMPATIBLE_URL", "https://embedding.example.com")
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "sk-test")
        b = get_backend()
        assert isinstance(b, OpenAICompatibleBackend)
        assert b.model_id == "text-embedding-3-small"
        assert b.base_url == "https://embedding.example.com"
        assert b.api_key == "sk-test"

    def test_openai_compatible_default_url(self, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "openai-compatible")
        monkeypatch.setenv("OBSIDIAN_EMBEDDER_MODEL", "text-embedding-3-small")
        monkeypatch.delenv("OPENAI_COMPATIBLE_URL", raising=False)
        b = get_backend()
        assert b.base_url == emb.DEFAULT_OPENAI_COMPATIBLE_URL

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
