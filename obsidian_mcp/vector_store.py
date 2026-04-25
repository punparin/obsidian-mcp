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
"""


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
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            self._conn.execute(_vec_table_ddl(self.dim))
            # If a prior run used a different dim, vec0 will fail at insert —
            # better to catch the mismatch at open time and tell the user.
            row = self._conn.execute(
                "SELECT model FROM notes LIMIT 1"
            ).fetchone()
            if row and row[0] and row[0] != self.model_id:
                logger.warning(
                    "vector store model mismatch (stored=%s, current=%s) — "
                    "run rebuild_embeddings to re-populate",
                    row[0],
                    self.model_id,
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
