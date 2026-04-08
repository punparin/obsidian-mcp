import pytest
from obsidian_mcp.vault import Vault


class TestPathSecurity:
    def test_valid_path(self, vault, tmp_vault):
        resolved = vault._resolve_path("note1.md")
        assert str(resolved).startswith(str(tmp_vault))

    def test_escape_raises(self, vault):
        with pytest.raises(ValueError, match="escapes vault"):
            vault._resolve_path("../../etc/passwd")


class TestReadNote:
    def test_reads_content(self, vault):
        content = vault.read_note("note1.md")
        assert "First paragraph" in content

    def test_not_found(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.read_note("nonexistent.md")


class TestWriteNote:
    def test_creates_new(self, vault, tmp_vault):
        vault.write_note("new.md", "# New Note\n\nContent")
        assert (tmp_vault / "new.md").exists()
        assert "new.md" in vault.index

    def test_creates_parent_dirs(self, vault, tmp_vault):
        vault.write_note("deep/nested/note.md", "content")
        assert (tmp_vault / "deep" / "nested" / "note.md").exists()

    def test_overwrites_existing(self, vault):
        vault.write_note("note1.md", "Overwritten")
        assert vault.read_note("note1.md") == "Overwritten"


class TestAppendNote:
    def test_appends_to_existing(self, vault):
        vault.append_note("note1.md", "APPENDED TEXT")
        content = vault.read_note("note1.md")
        assert "APPENDED TEXT" in content
        assert "First paragraph" in content

    def test_creates_if_missing(self, vault, tmp_vault):
        vault.append_note("brand_new.md", "Fresh content")
        assert (tmp_vault / "brand_new.md").exists()


class TestListNotes:
    def test_lists_all(self, vault):
        notes = vault.list_notes()
        assert "note1.md" in notes
        assert "note2.md" in notes
        assert "subfolder/note3.md" in notes

    def test_lists_subfolder(self, vault):
        notes = vault.list_notes("subfolder")
        assert "subfolder/note3.md" in notes
        assert "note1.md" not in notes

    def test_folder_not_found(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.list_notes("nonexistent_folder")


class TestDeleteNote:
    def test_deletes(self, vault, tmp_vault):
        vault.delete_note("note1.md")
        assert not (tmp_vault / "note1.md").exists()
        assert "note1.md" not in vault.index

    def test_not_found(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.delete_note("nonexistent.md")


class TestMoveNote:
    def test_moves_file(self, vault, tmp_vault):
        vault.move_note("note1.md", "archive/note1.md")
        assert not (tmp_vault / "note1.md").exists()
        assert (tmp_vault / "archive" / "note1.md").exists()
        assert "archive/note1.md" in vault.index
        assert "note1.md" not in vault.index

    def test_destination_exists_raises(self, vault):
        with pytest.raises(FileExistsError):
            vault.move_note("note1.md", "note2.md")


class TestVaultIndex:
    def test_builds_index(self, vault):
        assert "note1.md" in vault.index
        assert vault.index["note1.md"].title == "Note One"
        assert "project" in vault.index["note1.md"].tags

    def test_inline_tags(self, vault):
        note3 = vault.index["subfolder/note3.md"]
        assert "inline-tag" in note3.tags

    def test_wikilinks_extracted(self, vault):
        assert "note2" in vault.index["note1.md"].links

    def test_summary(self, vault):
        assert "First paragraph" in vault.index["note1.md"].summary


class TestSearchFulltext:
    def test_finds_match(self, vault):
        results = vault.search_fulltext("First paragraph")
        assert len(results) == 1
        assert results[0]["path"] == "note1.md"

    def test_case_insensitive(self, vault):
        results = vault.search_fulltext("first paragraph")
        assert len(results) == 1

    def test_no_match(self, vault):
        assert vault.search_fulltext("zzz_nonexistent") == []


class TestSearchByTags:
    def test_finds_by_tag(self, vault):
        results = vault.search_by_tags(["project"])
        assert any(r["path"] == "note1.md" for r in results)

    def test_inline_tag(self, vault):
        results = vault.search_by_tags(["inline-tag"])
        assert any(r["path"] == "subfolder/note3.md" for r in results)

    def test_strips_hash(self, vault):
        results = vault.search_by_tags(["#project"])
        assert any(r["path"] == "note1.md" for r in results)


class TestSearchByFrontmatter:
    def test_exact_match(self, vault):
        results = vault.search_by_frontmatter("title", "Note One")
        assert len(results) == 1
        assert results[0]["path"] == "note1.md"

    def test_partial_match(self, vault):
        results = vault.search_by_frontmatter("title", "Note")
        assert len(results) >= 2


class TestSearchByDateRange:
    def test_finds_in_range(self, vault):
        results = vault.search_by_date_range("2026-01-01", "2026-01-20", "date")
        paths = [r["path"] for r in results]
        assert "note1.md" in paths
        assert "note2.md" in paths

    def test_excludes_out_of_range(self, vault):
        results = vault.search_by_date_range("2025-01-01", "2025-12-31", "date")
        assert len(results) == 0


class TestGetOrphanNotes:
    def test_finds_orphans(self, vault):
        orphans = vault.get_orphan_notes()
        paths = [o["path"] for o in orphans]
        # note2.md links to note1 and note3, note1 links to note2 and note3
        # MOC links to note1 and note2
        # But note2 is linked by note1 and MOC, note1 is linked by note2, note3, and MOC
        # note3 is linked by note1 and note2
        # So no standard notes should be orphans in this fixture
        # But templates/daily.md is excluded by the templates filter
        assert "templates/daily.md" not in paths

    def test_excludes_templates(self, vault):
        orphans = vault.get_orphan_notes()
        paths = [o["path"] for o in orphans]
        assert all("templates/" not in p for p in paths)

    def test_excludes_moc(self, vault):
        orphans = vault.get_orphan_notes()
        paths = [o["path"] for o in orphans]
        # MOC file should be excluded even if nothing links to it
        assert all("MOC" not in vault.index.get(p, vault.index.get(p, type("", (), {"frontmatter": {}}))).frontmatter.get("type", "") for p in paths)

    def test_detects_true_orphan(self, vault, tmp_vault):
        # Create a note that nothing links to
        (tmp_vault / "lonely.md").write_text("---\ntitle: Lonely Note\n---\nNo one links to me.")
        vault.rebuild_index()
        orphans = vault.get_orphan_notes()
        paths = [o["path"] for o in orphans]
        assert "lonely.md" in paths

    def test_orphan_has_metadata(self, vault, tmp_vault):
        (tmp_vault / "lonely.md").write_text("---\ntitle: Lonely\ntags: [lost]\n---\nAlone.")
        vault.rebuild_index()
        orphans = vault.get_orphan_notes()
        lonely = next(o for o in orphans if o["path"] == "lonely.md")
        assert lonely["title"] == "Lonely"
        assert "lost" in lonely["tags"]
        assert "outgoing_links" in lonely
        assert "modified" in lonely
