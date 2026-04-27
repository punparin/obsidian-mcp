"""Auto-link suggestions: notes that should probably be wikilinked but aren't.

Algorithm:

1. For each source note, embed its body (first ~2000 chars) and pull the
   top-K nearest neighbors from the chunk vector store.
2. Aggregate the chunk hits to one best-chunk-per-target.
3. Drop pairs that are already wikilinked (either direction), self-pairs,
   and pairs the user has previously dismissed.
4. Score = ``w_sem * cos_sim + w_tag * tag_jaccard``. Above ``min_score``
   makes the cut.
5. Deduplicate by canonical pair (so we never suggest A→B and B→A
   separately) and return top ``limit`` sorted descending.

The whole thing is one explicit ``suggest_links`` call, not a background
job — the user decides when to spend the embed budget.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .embeddings import EmbeddingBackend, batched
from .frontmatter import get_body, has_frontmatter
from .links import resolve_wikilink
from .vector_store import _canonical_pair

if TYPE_CHECKING:
    from .vault import Vault
    from .vector_store import VectorStore

logger = logging.getLogger(__name__)

DEFAULT_MIN_SCORE = 0.55
DEFAULT_LIMIT = 25
DEFAULT_K_PER_NOTE = 15
DEFAULT_BODY_CAP = 2000
DEFAULT_BATCH = 32
W_SEM = 0.7
W_TAG = 0.3
SNIPPET_LEN = 360  # chars per side — long enough to read context, short enough to skim


def _tag_jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _all_linked_pairs(index: dict) -> set[tuple[str, str]]:
    """Every wikilinked pair, treated as undirected (canonical order).

    A→B and B→A both produce the same canonical key, so we only need to
    check one direction when filtering out already-linked pairs.
    """
    out: set[tuple[str, str]] = set()
    for path, note in index.items():
        for link in note.links:
            resolved = resolve_wikilink(link, index)
            if resolved and resolved != path:
                out.add(_canonical_pair(path, resolved))
    return out


def suggest_links(
    vault: "Vault",
    store: "VectorStore",
    backend: EmbeddingBackend,
    *,
    path: str | None = None,
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    k_per_note: int = DEFAULT_K_PER_NOTE,
) -> list[dict]:
    """Find note pairs that look related but aren't yet wikilinked.

    ``path``: scan only this note's neighborhood. ``None`` = full vault.
    """
    index = vault.index
    if path is not None:
        if path not in index:
            return []
        sources = [path]
    else:
        sources = list(index.keys())

    linked_pairs = _all_linked_pairs(index)

    # Build (path, body_for_embedding, source_snippet) for each source.
    # The snippet is what the explorer card shows for the source side, so
    # keep it shorter than the embed cap.
    prepared: list[tuple[str, str, str]] = []
    source_snippets: dict[str, str] = {}
    for src in sources:
        try:
            raw = (vault.root / src).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        body = get_body(raw) if has_frontmatter(raw) else raw
        body = body.strip()
        if not body:
            continue
        note = index.get(src)
        if note is None:
            continue
        source_snippets[src] = body[:SNIPPET_LEN]
        prepared.append((src, body[:DEFAULT_BODY_CAP], source_snippets[src]))

    if not prepared:
        return []

    # Batch embed all source bodies in one pass.
    texts = [body for _, body, _ in prepared]
    src_vectors: list[list[float]] = []
    for batch in batched(texts, DEFAULT_BATCH):
        src_vectors.extend(backend.embed(batch))

    dismissed = store.get_all_dismissed()

    # candidates[canonical_pair] = best record so far
    candidates: dict[tuple[str, str], dict] = {}
    for (src, _, _), src_vec in zip(prepared, src_vectors):
        hits = store.knn(src_vec, k=k_per_note)
        # Aggregate hits to best-per-target.
        best_per_target: dict[str, tuple[float, dict]] = {}
        for hit in hits:
            tgt = hit["path"]
            if tgt == src:
                continue
            pair_check = _canonical_pair(src, tgt)
            if pair_check in linked_pairs:
                continue
            cos_sim = max(0.0, 1.0 - float(hit["distance"]))
            existing_best = best_per_target.get(tgt)
            if existing_best is None or cos_sim > existing_best[0]:
                best_per_target[tgt] = (cos_sim, hit)

        src_note = index[src]
        src_tags = {t.lower() for t in src_note.tags}

        for tgt, (cos_sim, hit) in best_per_target.items():
            pair = _canonical_pair(src, tgt)
            if pair in dismissed:
                continue
            tgt_note = index.get(tgt)
            if tgt_note is None:
                continue
            tgt_tags = {t.lower() for t in tgt_note.tags}
            tag_jacc = _tag_jaccard(src_tags, tgt_tags)
            score = W_SEM * cos_sim + W_TAG * tag_jacc
            if score < min_score:
                continue
            # If we already have a record for this pair, keep the higher-scoring
            # direction so the snippet/source is the more informative side.
            existing_record = candidates.get(pair)
            if existing_record is not None and existing_record["score"] >= score:
                continue
            target_snippet = hit["text"][:SNIPPET_LEN]
            candidates[pair] = {
                "source": src,
                "target": tgt,
                "source_title": src_note.title,
                "target_title": tgt_note.title,
                "score": round(score, 4),
                "cos_sim": round(cos_sim, 4),
                "tag_jaccard": round(tag_jacc, 3),
                "shared_tags": sorted(src_tags & tgt_tags),
                "source_snippet": source_snippets.get(src, ""),
                "target_snippet": target_snippet,
                # Back-compat alias for the old single-snippet shape — the
                # matched chunk has always come from the target side.
                "snippet": target_snippet,
                "heading": hit.get("heading", ""),
            }

    out = list(candidates.values())
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:limit]
