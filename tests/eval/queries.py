"""Hand-labeled (query, expected_paths) pairs for retrieval eval.

Each query is a realistic search a user might type. ``expected_paths``
lists every note that *should* appear in the top-5 — usually one,
several when a topic legitimately spans multiple notes.

Mix of query styles by design:
- Paraphrase queries with no shared keywords → real semantic test
- Lexical queries → cheap regression sniff for the pipeline
- Wikilink-bearing → exercises graph rescore
- Disambiguation queries → ranker must pick the right sibling
  (e.g. one of two same-project meetings, one of two async notes)

Hit@k is calculated as: query passes if any expected path appears
in the top-k results. With multiple ``expected_paths``, only one
needs to land — that allows a paraphrase to legitimately match any
member of a topical sibling group.
"""

from __future__ import annotations

LABELED_QUERIES: list[tuple[str, list[str]]] = [
    # ── Paraphrase queries (no shared keywords with the target) ────────
    # 1. "asyncio.gather" wording absent — tests semantic match for the
    #    intro async note.
    (
        "run several coroutines in parallel and collect their results",
        ["python/async.md"],
    ),
    # 2. Decorator memoization paraphrase.
    (
        "cache results of a pure function so it isn't recomputed",
        ["python/decorators.md"],
    ),
    # 3. TypedDict described conceptually.
    (
        "annotate a dictionary's expected keys and value types",
        ["python/typing.md"],
    ),
    # 4. TF-IDF described without naming it.
    (
        "rank documents by how rare each search term is",
        ["retrieval/tfidf.md"],
    ),
    # 5. Embeddings concept without using the word "embedding".
    (
        "compare meaning of two pieces of text using vector distance",
        ["retrieval/embeddings.md", "retrieval/embedding-models.md"],
    ),
    # 6. Chunking concept paraphrased.
    (
        "split long markdown notes into pieces for vector search",
        ["retrieval/chunking.md"],
    ),
    # 7. Re-ranking with no shared keywords.
    (
        "boost search results using the wikilink graph after vector lookup",
        ["retrieval/reranking.md"],
    ),
    # 8. Cherry-pick paraphrase.
    (
        "copy a single commit from one branch to another",
        ["tools/git-cherry-pick.md"],
    ),
    # 9. Obsidian shortcut paraphrased.
    (
        "jump to a note quickly with the keyboard",
        ["tools/obsidian.md"],
    ),
    # ── Disambiguation queries (multiple sibling notes share vocab) ────
    # 10. Same-project meeting, second occurrence — tests whether date
    #     in the query nudges the right note to the top.
    (
        "follow-up retrieval standup 2026-04-22",
        ["meetings/2026-04-22.md"],
    ),
    # 11. Class decorators specifically — should beat the intro note.
    (
        "decorating a whole class with @dataclass-like behavior",
        ["python/decorators-advanced.md"],
    ),
    # 12. TaskGroup over plain gather — should pick the patterns note,
    #     not the intro one.
    (
        "task group cancellation propagation in asyncio",
        ["python/async-patterns.md"],
    ),
    # 13. Picking an embedding model — should beat the intro embeddings note.
    (
        "compare bge nomic and qwen for retrieval quality",
        ["retrieval/embedding-models.md"],
    ),
    # ── Wikilink-bearing query (graph signal must contribute) ──────────
    # 14. Explicit [[reranking]] in the query — graph signal should
    #     pin this even if cos_sim is marginal.
    (
        "see [[reranking]] for the pipeline overview",
        ["retrieval/reranking.md"],
    ),
    # ── Multi-target conceptual query (any sibling counts as a hit) ────
    # 15. Broad retrieval intent — any of the three retrieval notes
    #     would be a fine top-5 entry.
    (
        "how does semantic retrieval rank candidates",
        [
            "retrieval/embeddings.md",
            "retrieval/embedding-models.md",
            "retrieval/reranking.md",
        ],
    ),
    # ── Light lexical queries (regression sniff for plumbing) ──────────
    # 16. Direct rebase mention.
    (
        "interactive rebase to squash commits",
        ["tools/git-rebase.md"],
    ),
    # 17. MOC discovery.
    (
        "personal knowledge base map of content",
        ["MOC - Knowledge.md"],
    ),
    # 18. Archive recovery.
    (
        "deprecated retrieval design pre rerank",
        ["archive/old-design.md"],
    ),
]
