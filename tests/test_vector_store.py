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


class TestModelChangeReset:
    """Switching embedding model or dim should auto-clear the index so the
    reconcile loop re-embeds every note. Dismissed link suggestions must
    survive since they're tied to wikilinks, not embeddings."""

    def test_same_model_keeps_data(self, tmp_path):
        b = FakeBackend(dim=32)
        s = VectorStore(tmp_path / "idx.db", dim=b.dim, model_id=b.model_id)
        chunks = [_ch("alpha")]
        s.replace_chunks("a.md", 1.0, "h1", chunks, _embed_chunks(b, chunks))
        s.close()

        s2 = VectorStore(tmp_path / "idx.db", dim=b.dim, model_id=b.model_id)
        assert s2.get_note("a.md") is not None
        assert s2.stats()["chunks"] == 1
        s2.close()

    def test_model_change_clears_index(self, tmp_path):
        old = FakeBackend(dim=32)
        s = VectorStore(tmp_path / "idx.db", dim=old.dim, model_id=old.model_id)
        chunks = [_ch("alpha"), _ch("beta")]
        s.replace_chunks("a.md", 1.0, "h1", chunks, _embed_chunks(old, chunks))
        # Pre-existing dismissal we expect to survive the reset.
        s.dismiss_pair("note-a.md", "note-b.md")
        s.close()

        # Re-open with a different model id (same dim).
        s2 = VectorStore(tmp_path / "idx.db", dim=32, model_id="other-model")
        stats = s2.stats()
        assert stats["notes"] == 0
        assert stats["chunks"] == 0
        # Dismissals are about wikilinks, not embeddings — they survive.
        assert s2.get_all_dismissed() == {("note-a.md", "note-b.md")}
        s2.close()

    def test_dim_change_drops_vec_table_and_reindexes(self, tmp_path):
        small = FakeBackend(dim=16)
        s = VectorStore(tmp_path / "idx.db", dim=small.dim, model_id=small.model_id)
        chunks = [_ch("alpha")]
        s.replace_chunks("a.md", 1.0, "h1", chunks, _embed_chunks(small, chunks))
        s.close()

        # Same model id, but the dim changed — vec table must be rebuilt.
        big = FakeBackend(dim=64)
        # Force same model_id via direct init to isolate dim-only mismatch.
        s2 = VectorStore(tmp_path / "idx.db", dim=big.dim, model_id=small.model_id)
        assert s2.stats()["notes"] == 0
        # New inserts at the new dim succeed.
        new_chunks = [_ch("beta")]
        s2.replace_chunks("b.md", 2.0, "h2", new_chunks, _embed_chunks(big, new_chunks))
        assert s2.stats()["dim"] == 64
        s2.close()


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
