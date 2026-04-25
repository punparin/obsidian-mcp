"""Background debounced embedding worker.

Saves-on-type in Obsidian can fire many events per second. Embedding on
every event would stall the main thread and waste CPU. Instead, edits
enqueue a path onto a simple in-memory queue; a worker thread coalesces
rapid events into one re-embed per path.

The worker is best-effort: on failure it logs and moves on, because
never blocking the MCP tool loop is more important than guaranteeing
100% embed coverage in the presence of transient read errors.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
from typing import TYPE_CHECKING

from .chunker import chunk_body
from .embeddings import EmbeddingBackend, batched
from .frontmatter import get_body, has_frontmatter

if TYPE_CHECKING:
    from .vault import Vault
    from .vector_store import VectorStore

logger = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SEC = 0.2
DEFAULT_BATCH_SIZE = 32
STOP_SENTINEL = "__STOP__"


def body_hash(body: str) -> str:
    return hashlib.sha1(body.encode("utf-8", errors="replace")).hexdigest()


def chunks_for_note(vault: "Vault", rel_path: str) -> tuple[str, list] | None:
    """Read note body + produce chunks. Returns ``(body_hash, chunks)`` or None."""
    try:
        raw = (vault.root / rel_path).read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError) as exc:
        logger.debug("skip embed for %s: %s", rel_path, exc)
        return None
    body = get_body(raw) if has_frontmatter(raw) else raw
    chunks = chunk_body(body)
    return body_hash(body), chunks


class EmbedQueue:
    """Simple thread + queue. ``enqueue(path)`` is the only public surface
    besides ``start`` / ``stop`` / ``flush``."""

    def __init__(
        self,
        vault: "Vault",
        store: "VectorStore",
        backend: EmbeddingBackend,
        debounce: float = DEFAULT_DEBOUNCE_SEC,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self._vault = vault
        self._store = store
        self._backend = backend
        self._debounce = debounce
        self._batch_size = batch_size
        self._q: "queue.Queue[str]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pending: dict[str, float] = {}
        self._idle_event = threading.Event()
        self._idle_event.set()

    def start(self) -> None:
        if self._thread is not None:
            return
        t = threading.Thread(target=self._run, name="obsidian-embed-queue", daemon=True)
        t.start()
        self._thread = t

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is None:
            return
        self._q.put(STOP_SENTINEL)
        self._thread.join(timeout=timeout)
        self._thread = None

    def enqueue(self, rel_path: str) -> None:
        if rel_path == STOP_SENTINEL:
            return
        self._idle_event.clear()
        self._pending[rel_path] = time.monotonic() + self._debounce
        self._q.put(rel_path)

    def forget(self, rel_path: str) -> None:
        """Immediately drop a path from the store (deletes are not debounced)."""
        self._pending.pop(rel_path, None)
        try:
            self._store.forget(rel_path)
        except Exception as exc:
            logger.warning("forget %s failed: %s", rel_path, exc)

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Block until the queue has drained — useful for tests."""
        return self._idle_event.wait(timeout)

    # -- Worker --------------------------------------------------------

    def _run(self) -> None:
        """Single loop that juggles pending deadlines and new queue items.

        Key invariant: never block on ``q.get()`` while ``_pending`` is
        non-empty, or an item whose debounce has not yet expired will sit
        unprocessed forever. Instead, use a bounded timeout equal to the
        soonest deadline so we wake up for whichever event fires first.
        """
        while True:
            try:
                if not self._pending:
                    item = self._q.get()  # block until something arrives
                    if item == STOP_SENTINEL:
                        return
                    self._pending[item] = time.monotonic() + self._debounce
                else:
                    now = time.monotonic()
                    soonest = min(self._pending.values())
                    wait_for = max(0.01, soonest - now)
                    try:
                        item = self._q.get(timeout=wait_for)
                        if item == STOP_SENTINEL:
                            return
                        self._pending[item] = time.monotonic() + self._debounce
                    except queue.Empty:
                        pass  # deadline tick — fall through to _take_ready
                self._coalesce_pending()
                ready = self._take_ready()
                if ready:
                    self._process_batch(ready)
                if not self._pending:
                    self._idle_event.set()
            except Exception:
                logger.exception("embed queue worker iteration failed")

    def _coalesce_pending(self) -> None:
        while True:
            try:
                more = self._q.get_nowait()
            except queue.Empty:
                return
            if more == STOP_SENTINEL:
                # Re-insert so the main loop sees it.
                self._q.put(STOP_SENTINEL)
                return
            self._pending[more] = time.monotonic() + self._debounce

    def _take_ready(self) -> list[str]:
        now = time.monotonic()
        ready: list[str] = []
        for path, due_at in list(self._pending.items()):
            if due_at <= now:
                ready.append(path)
                del self._pending[path]
        return ready

    def _process_batch(self, paths: list[str]) -> None:
        # Step 1: gather (path, hash, chunks) for still-existing notes.
        prepared: list[tuple[str, str, list]] = []
        for p in paths:
            try:
                existing = self._store.get_note(p)
                result = chunks_for_note(self._vault, p)
                if result is None:
                    # File vanished; drop the vector rows if present.
                    self._store.forget(p)
                    continue
                h, chunks = result
                if existing and existing.get("body_hash") == h:
                    # Content unchanged — skip the embed work.
                    continue
                if not chunks:
                    # Empty body; forget any prior chunks.
                    self._store.forget(p)
                    continue
                prepared.append((p, h, chunks))
            except Exception:
                logger.exception("prepare failed for %s", p)
        if not prepared:
            return

        # Step 2: flatten all chunk texts for batched embedding, track origin.
        flat_texts: list[str] = []
        owners: list[tuple[int, int]] = []  # (note_ix, chunk_ix_within_note)
        for note_ix, (_, _, chunks) in enumerate(prepared):
            for chunk_ix, ch in enumerate(chunks):
                flat_texts.append(ch.text)
                owners.append((note_ix, chunk_ix))

        try:
            vectors: list[list[float]] = []
            for batch in batched(flat_texts, self._batch_size):
                vectors.extend(self._backend.embed(batch))
        except Exception:
            logger.exception("embedder failed, dropping batch")
            return

        # Step 3: regroup vectors by note and upsert atomically per note.
        by_note: dict[int, list[list[float]]] = {i: [] for i in range(len(prepared))}
        for (note_ix, _), vec in zip(owners, vectors):
            by_note[note_ix].append(vec)

        for note_ix, (path, h, chunks) in enumerate(prepared):
            try:
                mtime = (self._vault.root / path).stat().st_mtime
                self._store.replace_chunks(
                    path=path, mtime=mtime, body_hash=h,
                    chunks=chunks, vectors=by_note[note_ix],
                )
            except FileNotFoundError:
                self._store.forget(path)
            except Exception:
                logger.exception("replace_chunks failed for %s", path)
