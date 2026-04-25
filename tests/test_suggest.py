"""Auto-link suggestions: scan, score, dismiss, apply."""

from __future__ import annotations

import pytest

from obsidian_mcp.embeddings import FakeBackend
from obsidian_mcp.vault import Vault


@pytest.fixture
def sem_vault(tmp_vault, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_EMBEDDER", "fake")
    vault = Vault(tmp_vault)
    backend = FakeBackend(dim=32)
    vault.enable_semantic(embedder=backend, db_path=tmp_vault / ".obsidian-mcp" / "idx.db")
    vault.rebuild_embeddings()
    yield vault
    vault.disable_semantic()


class TestSuggestLinksBasics:
    def test_disabled_returns_empty(self, tmp_vault):
        vault = Vault(tmp_vault)  # no enable_semantic
        assert vault.suggest_links() == []

    def test_unknown_path_returns_empty(self, sem_vault):
        assert sem_vault.suggest_links(path="nonexistent.md") == []

    def test_already_linked_pairs_excluded(self, sem_vault, tmp_vault):
        # Add a brand-new note that is highly similar to note1 but unlinked.
        sem_vault.write_note(
            "twin-of-note1.md",
            "---\ntitle: Twin\ntags: [project]\n---\n\nFirst paragraph of note one. exact dup.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)

        results = sem_vault.suggest_links(min_score=0.0, limit=50)
        # The new note isn't linked to note1, so the pair should appear.
        pairs = {tuple(sorted([r["source"], r["target"]])) for r in results}
        assert ("note1.md", "twin-of-note1.md") in pairs
        # note1 <-> note2 are already wikilinked both ways — should NOT appear.
        assert ("note1.md", "note2.md") not in pairs

    def test_already_linked_excluded_either_direction(self, sem_vault, tmp_vault):
        # Note A has [[B]] but B has no link to A. The pair should still
        # count as "linked" — undirected — so it shouldn't be suggested.
        sem_vault.write_note(
            "uni-a.md",
            "---\ntitle: UniA\ntags: [project]\n---\n\nFirst paragraph of note one. [[uni-b]]",
        )
        sem_vault.write_note(
            "uni-b.md",
            "---\ntitle: UniB\ntags: [project]\n---\n\nFirst paragraph of note one.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)

        results = sem_vault.suggest_links(min_score=0.0, limit=100)
        pairs = {tuple(sorted([r["source"], r["target"]])) for r in results}
        # Undirected: A→B counts as linked from BOTH sides.
        assert ("uni-a.md", "uni-b.md") not in pairs

    def test_self_pair_never_suggested(self, sem_vault):
        results = sem_vault.suggest_links(min_score=0.0, limit=100)
        for r in results:
            assert r["source"] != r["target"]

    def test_scoped_to_one_path(self, sem_vault, tmp_vault):
        sem_vault.write_note(
            "lonely.md",
            "---\ntitle: Lonely\n---\n\ncompletely unique phrase brutonomicon.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)
        results = sem_vault.suggest_links(path="lonely.md", min_score=0.0, limit=50)
        # Every result should involve lonely.md as one side of the pair.
        for r in results:
            assert "lonely.md" in (r["source"], r["target"])


class TestSuggestLinksScoring:
    def test_results_sorted_by_score_descending(self, sem_vault):
        results = sem_vault.suggest_links(min_score=0.0, limit=50)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_min_score_filters(self, sem_vault):
        # Threshold of 999 should filter out everything.
        assert sem_vault.suggest_links(min_score=999.0) == []

    def test_each_result_has_breakdown_fields(self, sem_vault, tmp_vault):
        sem_vault.write_note(
            "twin.md",
            "---\ntitle: Twin\ntags: [project, active]\n---\n\nFirst paragraph of note one.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)
        results = sem_vault.suggest_links(min_score=0.0, limit=20)
        assert results
        r = results[0]
        for key in ("source", "target", "score", "cos_sim", "tag_jaccard",
                    "shared_tags", "snippet", "source_title", "target_title"):
            assert key in r


class TestDismiss:
    def test_dismissed_pair_does_not_reappear(self, sem_vault, tmp_vault):
        sem_vault.write_note(
            "twin.md",
            "---\ntitle: Twin\ntags: [project]\n---\n\nFirst paragraph of note one.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)

        before = sem_vault.suggest_links(min_score=0.0, limit=50)
        before_pairs = {tuple(sorted([r["source"], r["target"]])) for r in before}
        assert ("note1.md", "twin.md") in before_pairs

        sem_vault.dismiss_link_suggestion("note1.md", "twin.md")
        after = sem_vault.suggest_links(min_score=0.0, limit=50)
        after_pairs = {tuple(sorted([r["source"], r["target"]])) for r in after}
        assert ("note1.md", "twin.md") not in after_pairs

    def test_dismiss_is_order_independent(self, sem_vault, tmp_vault):
        sem_vault.write_note(
            "twin.md",
            "---\ntitle: Twin\n---\n\nFirst paragraph of note one.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)

        sem_vault.dismiss_link_suggestion("twin.md", "note1.md")  # reverse order
        results = sem_vault.suggest_links(min_score=0.0, limit=50)
        pairs = {tuple(sorted([r["source"], r["target"]])) for r in results}
        assert ("note1.md", "twin.md") not in pairs

    def test_undismiss_restores_pair(self, sem_vault, tmp_vault):
        sem_vault.write_note(
            "twin.md",
            "---\ntitle: Twin\n---\n\nFirst paragraph of note one.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)

        sem_vault.dismiss_link_suggestion("note1.md", "twin.md")
        sem_vault.undismiss_link_suggestion("note1.md", "twin.md")
        results = sem_vault.suggest_links(min_score=0.0, limit=50)
        pairs = {tuple(sorted([r["source"], r["target"]])) for r in results}
        assert ("note1.md", "twin.md") in pairs


class TestApply:
    def test_appends_wikilink_when_missing(self, sem_vault):
        msg = sem_vault.apply_link_suggestion("note1.md", "subfolder/note3.md")
        # note1 already links [[subfolder/note3]] from the fixture, so this
        # should be a no-op and report "already linked".
        assert "already" in msg.lower()

    def test_appends_when_actually_missing(self, sem_vault, tmp_vault):
        # Add a brand-new note with no wikilinks anywhere.
        sem_vault.write_note(
            "isolated.md",
            "---\ntitle: Isolated\n---\n\njust some text.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)

        msg = sem_vault.apply_link_suggestion("isolated.md", "note2.md")
        assert "linked" in msg.lower() and "already" not in msg.lower()

        body = sem_vault.read_note("isolated.md")
        assert "[[note2]]" in body
        assert "See also" in body

    def test_apply_is_idempotent(self, sem_vault, tmp_vault):
        sem_vault.write_note(
            "iso2.md",
            "---\ntitle: Iso2\n---\n\nbody.",
        )
        assert sem_vault._embed_queue.wait_idle(timeout=10)
        sem_vault.apply_link_suggestion("iso2.md", "note1.md")
        before = sem_vault.read_note("iso2.md")
        sem_vault.apply_link_suggestion("iso2.md", "note1.md")  # second time
        after = sem_vault.read_note("iso2.md")
        assert before == after  # nothing added the second time

    def test_apply_unknown_source_raises(self, sem_vault):
        with pytest.raises(FileNotFoundError):
            sem_vault.apply_link_suggestion("does-not-exist.md", "note1.md")
