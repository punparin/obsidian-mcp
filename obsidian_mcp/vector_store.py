"""SQLite + sqlite-vec chunk-level vector store.

Schema:

    notes           — one row per note (mtime, body hash, model)
    chunks          — one row per chunk (path FK, breadcrumb, offsets, text)
    chunk_vectors   — virtual table matching chunks.rowid

On a note update, ``replace_chunks(path, ...)`` deletes all existing
chunks + vectors for that path and re-inserts the new set in a single
transaction, so there's never a half-updated intermediate state.

SQLite is opened in WAL mode so background re-embeds don't block reads
from the MCP tool thread.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

import sqlite_vec

from .chunker import Chunk

logger = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path         TEXT PRIMARY KEY,
    mtime        REAL NOT NULL,
    body_hash    TEXT NOT NULL,
    embedded_at  REAL NOT NULL,
    model        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    rowid       INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    chunk_ix    INTEGER NOT NULL,
    heading     TEXT,
    char_start  INTEGER NOT NULL,
    char_end    INTEGER NOT NULL,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);

CREATE TABLE IF NOT EXISTS dismissed_link_suggestions (
    a            TEXT NOT NULL,
    b            TEXT NOT NULL,
    dismissed_at REAL NOT NULL,
    PRIMARY KEY (a, b)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    """Sort the pair so (A, B) and (B, A) hash to the same row."""
    return (a, b) if a < b else (b, a)


def _vec_table_ddl(dim: int) -> str:
    # The virtual-table dim is compiled into the DDL; any change requires rebuild.
    return f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(embedding FLOAT[{dim}]);"


class VectorStore:
    """Chunk-level vector store with note-level bookkeeping."""

    def __init__(self, db_path: Path | str, dim: int, model_id: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self.model_id = model_id
        # One connection per instance, guarded by a lock — sqlite-vec
        # virtual tables aren't re-entrant across threads on the same conn.
        self._lock = threading.RLock()
        self._conn = self._open()
        self._init_schema()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        """Create tables, then auto-reset if the embedding model or dim changed.

        On a model/dim change we drop the vec table (its dim is baked into
        DDL) and clear notes/chunks. The reconcile loop in ``Vault`` will
        see an empty store and re-enqueue every note for re-embedding.
        Dismissed link suggestions survive — they're tied to wikilink pairs,
        not embeddings.
        """
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            prior_model = self._get_meta_locked("embedding_model")
            prior_dim_str = self._get_meta_locked("embedding_dim")
            prior_dim = int(prior_dim_str) if prior_dim_str else None

            mismatch = prior_model is not None and (
                prior_model != self.model_id or prior_dim != self.dim
            )
            if mismatch:
                logger.warning(
                    "embedding model changed (stored=%s/dim=%s, current=%s/dim=%d) — "
                    "clearing index for re-embed",
                    prior_model,
                    prior_dim,
                    self.model_id,
                    self.dim,
                )
                self._conn.execute("DROP TABLE IF EXISTS chunk_vectors")
                self._conn.execute("DELETE FROM chunks")
                self._conn.execute("DELETE FROM notes")

            self._conn.execute(_vec_table_ddl(self.dim))
            self._set_meta_locked("embedding_model", self.model_id)
            self._set_meta_locked("embedding_dim", str(self.dim))

    def _get_meta_locked(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def _set_meta_locked(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- Writes ---------------------------------------------------------

    def replace_chunks(
        self,
        path: str,
        mtime: float,
        body_hash: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
    ) -> None:
        """Atomic: drop all chunks for path, insert new set."""
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks/vectors length mismatch: {len(chunks)} vs {len(vectors)}"
            )
        with self._lock, self._conn:
            # Delete existing chunks + their vectors.
            old_rowids = [
                r[0] for r in self._conn.execute(
                    "SELECT rowid FROM chunks WHERE path = ?", (path,)
                ).fetchall()
            ]
            if old_rowids:
                self._conn.executemany(
                    "DELETE FROM chunk_vectors WHERE rowid = ?",
                    [(r,) for r in old_rowids],
                )
                self._conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
            # Upsert note metadata.
            self._conn.execute(
                """
                INSERT INTO notes(path, mtime, body_hash, embedded_at, model)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    mtime=excluded.mtime,
                    body_hash=excluded.body_hash,
                    embedded_at=excluded.embedded_at,
                    model=excluded.model
                """,
                (path, mtime, body_hash, time.time(), self.model_id),
            )
            # Insert new chunks and their vectors, threading rowid through.
            for ix, (chunk, vec) in enumerate(zip(chunks, vectors)):
                if len(vec) != self.dim:
                    raise ValueError(
                        f"vector dim {len(vec)} != store dim {self.dim}"
                    )
                cur = self._conn.execute(
                    """
                    INSERT INTO chunks(path, chunk_ix, heading, char_start, char_end, text)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (path, ix, chunk.heading, chunk.char_start, chunk.char_end, chunk.text),
                )
                rowid = cur.lastrowid
                self._conn.execute(
                    "INSERT INTO chunk_vectors(rowid, embedding) VALUES (?, ?)",
                    (rowid, sqlite_vec.serialize_float32(vec)),
                )

    def forget(self, path: str) -> None:
        """Drop all traces of ``path`` (note + chunks + vectors)."""
        with self._lock, self._conn:
            old_rowids = [
                r[0] for r in self._conn.execute(
                    "SELECT rowid FROM chunks WHERE path = ?", (path,)
                ).fetchall()
            ]
            if old_rowids:
                self._conn.executemany(
                    "DELETE FROM chunk_vectors WHERE rowid = ?",
                    [(r,) for r in old_rowids],
                )
            self._conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
            self._conn.execute("DELETE FROM notes WHERE path = ?", (path,))

    def rename(self, old_path: str, new_path: str) -> None:
        """A move keeps chunks + vectors; just relabel the path FK."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE notes SET path = ? WHERE path = ?", (new_path, old_path)
            )
            self._conn.execute(
                "UPDATE chunks SET path = ? WHERE path = ?", (new_path, old_path)
            )

    # -- Reads ----------------------------------------------------------

    # -- Link-suggestion dismissals -------------------------------------

    def dismiss_pair(self, a: str, b: str) -> None:
        """Record (a, b) as a dismissed link suggestion. Order-independent."""
        ca, cb = _canonical_pair(a, b)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO dismissed_link_suggestions(a, b, dismissed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(a, b) DO UPDATE SET dismissed_at=excluded.dismissed_at
                """,
                (ca, cb, time.time()),
            )

    def undismiss_pair(self, a: str, b: str) -> None:
        ca, cb = _canonical_pair(a, b)
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM dismissed_link_suggestions WHERE a = ? AND b = ?",
                (ca, cb),
            )

    def get_all_dismissed(self) -> set[tuple[str, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT a, b FROM dismissed_link_suggestions"
            ).fetchall()
        return {(r[0], r[1]) for r in rows}

    def all_paths_with_mtime(self) -> dict[str, float]:
        """Snapshot of every embedded note's mtime — used for startup reconciliation."""
        with self._lock:
            rows = self._conn.execute("SELECT path, mtime FROM notes").fetchall()
        return {r[0]: r[1] for r in rows}

    def get_note(self, path: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT path, mtime, body_hash, embedded_at, model FROM notes WHERE path = ?",
                (path,),
            ).fetchone()
        if not row:
            return None
        return {
            "path": row[0],
            "mtime": row[1],
            "body_hash": row[2],
            "embedded_at": row[3],
            "model": row[4],
        }

    def knn(self, query_vec: list[float], k: int = 50) -> list[dict]:
        """Return top-k nearest chunks with cosine distance and metadata.

        Each row is ``{path, chunk_ix, heading, text, distance}``. Lower
        distance = closer; score = 1 - distance gives a friendly 0..1.
        """
        if len(query_vec) != self.dim:
            raise ValueError(f"query dim {len(query_vec)} != store dim {self.dim}")
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT c.path, c.chunk_ix, c.heading, c.text, v.distance
                FROM chunk_vectors v
                JOIN chunks c ON c.rowid = v.rowid
                WHERE v.embedding MATCH ?
                  AND k = {int(k)}
                ORDER BY v.distance
                """,
                (sqlite_vec.serialize_float32(query_vec),),
            ).fetchall()
        return [
            {
                "path": r[0],
                "chunk_ix": r[1],
                "heading": r[2] or "",
                "text": r[3],
                "distance": r[4],
            }
            for r in rows
        ]

    def stats(self) -> dict:
        with self._lock:
            notes = self._conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            chunks = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            last = self._conn.execute(
                "SELECT MAX(embedded_at) FROM notes"
            ).fetchone()[0]
        return {
            "notes": notes,
            "chunks": chunks,
            "model": self.model_id,
            "dim": self.dim,
            "last_embedded_at": last,
            "db_path": str(self.db_path),
        }
