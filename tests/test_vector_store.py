"""VectorStore tests — schema, upsert/replace/forget/rename, knn correctness."""

from __future__ import annotations

import pytest

from obsidian_mcp.chunker import Chunk
from obsidian_mcp.embeddings import FakeBackend
from obsidian_mcp.vector_store import VectorStore


@pytest.fixture
def store(tmp_path):
    backend = FakeBackend(dim=32)
    s = VectorStore(tmp_path / "idx.db", dim=backend.dim, model_id=backend.model_id)
    yield s, backend
    s.close()


def _embed_chunks(backend: FakeBackend, chunks: list[Chunk]) -> list[list[float]]:
    return backend.embed([c.text for c in chunks])


def _ch(text, heading="", start=0, end=None) -> Chunk:
    return Chunk(heading=heading, char_start=start, char_end=end or len(text), text=text)


class TestReplaceChunks:
    def test_insert_and_retrieve(self, store):
        s, backend = store
        chunks = [_ch("alpha content"), _ch("beta content", heading="Beta")]
        vecs = _embed_chunks(backend, chunks)
        s.replace_chunks("a.md", mtime=1.0, body_hash="h1", chunks=chunks, vectors=vecs)

        note = s.get_note("a.md")
        assert note["body_hash"] == "h1"
        assert note["mtime"] == 1.0

        # kNN to the first chunk should return it as nearest.
        hits = s.knn(vecs[0], k=10)
        paths = [h["path"] for h in hits]
        assert paths[0] == "a.md"
        assert hits[0]["text"] == "alpha content"

    def test_replace_overwrites_old_chunks(self, store):
        s, backend = store
        old = [_ch("one"), _ch("two"), _ch("three")]
        s.replace_chunks("a.md", 1.0, "h1", old, _embed_chunks(backend, old))

        new = [_ch("fresh content")]
        s.replace_chunks("a.md", 2.0, "h2", new, _embed_chunks(backend, new))

        # knn for "one" no longer hits "a.md"
        vec_one = backend.embed(["one"])[0]
        hits = s.knn(vec_one, k=5)
        for h in hits:
            if h["path"] == "a.md":
                assert h["text"] == "fresh content"
        stats = s.stats()
        assert stats["notes"] == 1
        assert stats["chunks"] == 1

    def test_dim_mismatch_raises(self, store):
        s, backend = store
        chunks = [_ch("x")]
        bad_vec = [0.0] * (backend.dim + 4)
        with pytest.raises(ValueError, match="dim"):
            s.replace_chunks("a.md", 1.0, "h1", chunks, [bad_vec])

    def test_vector_count_must_match_chunk_count(self, store):
        s, backend = store
        chunks = [_ch("x"), _ch("y")]
        with pytest.raises(ValueError, match="length mismatch"):
            s.replace_chunks("a.md", 1.0, "h1", chunks, _embed_chunks(backend, chunks[:1]))


class TestForget:
    def test_removes_note_chunks_and_vectors(self, store):
        s, backend = store
        chunks = [_ch("alpha"), _ch("beta")]
        s.replace_chunks("a.md", 1.0, "h1", chunks, _embed_chunks(backend, chunks))
        s.forget("a.md")
        assert s.get_note("a.md") is None
        stats = s.stats()
        assert stats["notes"] == 0 and stats["chunks"] == 0

    def test_forget_unknown_noop(self, store):
        s, _ = store
        s.forget("nonexistent.md")  # should not raise


class TestRename:
    def test_rename_preserves_vectors(self, store):
        s, backend = store
        chunks = [_ch("findable content")]
        vecs = _embed_chunks(backend, chunks)
        s.replace_chunks("old.md", 1.0, "h1", chunks, vecs)
        s.rename("old.md", "new.md")

        assert s.get_note("old.md") is None
        assert s.get_note("new.md") is not None
        hits = s.knn(vecs[0], k=5)
        assert hits[0]["path"] == "new.md"


class TestKnn:
    def test_distance_is_ordered(self, store):
        s, backend = store
        chunks = [_ch(f"distinct text {i}") for i in range(5)]
        vecs = _embed_chunks(backend, chunks)
        s.replace_chunks("a.md", 1.0, "h1", chunks, vecs)

        hits = s.knn(vecs[2], k=5)
        distances = [h["distance"] for h in hits]
        assert distances == sorted(distances)
        # The exact chunk we queried for should be the top hit.
        assert hits[0]["text"] == "distinct text 2"

    def test_k_respected(self, store):
        s, backend = store
        chunks = [_ch(f"t {i}") for i in range(10)]
        s.replace_chunks("a.md", 1.0, "h1", chunks, _embed_chunks(backend, chunks))
        hits = s.knn(backend.embed(["t 0"])[0], k=3)
        assert len(hits) == 3


class TestStats:
    def test_empty_store(self, store):
        s, _ = store
        stats = s.stats()
        assert stats["notes"] == 0
        assert stats["chunks"] == 0
        assert stats["dim"] == 32
        assert stats["last_embedded_at"] is None

    def test_populated(self, store):
        s, backend = store
        chunks = [_ch("a"), _ch("b")]
        s.replace_chunks("x.md", 1.0, "h1", chunks, _embed_chunks(backend, chunks))
        stats = s.stats()
        assert stats["notes"] == 1
        assert stats["chunks"] == 2
        assert stats["last_embedded_at"] is not None
