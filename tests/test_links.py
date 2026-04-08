from obsidian_mcp.links import extract_wikilinks, resolve_wikilink, get_backlinks, get_graph, update_wikilinks_across_vault
from obsidian_mcp.vault import NoteIndex


def _note(path, links=None):
    return NoteIndex(path=path, title=path, links=links or [])


class TestExtractWikilinks:
    def test_basic(self):
        assert extract_wikilinks("Link to [[Note A]] and [[Note B]]") == ["Note A", "Note B"]

    def test_alias(self):
        assert extract_wikilinks("[[Note A|display text]]") == ["Note A"]

    def test_heading(self):
        assert extract_wikilinks("[[Note A#Section 1]]") == ["Note A"]

    def test_alias_and_heading(self):
        assert extract_wikilinks("[[Note A#heading|alias]]") == ["Note A"]

    def test_folder_path(self):
        assert extract_wikilinks("[[folder/Note A]]") == ["folder/Note A"]

    def test_deduplication(self):
        assert extract_wikilinks("[[A]] text [[A]] more [[A]]") == ["A"]

    def test_no_links(self):
        assert extract_wikilinks("No links here") == []


class TestResolveWikilink:
    def test_exact_path(self):
        index = {"notes/hello.md": _note("notes/hello.md")}
        assert resolve_wikilink("notes/hello", index) == "notes/hello.md"

    def test_filename_only(self):
        index = {"folder/my-note.md": _note("folder/my-note.md")}
        assert resolve_wikilink("my-note", index) == "folder/my-note.md"

    def test_case_insensitive(self):
        index = {"My Note.md": _note("My Note.md")}
        assert resolve_wikilink("my note", index) == "My Note.md"

    def test_unresolved(self):
        index = {"exists.md": _note("exists.md")}
        assert resolve_wikilink("nonexistent", index) is None


class TestGetBacklinks:
    def test_finds_backlinks(self, vault):
        backlinks = get_backlinks("note1.md", vault.index)
        assert "note2.md" in backlinks
        assert "subfolder/note3.md" in backlinks

    def test_no_backlinks(self, vault):
        # MOC links to note1 and note2, but note3 only links to note1
        backlinks = get_backlinks("templates/daily.md", vault.index)
        assert backlinks == []


class TestGetGraph:
    def test_has_nodes_and_edges(self, vault):
        graph = get_graph(vault.index)
        assert len(graph["nodes"]) > 0
        assert len(graph["edges"]) > 0
        paths = [n["path"] for n in graph["nodes"]]
        assert "note1.md" in paths

    def test_edges_have_source_target(self, vault):
        graph = get_graph(vault.index)
        for edge in graph["edges"]:
            assert "source" in edge
            assert "target" in edge
            assert "resolved" in edge


class TestUpdateWikilinksAcrossVault:
    def test_renames_links(self, tmp_vault):
        from obsidian_mcp.vault import Vault
        v = Vault(tmp_vault)

        updated = update_wikilinks_across_vault(tmp_vault, "note1", "renamed_note", v.index)
        assert len(updated) > 0

        # Check that note2 now links to renamed_note
        content = (tmp_vault / "note2.md").read_text()
        assert "[[renamed_note]]" in content
        assert "[[note1]]" not in content
