"""Filesystem watcher tests.

These tests rely on real filesystem events propagating through watchdog's
inotify backend on Linux. Each test polls for up to ~2s to let events land.
"""

from __future__ import annotations

import time

import pytest

from obsidian_mcp.vault import Vault


def _wait_for(predicate, timeout: float = 2.0, interval: float = 0.05) -> bool:
    """Poll predicate until it returns truthy, or timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def watched_vault(tmp_vault):
    vault = Vault(tmp_vault)
    vault.start_watching()
    try:
        yield vault
    finally:
        vault.stop_watching()


class TestWatcherLifecycle:
    def test_start_is_idempotent(self, watched_vault):
        first = watched_vault._watcher
        watched_vault.start_watching()
        assert watched_vault._watcher is first
        assert first.is_alive

    def test_stop_releases_observer(self, tmp_vault):
        vault = Vault(tmp_vault)
        watcher = vault.start_watching()
        assert watcher.is_alive
        vault.stop_watching()
        assert vault._watcher is None
        assert not watcher.is_alive


class TestExternalCreate:
    def test_new_file_appears_in_index(self, watched_vault, tmp_vault):
        (tmp_vault / "fresh.md").write_text("---\ntitle: Fresh\n---\nHello.")
        assert _wait_for(lambda: "fresh.md" in watched_vault.index), (
            "watcher did not pick up new file within timeout"
        )
        assert watched_vault.index["fresh.md"].title == "Fresh"

    def test_nested_new_file(self, watched_vault, tmp_vault):
        (tmp_vault / "deep").mkdir()
        (tmp_vault / "deep" / "nested.md").write_text("content")
        assert _wait_for(lambda: "deep/nested.md" in watched_vault.index)


class TestExternalModify:
    def test_edit_refreshes_index_entry(self, watched_vault, tmp_vault):
        # Prime the index.
        assert watched_vault.index["note1.md"].title == "Note One"
        (tmp_vault / "note1.md").write_text(
            "---\ntitle: Note One Edited\n---\nEdited from outside.\n"
        )
        assert _wait_for(
            lambda: watched_vault.index.get("note1.md")
            and watched_vault.index["note1.md"].title == "Note One Edited"
        )


class TestExternalDelete:
    def test_delete_removes_from_index(self, watched_vault, tmp_vault):
        assert "note1.md" in watched_vault.index
        (tmp_vault / "note1.md").unlink()
        assert _wait_for(lambda: "note1.md" not in watched_vault.index)


class TestIgnoredPaths:
    def test_dotfolder_noise_ignored(self, watched_vault, tmp_vault):
        (tmp_vault / ".obsidian").mkdir(exist_ok=True)
        (tmp_vault / ".obsidian" / "workspace.json").write_text("{}")
        # Give watchdog a beat to see the event (should be ignored).
        time.sleep(0.2)
        assert ".obsidian/workspace.json" not in watched_vault.index

    def test_non_markdown_ignored(self, watched_vault, tmp_vault):
        (tmp_vault / "notes.txt").write_text("plain text")
        time.sleep(0.2)
        assert "notes.txt" not in watched_vault.index
