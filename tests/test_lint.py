from obsidian_mcp.lint import (
    find_broken_wikilinks,
    find_duplicate_titles,
    find_stale_notes,
    lint_vault,
)


class TestBrokenWikilinks:
    def test_no_broken(self, vault):
        # Default fixture has all valid links
        broken = find_broken_wikilinks(vault)
        assert broken == []

    def test_finds_broken(self, vault, tmp_vault):
        (tmp_vault / "with_broken.md").write_text("Links to [[nonexistent]] and [[note1]]")
        vault.rebuild_index()
        broken = find_broken_wikilinks(vault)
        assert any(b["broken_link"] == "nonexistent" for b in broken)


class TestDuplicateTitles:
    def test_no_duplicates(self, vault):
        dupes = find_duplicate_titles(vault)
        assert dupes == []

    def test_finds_duplicates(self, vault, tmp_vault):
        (tmp_vault / "folder1").mkdir()
        (tmp_vault / "folder2").mkdir()
        (tmp_vault / "folder1" / "shared.md").write_text("# A")
        (tmp_vault / "folder2" / "shared.md").write_text("# B")
        vault.rebuild_index()
        dupes = find_duplicate_titles(vault)
        assert any(d["stem"] == "shared" and d["count"] == 2 for d in dupes)


class TestStaleNotes:
    def test_finds_stale_referenced(self, vault, tmp_vault):
        import os
        from datetime import datetime, timedelta

        # Create old note
        old = tmp_vault / "old_note.md"
        old.write_text("---\ntitle: Old\n---\nContent")
        # Set mtime to 1 year ago
        old_time = (datetime.now() - timedelta(days=365)).timestamp()
        os.utime(old, (old_time, old_time))

        # Create recent note that links to it
        (tmp_vault / "recent.md").write_text("Recent note linking to [[old_note]]")

        vault.rebuild_index()
        stale = find_stale_notes(vault, months=6)
        assert any(s["path"] == "old_note.md" for s in stale)


class TestLintVault:
    def test_returns_all_categories(self, vault):
        report = lint_vault(vault)
        assert "broken_wikilinks" in report
        assert "stale_notes" in report
        assert "duplicate_titles" in report
        assert "orphan_notes" in report
