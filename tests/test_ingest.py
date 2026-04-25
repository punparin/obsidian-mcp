import pytest

from obsidian_mcp.ingest import archive_inbox_note, find_related_notes, list_inbox


class TestListInbox:
    def test_empty_inbox(self, vault):
        assert list_inbox(vault) == []

    def test_lists_inbox(self, vault, tmp_vault):
        (tmp_vault / "inbox").mkdir()
        (tmp_vault / "inbox" / "raw1.md").write_text("Some raw note content")
        (tmp_vault / "inbox" / "raw2.md").write_text("Another raw note")
        items = list_inbox(vault)
        assert len(items) == 2
        assert all("path" in i and "preview" in i for i in items)


class TestFindRelatedNotes:
    def test_finds_by_tag(self, vault):
        # Fixture has note1 with tags [project, active]
        content = "Working on a #project today"
        related = find_related_notes(vault, content)
        assert any(r["path"] == "note1.md" for r in related)

    def test_finds_by_wikilink(self, vault):
        content = "See [[note1]] for context"
        related = find_related_notes(vault, content)
        assert any(r["path"] == "note1.md" for r in related)

    def test_excludes_inbox(self, vault, tmp_vault):
        (tmp_vault / "inbox").mkdir()
        (tmp_vault / "inbox" / "draft.md").write_text("---\ntags: [project]\n---\nBody")
        vault.rebuild_index()
        content = "Working on a #project"
        related = find_related_notes(vault, content)
        paths = [r["path"] for r in related]
        assert "inbox/draft.md" not in paths


class TestArchiveInboxNote:
    def test_archives_note(self, vault, tmp_vault):
        (tmp_vault / "inbox").mkdir()
        (tmp_vault / "inbox" / "todo.md").write_text("---\ntitle: Todo\n---\nContent")
        vault.rebuild_index()

        result = archive_inbox_note(vault, "inbox/todo.md")
        assert "Archived" in result
        assert not (tmp_vault / "inbox" / "todo.md").exists()
        # Check it's in archive/YYYY-MM/
        archive_files = list((tmp_vault / "archive").rglob("todo.md"))
        assert len(archive_files) == 1

    def test_rejects_non_inbox(self, vault):
        with pytest.raises(ValueError, match="Not an inbox note"):
            archive_inbox_note(vault, "note1.md")

    def test_missing_note(self, vault):
        with pytest.raises(FileNotFoundError):
            archive_inbox_note(vault, "inbox/nonexistent.md")
