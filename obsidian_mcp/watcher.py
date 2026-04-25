"""Filesystem watcher — keep the Vault index in sync with out-of-band edits.

The MCP server holds an in-memory index built once at startup. Without a
watcher, any edit made directly in Obsidian (or any tool outside this server)
silently diverges from the index until the process restarts. The watcher
closes that gap by listening for filesystem events and applying targeted
index updates on the same event loop-agnostic worker thread that watchdog
provides.

Only `.md` files are tracked. Hidden files and tempfile patterns
(e.g. `.obsidian/`, `.git/`, `.swp`, `*.tmp`, `.~lock*`) are ignored — they
produce noise without ever being part of the vault graph.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from .vault import Vault

logger = logging.getLogger(__name__)

IGNORED_DIRS = {".obsidian", ".git", ".trash", ".stversions"}


def _is_ignored(rel_path: str) -> bool:
    """Skip paths under hidden/infra directories, tempfiles, and non-markdown."""
    parts = Path(rel_path).parts
    if any(part in IGNORED_DIRS for part in parts):
        return True
    if any(part.startswith(".") for part in parts):
        return True
    name = Path(rel_path).name
    if name.endswith((".swp", ".tmp", ".swx")):
        return True
    if name.startswith(".~lock"):
        return True
    return not name.endswith(".md")


class _VaultEventHandler(FileSystemEventHandler):
    """Translate watchdog events into targeted Vault index mutations."""

    def __init__(self, vault: "Vault"):
        self._vault = vault

    def _rel(self, src_path: str) -> str | None:
        abs_path = Path(src_path).resolve()
        try:
            rel = str(abs_path.relative_to(self._vault.root))
        except ValueError:
            return None
        if _is_ignored(rel):
            return None
        return rel

    def _reindex(self, rel: str) -> None:
        try:
            self._vault._reindex_path(rel)
        except FileNotFoundError:
            self._vault._forget_path(rel)
        except Exception as exc:
            # Partial writes / transient read errors shouldn't crash the watcher thread.
            logger.warning("watcher reindex failed for %s: %s", rel, exc)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        rel = self._rel(event.src_path)
        if rel:
            self._reindex(rel)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        rel = self._rel(event.src_path)
        if rel:
            self._reindex(rel)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        rel = self._rel(event.src_path)
        if rel:
            self._vault._forget_path(rel)

    def on_moved(self, event) -> None:
        if event.is_directory:
            return
        old_rel = self._rel(event.src_path)
        new_rel = self._rel(event.dest_path) if hasattr(event, "dest_path") else None
        if old_rel:
            self._vault._forget_path(old_rel)
        if new_rel:
            self._reindex(new_rel)


class VaultWatcher:
    """Lifecycle wrapper around a watchdog Observer bound to a Vault."""

    def __init__(self, vault: "Vault"):
        self._vault = vault
        self._observer: Observer | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._observer is not None:
                return
            observer = Observer()
            observer.schedule(_VaultEventHandler(self._vault), str(self._vault.root), recursive=True)
            observer.daemon = True
            observer.start()
            self._observer = observer
            logger.info("vault watcher started on %s", self._vault.root)

    def stop(self, timeout: float = 2.0) -> None:
        with self._lock:
            if self._observer is None:
                return
            observer = self._observer
            self._observer = None
        observer.stop()
        observer.join(timeout=timeout)
        logger.info("vault watcher stopped")

    @property
    def is_alive(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
