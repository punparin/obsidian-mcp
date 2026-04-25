"""Semantic query pipeline — embed + kNN + graph-aware re-rank.

Ranking formula (weights all env-tunable, defaults favour the user's
explicit graph over marginal semantic differences):

    final = w_sem     * cos_sim                         # 0..1
          + w_link    * wikilink_match                  # 0 or 1
          + w_tag     * jaccard(shared_tags)            # 0..1
          + w_neighbor* 1 / max(hops, 1)                # 0..1 if within 2 hops
          + w_recency * exp(-age_days / halflife)       # 0..1

Chunk-level kNN is aggregated to note-level before re-rank: each note
appears once with its best chunk's score + snippet.
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .embeddings import EmbeddingBackend

if TYPE_CHECKING:
    from .vault import NoteIndex, Vault
    from .vector_store import VectorStore


DEFAULT_WEIGHTS = {
    "sem": 1.00,
    "link": 0.40,
    "tag": 0.30,
    "neighbor": 0.15,
    "recency": 0.10,
}
DEFAULT_HALF_LIFE_DAYS = 180.0
DEFAULT_KNN_K = 50
DEFAULT_NEIGHBOR_HOPS = 2

WIKILINK_RE = re.compile(r"\[\[([^\]]+?)\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z0-9_/-]+)")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _weights() -> dict[str, float]:
    return {
        "sem": _env_float("OBSIDIAN_W_SEM", DEFAULT_WEIGHTS["sem"]),
        "link": _env_float("OBSIDIAN_W_LINK", DEFAULT_WEIGHTS["link"]),
        "tag": _env_float("OBSIDIAN_W_TAG", DEFAULT_WEIGHTS["tag"]),
        "neighbor": _env_float("OBSIDIAN_W_NEIGHBOR", DEFAULT_WEIGHTS["neighbor"]),
        "recency": _env_float("OBSIDIAN_W_RECENCY", DEFAULT_WEIGHTS["recency"]),
    }


def _extract_query_signals(content: str) -> dict[str, set[str]]:
    """Pull out wikilink targets and tags from a query blob."""
    wikilinks = {m.group(1).split("|", 1)[0].split("#", 1)[0].strip().lower() for m in WIKILINK_RE.finditer(content)}
    wikilinks.discard("")
    tags = {m.group(1).lower() for m in TAG_RE.finditer(content)}
    return {"wikilinks": wikilinks, "tags": tags}


def _age_days(iso_modified: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_modified)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    return max((now - dt).total_seconds() / 86400.0, 0.0)


def _neighbor_set(vault: "Vault", seed_paths: set[str], max_hops: int) -> dict[str, int]:
    """BFS the vault link graph from ``seed_paths``; return {path: hops}."""
    if not seed_paths or max_hops <= 0:
        return {}
    index: dict[str, "NoteIndex"] = vault.index

    # Map wikilink stem -> path for O(1) lookups.
    stem_to_path: dict[str, str] = {}
    for p in index:
        stem_to_path.setdefault(Path(p).stem.lower(), p)

    seeds: set[str] = set()
    for sp in seed_paths:
        seeds.add(sp)
        # If the seed was given as a stem (from a wikilink), resolve it.
        candidate = stem_to_path.get(sp.lower())
        if candidate:
            seeds.add(candidate)

    hops: dict[str, int] = {s: 0 for s in seeds if s in index}
    frontier = list(hops)
    for depth in range(1, max_hops + 1):
        next_frontier: list[str] = []
        for path in frontier:
            note = index.get(path)
            if not note:
                continue
            for link in note.links:
                target = stem_to_path.get(link.split("#", 1)[0].lower())
                if target and target not in hops:
                    hops[target] = depth
                    next_frontier.append(target)
        if not next_frontier:
            break
        frontier = next_frontier
    return hops


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def rank(
    vault: "Vault",
    store: "VectorStore",
    backend: EmbeddingBackend,
    query_text: str,
    *,
    query_for_signals: str | None = None,
    limit: int = 10,
    knn_k: int = DEFAULT_KNN_K,
    exclude_path: str | None = None,
) -> list[dict]:
    """Embed ``query_text``, retrieve candidate chunks, aggregate to notes,
    graph-rescore, and return ``limit`` ranked notes.

    ``query_for_signals`` (defaults to ``query_text``) is scanned for
    wikilinks + tags; a short raw query like "graph retrieval" carries no
    graph signal, but piping the full content of an inbox item here lets
    the explicit structure dominate.
    """
    if not query_text.strip():
        return []

    w = _weights()
    signals_blob = query_for_signals if query_for_signals is not None else query_text
    signals = _extract_query_signals(signals_blob)

    query_vec = backend.embed([query_text])[0]
    hits = store.knn(query_vec, k=knn_k)
    if not hits:
        return []

    # Aggregate chunks -> best chunk per note.
    best_chunk_by_path: dict[str, dict] = {}
    for h in hits:
        path = h["path"]
        if exclude_path and path == exclude_path:
            continue
        existing = best_chunk_by_path.get(path)
        if existing is None or h["distance"] < existing["distance"]:
            best_chunk_by_path[path] = h

    index = vault.index
    neighbors = _neighbor_set(vault, signals["wikilinks"], max_hops=DEFAULT_NEIGHBOR_HOPS)

    ranked: list[dict] = []
    for path, chunk_hit in best_chunk_by_path.items():
        note = index.get(path)
        if note is None:
            # Index and store disagreed briefly (stale vector); skip gracefully.
            continue

        cos_sim = max(0.0, 1.0 - float(chunk_hit["distance"]))

        note_stem = Path(path).stem.lower()
        link_bonus = 1.0 if note_stem in signals["wikilinks"] else 0.0

        note_tags_lower = {t.lower() for t in note.tags}
        tag_bonus = _jaccard(note_tags_lower, signals["tags"])

        hops = neighbors.get(path)
        if hops is None or hops == 0:
            neighbor_bonus = 0.0
        else:
            neighbor_bonus = 1.0 / hops  # 1-hop = 1.0, 2-hops = 0.5

        recency = math.exp(-_age_days(note.modified) / DEFAULT_HALF_LIFE_DAYS)

        final = (
            w["sem"] * cos_sim
            + w["link"] * link_bonus
            + w["tag"] * tag_bonus
            + w["neighbor"] * neighbor_bonus
            + w["recency"] * recency
        )

        ranked.append({
            "path": path,
            "title": note.title,
            "score": round(final, 4),
            "cos_sim": round(cos_sim, 4),
            "signals": {
                "wikilink_match": bool(link_bonus),
                "tag_jaccard": round(tag_bonus, 3),
                "neighbor_hops": hops,
                "recency": round(recency, 3),
            },
            "snippet": chunk_hit["text"][:300],
            "heading": chunk_hit["heading"],
            "tags": note.tags,
        })

    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked[:limit]
