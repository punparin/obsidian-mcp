"""Tests for vault-level ignore patterns."""

from __future__ import annotations

import pytest

from obsidian_mcp.ignore import IgnoreMatcher, build_matcher, load_ignore_config
from obsidian_mcp.vault import Vault


def _write_config(vault_path, body: str):
    cfg_dir = vault_path / ".obsidian-mcp"
    cfg_dir.mkdir(exist_ok=True)
    (cfg_dir / "config.yml").write_text(body, encoding="utf-8")


class TestIgnoreMatcher:
    def test_builtins_always_ignored(self):
        m = IgnoreMatcher()
        assert m.matches(".obsidian/workspace.json")
        assert m.matches(".git/HEAD")
        assert m.matches(".obsidian-mcp/index.db")
        assert m.matches(".trash/old.md")
        assert m.matches("note.swp")
        assert m.matches(".~lock-doc.md#")

    def test_regular_paths_not_ignored_by_default(self):
        m = IgnoreMatcher()
        assert not m.matches("notes/today.md")
        assert not m.matches("project.md")

    def test_user_globs_apply(self):
        m = IgnoreMatcher(["archive/**", "private/**", "*.draft.md"])
        assert m.matches("archive/2024/note.md")
        assert m.matches("private/secret.md")
        assert m.matches("post.draft.md")
        assert not m.matches("archive.md")
        assert not m.matches("notes/today.md")

    def test_directory_pattern_matches_nested(self):
        m = IgnoreMatcher(["scratch/"])
        assert m.matches("scratch/note.md")
        assert m.matches("scratch/sub/note.md")

    def test_empty_path_not_ignored(self):
        m = IgnoreMatcher(["**"])
        assert not m.matches("")


class TestLoadIgnoreConfig:
    def test_no_config_returns_empty(self, tmp_path):
        assert load_ignore_config(tmp_path) == []

    def test_reads_ignore_list(self, tmp_path):
        _write_config(tmp_path, "ignore:\n  - archive/**\n  - private/**\n")
        assert load_ignore_config(tmp_path) == ["archive/**", "private/**"]

    def test_missing_ignore_key_returns_empty(self, tmp_path):
        # Config file present but no `ignore:` key — fine, returns empty
        # so users can keep the file around for future settings without
        # being forced to declare ignores.
        _write_config(tmp_path, "actors:\n  - me\n")
        assert load_ignore_config(tmp_path) == []

    def test_empty_file_returns_empty(self, tmp_path):
        _write_config(tmp_path, "")
        assert load_ignore_config(tmp_path) == []

    def test_malformed_yaml_raises(self, tmp_path):
        _write_config(tmp_path, "ignore: [unclosed\n")
        with pytest.raises(ValueError, match="failed to parse"):
            load_ignore_config(tmp_path)

    def test_non_list_raises(self, tmp_path):
        _write_config(tmp_path, "ignore: archive\n")
        with pytest.raises(ValueError, match="must be a list"):
            load_ignore_config(tmp_path)

    def test_non_string_entry_raises(self, tmp_path):
        _write_config(tmp_path, "ignore:\n  - archive/**\n  - 42\n")
        with pytest.raises(ValueError, match="non-empty string"):
            load_ignore_config(tmp_path)


class TestVaultIgnoreIntegration:
    """Vault scans skip ignored paths, but explicit reads/writes still
    work — ignore is "don't surface in scans", not "deny access"."""

    def _make_vault(self, tmp_path, ignore_config: str | None = None):
        # Bootstrap files
        (tmp_path / "kept.md").write_text("# Kept\n", encoding="utf-8")
        (tmp_path / "archive").mkdir()
        (tmp_path / "archive" / "old.md").write_text("# Old\n", encoding="utf-8")
        (tmp_path / "private").mkdir()
        (tmp_path / "private" / "secret.md").write_text("# Secret\n", encoding="utf-8")
        if ignore_config:
            _write_config(tmp_path, ignore_config)
        return Vault(tmp_path)

    def test_index_skips_ignored_paths(self, tmp_path):
        v = self._make_vault(tmp_path, "ignore:\n  - archive/**\n  - private/**\n")
        paths = set(v.index.keys())
        assert "kept.md" in paths
        assert "archive/old.md" not in paths
        assert "private/secret.md" not in paths

    def test_list_notes_skips_ignored(self, tmp_path):
        v = self._make_vault(tmp_path, "ignore:\n  - archive/**\n")
        listed = v.list_notes()
        assert "kept.md" in listed
        assert "archive/old.md" not in listed

    def test_search_fulltext_skips_ignored(self, tmp_path):
        v = self._make_vault(tmp_path, "ignore:\n  - archive/**\n")
        # "Old" only appears in archive/old.md
        results = v.search_fulltext("Old")
        assert all(r["path"] != "archive/old.md" for r in results)

    def test_explicit_read_still_works_for_ignored_path(self, tmp_path):
        v = self._make_vault(tmp_path, "ignore:\n  - archive/**\n")
        # The model can still poke at an archived note when it explicitly
        # asks for the path — ignore only suppresses scans.
        content = v.read_note("archive/old.md")
        assert "Old" in content

    def test_builtin_dot_dirs_ignored_without_config(self, tmp_path):
        # No user config; built-ins should still kick in.
        (tmp_path / "real.md").write_text("# Real\n", encoding="utf-8")
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / ".obsidian" / "workspace.md").write_text("plugin junk", encoding="utf-8")
        v = Vault(tmp_path)
        assert "real.md" in v.index
        assert ".obsidian/workspace.md" not in v.index

    def test_no_config_keeps_default_behavior(self, tmp_path):
        # Without a config file, regular notes should all be indexed.
        v = self._make_vault(tmp_path, ignore_config=None)
        assert "kept.md" in v.index
        assert "archive/old.md" in v.index
        assert "private/secret.md" in v.index

    def test_malformed_config_raises_at_startup(self, tmp_path):
        _write_config(tmp_path, "ignore: [unclosed\n")
        with pytest.raises(ValueError, match="failed to parse"):
            Vault(tmp_path)

    def test_reindex_path_skips_ignored(self, tmp_path):
        v = self._make_vault(tmp_path, "ignore:\n  - archive/**\n")
        # Simulate the watcher trying to reindex an ignored path —
        # should be a no-op rather than crash or pollute the index.
        v._reindex_path("archive/old.md")
        assert "archive/old.md" not in v.index

    def test_ignore_predicate_is_public(self, tmp_path):
        v = self._make_vault(tmp_path, "ignore:\n  - archive/**\n")
        assert v.is_ignored("archive/old.md")
        assert not v.is_ignored("kept.md")


class TestBuildMatcher:
    def test_round_trip_via_disk(self, tmp_path):
        _write_config(tmp_path, "ignore:\n  - archive/**\n  - '*.draft.md'\n")
        m = build_matcher(tmp_path)
        assert m.matches("archive/old.md")
        assert m.matches("post.draft.md")
        assert not m.matches("notes/today.md")
        assert m.user_patterns == ("archive/**", "*.draft.md")
