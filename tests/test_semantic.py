"""End-to-end semantic pipeline tests — vault + embed_queue + vector_store + rank.

Uses the FakeBackend so we don't download a model. FakeBackend is
deterministic (SHA-1 based), so tests can assert on ordering.
"""

from __future__ import annotations

import time

import pytest

from obsidian_mcp.embeddings import FakeBackend
from obsidian_mcp.vault import Vault


@pytest.fixture
def sem_vault(tmp_vault, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_EMBEDDER", "fake")
    vault = Vault(tmp_vault)
    backend = FakeBackend(dim=32)
    vault.enable_semantic(embedder=backend, db_path=tmp_vault / ".obsidian-mcp" / "idx.db")
    # Prime the embed queue for every existing note.
    vault.rebuild_embeddings()
    yield vault
    vault.disable_semantic()


class TestSemanticLifecycle:
    def test_enable_disable_idempotent(self, tmp_vault):
        vault = Vault(tmp_vault)
        backend = FakeBackend(dim=32)
        assert vault.enable_semantic(embedder=backend, db_path=tmp_vault / "idx.db")
        assert vault.semantic_enabled
        # Calling again is a no-op.
        assert vault.enable_semantic(embedder=backend, db_path=tmp_vault / "idx.db")
        vault.disable_semantic()
        assert not vault.semantic_enabled

    def test_embedder_none_disables(self, tmp_vault, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_EMBEDDER", "none")
        vault = Vault(tmp_vault)
        assert not vault.enable_semantic()
        assert not vault.semantic_enabled


class TestRebuild:
    def test_populates_store_from_existing_notes(self, sem_vault):
        stats = sem_vault.embedding_stats()
        assert stats["enabled"]
        assert stats["notes"] >= 3   # fixture has note1, note2, subfolder/note3, MOC, templates/daily
        assert stats["chunks"] >= stats["notes"]


class TestExactChunkRetrieval:
    def test_query_matching_existing_chunk_returns_its_note(self, sem_vault):
        # note1 contains "First paragraph of note one."
        results = sem_vault.semantic_search("First paragraph of note one.", k=5)
        paths = [r["path"] for r in results]
        assert paths[0] == "note1.md"

    def test_results_include_graph_signals(self, sem_vault):
        results = sem_vault.semantic_search("Second note content.", k=5)
        assert results
        first = results[0]
        assert "signals" in first
        assert "wikilink_match" in first["signals"]
        assert "tag_jaccard" in first["signals"]

    def test_path_scope_filters_results(self, sem_vault):
        # The fixture has note3 only under subfolder/. With path="subfolder",
        # other root-level notes should drop out even if their cos_sim is higher.
        scoped = sem_vault.semantic_search("note", k=10, path="subfolder")
        paths = [r["path"] for r in scoped]
        assert paths, "expected at least one result inside subfolder/"
        for p in paths:
            assert p.startswith("subfolder/"), p

    def test_path_scope_rejects_escape(self, sem_vault):
        with pytest.raises(ValueError):
            sem_vault.semantic_search("note", k=5, path="../escape")


class TestWriteTriggersEmbed:
    def test_new_note_becomes_searchable(self, sem_vault, tmp_vault):
        before = sem_vault.embedding_stats()["notes"]
        sem_vault.write_note(
            "fresh.md",
            "---\ntitle: Fresh Discovery\n---\n\nunique phrase xyz777 here.",
        )
        # Wait for the queue to drain.
        assert sem_vault._embed_queue.wait_idle(timeout=10)
        after = sem_vault.embedding_stats()["notes"]
        assert after == before + 1

        results = sem_vault.semantic_search("xyz777", k=5)
        paths = [r["path"] for r in results]
        assert "fresh.md" in paths

    def test_delete_removes_from_index(self, sem_vault):
        # Baseline: subfolder/note3.md is embedded.
        assert sem_vault.embedding_stats()["notes"] >= 3
        sem_vault.delete_note("subfolder/note3.md")
        # Delete is immediate (not debounced).
        # Tiny wait for any lingering enqueued work.
        time.sleep(0.1)
        stats_note_paths = [n for n in sem_vault.index]
        assert "subfolder/note3.md" not in stats_note_paths


class TestGraphReRank:
    def test_wikilink_match_boosts_weaker_candidate(self, sem_vault, tmp_vault):
        # Create two candidate notes with unrelated bodies.
        sem_vault.write_note(
            "candidate-a.md", "---\ntitle: Candidate A\n---\n\nlambda expressions in python.",
        )
        sem_vault.write_note(
            "candidate-b.md", "---\ntitle: Candidate B\n---\n\nlambda expressions in python explained.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)

        # Raw query (no graph signals) — highest cos_sim wins.
        raw = sem_vault.find_related_semantic(
            "lambda expressions in python explained.", limit=5
        )
        top_raw = [r["path"] for r in raw]

        # Query containing an explicit wikilink to candidate-a should lift it.
        with_link = sem_vault.find_related_semantic(
            "lambda expressions in python explained. See [[candidate-a]].", limit=5
        )
        top_linked = [r["path"] for r in with_link]

        # candidate-a should rank at least as high with the wikilink present,
        # and its signals should reflect that explicit match.
        a_linked = next(r for r in with_link if r["path"] == "candidate-a.md")
        assert a_linked["signals"]["wikilink_match"] is True
        # Rank of A should not be worse than in the raw query.
        assert top_linked.index("candidate-a.md") <= top_raw.index("candidate-a.md")


class TestStartupReconciliation:
    """`enable_semantic` should diff the on-disk store against the current
    vault state — picking up offline edits/creates/deletes that the watcher
    never saw."""

    def test_offline_create_is_enqueued_on_restart(self, tmp_vault):
        # First server lifetime: enable, embed everything, shut down.
        v1 = Vault(tmp_vault)
        backend = FakeBackend(dim=32)
        db = tmp_vault / ".obsidian-mcp" / "idx.db"
        v1.enable_semantic(embedder=backend, db_path=db)
        v1._embed_queue.wait_idle(timeout=10)
        baseline = v1.embedding_stats()["notes"]
        v1.disable_semantic()

        # Simulate offline edit: add a note while server is down.
        (tmp_vault / "offline-new.md").write_text(
            "---\ntitle: Offline\n---\n\noffline body content."
        )

        # Second lifetime: reconcile should pick up the new file.
        v2 = Vault(tmp_vault)
        v2.enable_semantic(embedder=FakeBackend(dim=32), db_path=db)
        v2._embed_queue.wait_idle(timeout=10)
        try:
            assert v2.embedding_stats()["notes"] == baseline + 1
            results = v2.semantic_search("offline body content.", k=5)
            assert any(r["path"] == "offline-new.md" for r in results)
        finally:
            v2.disable_semantic()

    def test_offline_delete_is_forgotten_on_restart(self, tmp_vault):
        v1 = Vault(tmp_vault)
        db = tmp_vault / ".obsidian-mcp" / "idx.db"
        v1.enable_semantic(embedder=FakeBackend(dim=32), db_path=db)
        v1._embed_queue.wait_idle(timeout=10)
        baseline = v1.embedding_stats()["notes"]
        assert baseline >= 1
        v1.disable_semantic()

        # Simulate offline delete.
        (tmp_vault / "note1.md").unlink()

        v2 = Vault(tmp_vault)
        v2.enable_semantic(embedder=FakeBackend(dim=32), db_path=db)
        v2._embed_queue.wait_idle(timeout=10)
        try:
            assert v2.embedding_stats()["notes"] == baseline - 1
            assert v2._vector_store.get_note("note1.md") is None
        finally:
            v2.disable_semantic()

    def test_offline_modify_re_embeds(self, tmp_vault):
        v1 = Vault(tmp_vault)
        db = tmp_vault / ".obsidian-mcp" / "idx.db"
        v1.enable_semantic(embedder=FakeBackend(dim=32), db_path=db)
        v1._embed_queue.wait_idle(timeout=10)
        v1.disable_semantic()

        # Mutate body and bump mtime past stored value.
        target = tmp_vault / "note1.md"
        target.write_text("---\ntitle: Note One\n---\n\nzzz unique marker zzz.")
        future = target.stat().st_mtime + 5.0
        import os
        os.utime(target, (future, future))

        v2 = Vault(tmp_vault)
        v2.enable_semantic(embedder=FakeBackend(dim=32), db_path=db)
        v2._embed_queue.wait_idle(timeout=10)
        try:
            results = v2.semantic_search("zzz unique marker zzz.", k=5)
            assert any(r["path"] == "note1.md" for r in results)
        finally:
            v2.disable_semantic()


class TestEmbeddingStatsFreshness:
    def test_queue_idle_reported_after_drain(self, sem_vault):
        # rebuild_embeddings already drained — stats should report idle.
        stats = sem_vault.embedding_stats()
        assert stats["queue_idle"] is True
        assert stats["queue_pending"] == 0

    def test_wait_blocks_until_drained(self, sem_vault):
        # Schedule an edit; without wait, queue may still be pending.
        sem_vault.write_note(
            "freshness.md",
            "---\ntitle: Freshness\n---\n\nbody body body.",
        )
        stats = sem_vault.embedding_stats(wait=True, timeout=10.0)
        assert stats["queue_idle"] is True
        assert stats["queue_pending"] == 0


class TestFallback:
    def test_semantic_search_disabled_returns_hint(self, tmp_vault):
        vault = Vault(tmp_vault)  # no enable_semantic
        assert vault.semantic_search("anything") == []

    def test_find_related_falls_back_to_lexical_when_disabled(self, tmp_vault):
        from obsidian_mcp.ingest import find_related_notes

        vault = Vault(tmp_vault)
        _ = vault.index  # prime
        results = find_related_notes(vault, "Note One [[note2]]")
        # Lexical scorer returns a "reasons" list; semantic returns "signals".
        assert results
        assert "reasons" in results[0]
