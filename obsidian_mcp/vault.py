"""Vault class — file operations, indexing, caching, and search."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .frontmatter import get_body, get_frontmatter, has_frontmatter
from .links import extract_wikilinks, update_wikilinks_across_vault

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .embed_queue import EmbedQueue
    from .embeddings import EmbeddingBackend
    from .vector_store import VectorStore
    from .watcher import VaultWatcher


class NoteConflictError(RuntimeError):
    """Raised when write_note would clobber an edit made since the last read."""


@dataclass
class NoteIndex:
    """Cached metadata for a single note."""

    path: str
    title: str
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    modified: str = ""
    summary: str = ""
    frontmatter: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


INLINE_TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z0-9_/-]+)")


class Vault:
    """Central abstraction for an Obsidian vault."""

    def __init__(self, vault_path: str | Path):
        self.root = Path(vault_path).resolve()
        if not self.root.is_dir():
            raise ValueError(f"Vault path does not exist: {self.root}")
        self._index: dict[str, NoteIndex] | None = None
        self._index_lock = threading.RLock()
        # Tracks the disk mtime observed the last time this server handed the
        # content of a path to the model. Used by write_note to detect that an
        # external edit (Obsidian, git pull, etc.) happened in the meantime.
        self._last_read_mtime: dict[str, float] = {}
        self._watcher: "VaultWatcher" | None = None
        # Semantic retrieval stack — wired lazily so tests / non-semantic
        # usage don't pay for model downloads.
        self._embedder: "EmbeddingBackend" | None = None
        self._vector_store: "VectorStore" | None = None
        self._embed_queue: "EmbedQueue" | None = None

    # -- Path security --

    def _resolve_path(self, relative: str) -> Path:
        """Resolve relative path and ensure it stays within the vault."""
        resolved = (self.root / relative).resolve()
        if not str(resolved).startswith(str(self.root)):
            raise ValueError(f"Path escapes vault: {relative}")
        return resolved

    def _to_relative(self, absolute: Path) -> str:
        return str(absolute.relative_to(self.root))

    # -- Index --

    def _index_single(self, rel_path: str) -> NoteIndex:
        """Build index entry for a single note."""
        file_path = self.root / rel_path
        content = file_path.read_text(encoding="utf-8")
        fm = get_frontmatter(content)
        body = get_body(content) if has_frontmatter(content) else content

        # Tags: from frontmatter + inline
        tags = list(fm.get("tags", []))
        inline_tags = INLINE_TAG_RE.findall(body)
        for tag in inline_tags:
            if tag not in tags:
                tags.append(tag)

        # Summary: first non-empty paragraph
        summary = ""
        for line in body.strip().split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                summary = stripped[:200]
                break

        mtime = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()

        return NoteIndex(
            path=rel_path,
            title=fm.get("title", Path(rel_path).stem),
            tags=tags,
            links=extract_wikilinks(content),
            modified=mtime,
            summary=summary,
            frontmatter=fm,
        )

    def _build_index(self) -> dict[str, NoteIndex]:
        """Scan entire vault and build index."""
        index = {}
        for md_file in self.root.rglob("*.md"):
            rel = self._to_relative(md_file)
            try:
                index[rel] = self._index_single(rel)
            except Exception:
                continue  # skip unreadable files
        return index

    def rebuild_index(self) -> dict[str, NoteIndex]:
        """Force rebuild the index."""
        with self._index_lock:
            self._index = self._build_index()
            return self._index

    @property
    def index(self) -> dict[str, NoteIndex]:
        """Lazy-loaded vault index."""
        with self._index_lock:
            if self._index is None:
                self._index = self._build_index()
            return self._index

    # -- Index mutation hooks (called by MCP tools AND the filesystem watcher) --

    def _reindex_path(self, rel_path: str) -> None:
        """Re-read a single note from disk and update the index entry.

        Raises FileNotFoundError if the file no longer exists; the caller
        decides whether to translate that into a forget_path.
        """
        if (self.root / rel_path).is_dir():
            return
        entry = self._index_single(rel_path)
        with self._index_lock:
            # Initialise index lazily if the watcher fires before first access.
            if self._index is None:
                self._index = self._build_index()
            self._index[rel_path] = entry
        self._enqueue_embed(rel_path)

    def _forget_path(self, rel_path: str) -> None:
        """Drop a note from the index (deletion or move-source)."""
        with self._index_lock:
            if self._index is None:
                return
            self._index.pop(rel_path, None)
            self._last_read_mtime.pop(rel_path, None)
        self._embed_forget(rel_path)

    # -- Watcher lifecycle --

    def start_watching(self) -> "VaultWatcher":
        """Start a filesystem watcher that keeps the index in sync with
        out-of-band edits (Obsidian, git, manual CLI). Idempotent."""
        if self._watcher is not None:
            return self._watcher
        from .watcher import VaultWatcher

        # Prime the index before starting the watcher so a burst of initial
        # on_modified events doesn't race with _build_index.
        _ = self.index
        self._watcher = VaultWatcher(self)
        self._watcher.start()
        return self._watcher

    def stop_watching(self) -> None:
        if self._watcher is None:
            return
        self._watcher.stop()
        self._watcher = None

    # -- Semantic retrieval lifecycle --

    def enable_semantic(
        self,
        embedder: "EmbeddingBackend" | None = None,
        db_path: "str | None" = None,
    ) -> bool:
        """Wire up embeddings + vector store + background embed queue.

        Returns True if enabled. Safe to call multiple times — idempotent.
        Set ``OBSIDIAN_EMBEDDER=none`` (or pass embedder explicitly) to
        skip; all semantic tools will fall back to their lexical path.
        """
        import os

        if self._embed_queue is not None:
            return True
        if os.environ.get("OBSIDIAN_EMBEDDER", "").lower() == "none":
            return False

        from .embed_queue import EmbedQueue
        from .embeddings import get_backend
        from .vector_store import VectorStore

        backend = embedder or get_backend()
        # Pre-flight: verify the backend is actually usable before we open
        # the vector store and start the embed queue. Catches the common
        # "Ollama unreachable" / "model not pulled" cases at startup with
        # an actionable hint instead of a stack trace on first query.
        ok, detail = backend.health_check()
        if not ok:
            logger.warning(
                "embedding backend health check failed (%s); semantic "
                "features disabled. Detail: %s",
                backend.model_id,
                detail,
            )
            return False
        # Materialise the model early so dim is known before we open the store.
        backend.embed(["warmup"])
        store = VectorStore(
            db_path=db_path or (self.root / ".obsidian-mcp" / "index.db"),
            dim=backend.dim,
            model_id=backend.model_id,
        )
        q = EmbedQueue(vault=self, store=store, backend=backend)
        q.start()
        self._embedder = backend
        self._vector_store = store
        self._embed_queue = q
        # Reconcile drift since last shutdown: external edits, deletions, and
        # fresh installs all converge here. Cheap (one stat per note) and the
        # actual embedding runs on the background queue.
        self._reconcile_with_store()
        return True

    def _reconcile_with_store(self) -> dict:
        """Diff vector store against current vault state.

        Notes added or modified while the MCP was offline get re-enqueued;
        notes deleted while offline get forgotten. The body_hash short-circuit
        in the worker skips no-op re-embeds. Idempotent.
        """
        if self._vector_store is None:
            return {"enqueued": 0, "forgotten": 0}
        stored = self._vector_store.all_paths_with_mtime()
        current = self.index
        enqueued = 0
        forgotten = 0
        for rel_path in current:
            try:
                disk_mtime = (self.root / rel_path).stat().st_mtime
            except OSError:
                continue
            prev = stored.get(rel_path)
            if prev is None or prev < disk_mtime:
                self._enqueue_embed(rel_path)
                enqueued += 1
        for rel_path in stored:
            if rel_path not in current:
                self._embed_forget(rel_path)
                forgotten += 1
        if enqueued or forgotten:
            logger.info(
                "semantic reconcile: enqueued=%d forgotten=%d", enqueued, forgotten
            )
        return {"enqueued": enqueued, "forgotten": forgotten}

    def disable_semantic(self) -> None:
        if self._embed_queue is not None:
            self._embed_queue.stop()
            self._embed_queue = None
        if self._vector_store is not None:
            self._vector_store.close()
            self._vector_store = None
        self._embedder = None

    @property
    def semantic_enabled(self) -> bool:
        return self._embed_queue is not None

    def _enqueue_embed(self, rel_path: str) -> None:
        if self._embed_queue is not None:
            self._embed_queue.enqueue(rel_path)

    def _embed_forget(self, rel_path: str) -> None:
        if self._embed_queue is not None:
            self._embed_queue.forget(rel_path)

    def rebuild_embeddings(self) -> dict:
        """Full re-embed of every note in the vault. Idempotent; safe to re-run."""
        if not self.semantic_enabled:
            return {"enabled": False}
        total = 0
        for path in list(self.index):
            self._enqueue_embed(path)
            total += 1
        # Wait for the queue to drain so callers get a consistent count back.
        assert self._embed_queue is not None
        self._embed_queue.wait_idle(timeout=max(30.0, total * 0.5))
        assert self._vector_store is not None
        return {"enabled": True, "requested": total, **self._vector_store.stats()}

    def embedding_stats(self, wait: bool = False, timeout: float = 5.0) -> dict:
        """Return current index stats plus background-queue status.

        ``queue_pending`` and ``queue_idle`` let callers see when the
        store is still catching up to the vault — without them, a stats
        call right after an edit can look stale.

        Pass ``wait=True`` to block until the queue drains (or
        ``timeout`` elapses) before sampling, so the returned counts
        reflect the latest edits.
        """
        if self._vector_store is None:
            return {"enabled": False}
        if wait and self._embed_queue is not None:
            self._embed_queue.wait_idle(timeout=timeout)
        out = {"enabled": True, **self._vector_store.stats()}
        if self._embed_queue is not None:
            out["queue_pending"] = self._embed_queue.pending_count()
            out["queue_idle"] = self._embed_queue.is_idle()
        return out

    def semantic_search(
        self,
        query: str,
        k: int = 10,
        weights: dict[str, float] | None = None,
    ) -> list[dict]:
        """Vault-facing facade used by the MCP tool; empty list if disabled.

        ``weights`` lets callers (e.g. the demo UI) override re-rank
        weights for a single query without mutating env vars.
        """
        if not self.semantic_enabled:
            return []
        from .semantic import rank

        assert self._vector_store is not None and self._embedder is not None
        return rank(
            self, self._vector_store, self._embedder, query,
            limit=k, weights=weights,
        )

    # -- Auto-link suggestions --

    def suggest_links(
        self,
        path: str | None = None,
        limit: int = 25,
        min_score: float = 0.55,
    ) -> list[dict]:
        """Pairs of notes that look related but aren't wikilinked yet.

        Empty list if semantic is disabled (the algorithm needs the
        chunk vector store).
        """
        if not self.semantic_enabled:
            return []
        from .suggest import suggest_links

        assert self._vector_store is not None and self._embedder is not None
        return suggest_links(
            self, self._vector_store, self._embedder,
            path=path, limit=limit, min_score=min_score,
        )

    def dismiss_link_suggestion(self, source: str, target: str) -> None:
        """Hide this pair from future ``suggest_links`` results."""
        if self._vector_store is None:
            return
        self._vector_store.dismiss_pair(source, target)

    def undismiss_link_suggestion(self, source: str, target: str) -> None:
        if self._vector_store is None:
            return
        self._vector_store.undismiss_pair(source, target)

    def apply_link_suggestion(self, source: str, target: str) -> str:
        """Append a wikilink from ``source`` to ``target``.

        Inserts ``See also: [[target]]`` at the end of the source note.
        Idempotent: if any existing wikilink in the source already
        resolves to the target path (bare stem, full path, alias —
        whichever Obsidian would resolve), no edit is made.
        """
        from pathlib import Path as _Path

        from .links import extract_wikilinks, resolve_wikilink

        try:
            current = self.read_note(source)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"source note not found: {source}") from exc

        index = self.index
        if target not in index:
            raise FileNotFoundError(f"target note not found: {target}")

        target_stem = _Path(target).stem
        for link in extract_wikilinks(current):
            resolved = resolve_wikilink(link, index)
            if resolved == target:
                return f"already linked: {source} -> {target_stem}"

        wikilink = f"[[{target_stem}]]"
        self.append_note(source, f"\n\nSee also: {wikilink}\n")
        return f"linked: {source} -> {target_stem}"

    def find_related_semantic(self, content: str, limit: int = 10) -> list[dict]:
        """Semantic variant of find_related_notes. Empty list if disabled."""
        if not self.semantic_enabled:
            return []
        from .semantic import rank

        assert self._vector_store is not None and self._embedder is not None
        # Pass the raw content for both embed and signal extraction — tags and
        # wikilinks in the source text should boost their referenced notes.
        return rank(
            self, self._vector_store, self._embedder, content,
            query_for_signals=content, limit=limit,
        )

    # -- File operations --

    def read_note(self, path: str) -> str:
        """Read note content. Records mtime for later conflict detection on write."""
        file_path = self._resolve_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        content = file_path.read_text(encoding="utf-8")
        rel = self._to_relative(file_path)
        self._last_read_mtime[rel] = file_path.stat().st_mtime
        return content

    def write_note(self, path: str, content: str, force: bool = False) -> str:
        """Create or overwrite a note.

        If the file already exists on disk and has been modified since this
        server last handed its contents to the model via read_note(), the
        write is refused with NoteConflictError — typically because the user
        edited the note in Obsidian in the meantime. Pass force=True to
        override.
        """
        file_path = self._resolve_path(path)
        rel = self._to_relative(file_path)

        if file_path.exists() and not force:
            disk_mtime = file_path.stat().st_mtime
            last_seen = self._last_read_mtime.get(rel)
            # Only check if we have a baseline — a fresh write without any
            # prior read (e.g. create_note_from_template) is allowed.
            if last_seen is not None and disk_mtime > last_seen:
                raise NoteConflictError(
                    f"Note changed on disk since last read: {path}. "
                    f"Re-read the note to see the current content, or pass force=True to overwrite."
                )

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        # Update index and mtime baseline
        self._last_read_mtime[rel] = file_path.stat().st_mtime
        with self._index_lock:
            self.index[rel] = self._index_single(rel)
        self._enqueue_embed(rel)
        return f"Written: {path}"

    def append_note(self, path: str, content: str) -> str:
        """Append content to existing note, or create if missing."""
        file_path = self._resolve_path(path)
        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            file_path.write_text(existing + "\n" + content, encoding="utf-8")
        else:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        rel = self._to_relative(file_path)
        self._last_read_mtime[rel] = file_path.stat().st_mtime
        with self._index_lock:
            self.index[rel] = self._index_single(rel)
        self._enqueue_embed(rel)
        return f"Appended: {path}"

    def list_notes(self, folder: str = "") -> list[str]:
        """List all .md files in the vault or a subfolder."""
        search_path = self._resolve_path(folder) if folder else self.root
        if not search_path.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder}")
        return sorted(self._to_relative(f) for f in search_path.rglob("*.md"))

    def delete_note(self, path: str) -> str:
        """Delete a note."""
        file_path = self._resolve_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        file_path.unlink()
        rel = self._to_relative(file_path)
        self._forget_path(rel)
        return f"Deleted: {path}"

    def move_note(self, src: str, dest: str) -> str:
        """Move/rename a note and update all wikilinks across the vault."""
        src_path = self._resolve_path(src)
        dest_path = self._resolve_path(dest)

        if not src_path.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        if dest_path.exists():
            raise FileExistsError(f"Destination already exists: {dest}")

        old_stem = src_path.stem
        new_stem = dest_path.stem

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.rename(dest_path)

        # Update index
        old_rel = self._to_relative(src_path)
        new_rel = self._to_relative(dest_path)
        # For a rename, the body is unchanged — relabel the vector rows rather
        # than re-embedding. Must happen before _forget_path drops any trace.
        if self._vector_store is not None:
            try:
                self._vector_store.rename(old_rel, new_rel)
            except Exception:
                # Fall back: forget old, re-embed new.
                self._embed_forget(old_rel)
                self._enqueue_embed(new_rel)
        self._forget_path(old_rel)
        with self._index_lock:
            self.index[new_rel] = self._index_single(new_rel)

        # Update wikilinks across vault
        updated = update_wikilinks_across_vault(self.root, old_stem, new_stem, self.index)

        # Re-index updated files
        with self._index_lock:
            for p in updated:
                self.index[p] = self._index_single(p)
        # The linking notes' bodies changed — queue them for re-embed.
        for p in updated:
            self._enqueue_embed(p)

        return f"Moved: {src} -> {dest} (updated {len(updated)} linking notes)"

    # -- Search --

    def search_fulltext(self, query: str, limit: int = 50) -> list[dict]:
        """Full-text search across all notes."""
        results = []
        query_lower = query.lower()
        for md_file in self.root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if query_lower in line.lower():
                    results.append({
                        "path": self._to_relative(md_file),
                        "line": i,
                        "context": line.strip()[:200],
                    })
                    break  # one match per file
            if len(results) >= limit:
                break
        return results

    def search_by_tags(self, tags: list[str]) -> list[dict]:
        """Find notes with specific tags."""
        tags_lower = [t.lstrip("#").lower() for t in tags]
        results = []
        for path, note in self.index.items():
            note_tags = [t.lower() for t in note.tags]
            if any(t in note_tags for t in tags_lower):
                results.append({"path": path, "title": note.title, "tags": note.tags})
        return results

    def search_by_frontmatter(self, key: str, value: str) -> list[dict]:
        """Find notes where a frontmatter property matches a value."""
        value_lower = value.lower()
        results = []
        for path, note in self.index.items():
            fm_value = note.frontmatter.get(key)
            if fm_value is None:
                continue
            if isinstance(fm_value, list):
                if any(value_lower in str(v).lower() for v in fm_value):
                    results.append({"path": path, "title": note.title, key: fm_value})
            elif value_lower in str(fm_value).lower():
                results.append({"path": path, "title": note.title, key: fm_value})
        return results

    def search_by_date_range(
        self, start: str, end: str, date_field: str = "modified"
    ) -> list[dict]:
        """Find notes within a date range.

        date_field: 'modified' uses file mtime, anything else uses frontmatter.
        """
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        results = []

        for path, note in self.index.items():
            if date_field == "modified":
                note_date = date.fromisoformat(note.modified[:10])
            else:
                fm_date = note.frontmatter.get(date_field)
                if not fm_date:
                    continue
                try:
                    note_date = date.fromisoformat(str(fm_date)[:10])
                except ValueError:
                    continue

            if start_date <= note_date <= end_date:
                results.append({"path": path, "title": note.title, date_field: str(note_date)})

        return results

    def get_orphan_notes(self) -> list[dict]:
        """Find notes with zero backlinks — disconnected from the vault graph.

        A note is an orphan if no other note links to it via wikilinks.
        Templates and MOC files are excluded from results.
        """
        from .links import get_backlinks

        orphans = []
        for path, note in self.index.items():
            # Skip templates and MOC files
            if "templates/" in path.lower():
                continue
            if note.frontmatter.get("type", "").lower() == "moc":
                continue

            backlinks = get_backlinks(path, self.index)
            if not backlinks:
                orphans.append({
                    "path": path,
                    "title": note.title,
                    "tags": note.tags,
                    "outgoing_links": len(note.links),
                    "modified": note.modified,
                })

        return sorted(orphans, key=lambda x: x["modified"])
