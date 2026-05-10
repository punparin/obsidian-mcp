"""Synthetic vault used by the retrieval eval harness.

Nineteen notes across Python, retrieval, dev tooling, and meetings.
Several topics intentionally have **multiple** notes that share
vocabulary (two async notes, two decorator notes, three retrieval
notes that all talk about embeddings, two same-project meetings on
different dates). That makes ranking non-trivial: the embedder has
to discriminate between sibling notes, not just pick the only
relevant one.

Wikilinks and tags are populated where realistic so the graph signals
in ``rank()`` are exercised, not just raw cos_sim.

Keep notes short — long bodies would force the chunker to split and
make hit attribution noisier.
"""

from __future__ import annotations

from pathlib import Path

NOTES: dict[str, str] = {
    "python/async.md": """\
---
title: Python async/await
tags: [python, async]
---

# asyncio basics

Use `asyncio.gather` to run concurrent tasks and collect their
results. The event loop schedules coroutines cooperatively;
`await` yields control back to the loop while I/O is in flight.

For CPU-bound work, prefer `asyncio.to_thread` so the event loop
stays responsive.
""",
    "python/decorators.md": """\
---
title: Python decorators
tags: [python]
---

# Decorators

A decorator wraps a function with new behavior. Common stdlib
decorators: `@functools.cache`, `@functools.cached_property`,
`@property`, `@staticmethod`. Decorators preserve metadata via
`functools.wraps`.

Use `@cached` to memoize pure functions; clear with `.cache_clear()`.
""",
    "python/decorators-advanced.md": """\
---
title: Advanced decorator patterns
tags: [python]
---

# Parameterized and class decorators

A decorator factory takes arguments and returns the actual
decorator: `@retry(times=3)`. Class decorators receive the class
object and can rewrite it — `@dataclass` is the canonical example.

For stacking, the bottom-most decorator is applied first. Use
`__wrapped__` to walk the chain.
""",
    "python/async-patterns.md": """\
---
title: async patterns
tags: [python, async]
---

# Cancellation and error handling

`asyncio.TaskGroup` (3.11+) supersedes manual `gather` for new code:
exceptions in any child cancel siblings deterministically. Use
`asyncio.shield` to protect a critical await from cancellation.

For long-running services, install a signal handler that calls
`task.cancel()` on SIGTERM rather than letting the loop crash.
""",
    "python/typing.md": """\
---
title: Python typing
tags: [python, typing]
---

# Type hints

`TypedDict` describes dictionaries with a fixed shape. `Generic`
and `TypeVar` enable parameterized types. `Protocol` defines
structural typing — duck typing with static checking.

Prefer `from __future__ import annotations` for forward references
without quoting.
""",
    "retrieval/tfidf.md": """\
---
title: TF-IDF
tags: [retrieval, ranking]
---

# TF-IDF

Term frequency times inverse document frequency. A classic lexical
ranker that rewards rare terms in the query that appear in a
document. Cheap, deterministic, no embeddings required.

Limitation: synonyms and paraphrases score zero overlap.
""",
    "retrieval/embeddings.md": """\
---
title: Embeddings
tags: [retrieval, ranking]
---

# Sentence embeddings

Vectors that capture semantic meaning so that paraphrases land near
each other in cosine space. Cosine similarity ranks candidate chunks
against the query vector.

Embeddings collapse synonyms (unlike TF-IDF) but blur fine-grained
distinctions on short queries.
""",
    "retrieval/embedding-models.md": """\
---
title: Picking an embedding model
tags: [retrieval, ranking]
---

# Model selection

Trade-offs across popular sentence-embedding models. BAAI/bge-small
is a fast English-only baseline; bge-m3 adds multilingual and long
context. nomic-embed sits between them on quality and dimension.
Larger models like qwen3-embedding score higher on MTEB but cost
more storage and slower kNN.

Switch only when you have an eval set that says the new one wins.
""",
    "retrieval/chunking.md": """\
---
title: Chunking markdown for retrieval
tags: [retrieval]
---

# Markdown-aware chunking

Split notes at H2/H3 boundaries so each chunk is topically coherent.
Pack adjacent paragraphs up to ~1600 chars to keep enough context
for the embedder without diluting the signal.

Overlap one paragraph between chunks so a query landing on a
boundary still finds its nearest semantic neighbor.
""",
    "retrieval/reranking.md": """\
---
title: Re-ranking
tags: [retrieval, ranking]
---

# Re-ranking pipeline

After kNN over [[embeddings]] returns candidates, a re-ranker
combines [[tfidf]] overlap, graph signals, and recency to produce
the final ordering. Weights are tunable per deployment.

Graph signals: wikilink match, shared tags, neighbor distance.
""",
    "tools/git-rebase.md": """\
---
title: git rebase
tags: [git, tools]
---

# Interactive rebase

`git rebase -i HEAD~5` opens an editor where you can squash, fixup,
reword, or drop commits. Useful for cleaning a feature branch
before review.

Force-push with `--force-with-lease` to avoid clobbering teammates.
""",
    "tools/git-cherry-pick.md": """\
---
title: git cherry-pick
tags: [git, tools]
---

# Cherry-picking commits

`git cherry-pick <sha>` replays a single commit from another branch
onto the current one. Useful for back-porting a hotfix without
merging the whole feature branch.

Use `--no-commit` to stage the change and amend before recording it.
""",
    "tools/obsidian.md": """\
---
title: Obsidian shortcuts
tags: [obsidian, tools]
---

# Obsidian power user

Open quick switcher with `Cmd+O`. Toggle the command palette with
`Cmd+P`. Wrap selection in `[[wikilinks]]` with `Cmd+L` (custom).

Daily notes are templated from `templates/daily.md`.
""",
    "meetings/2026-04-15.md": """\
---
title: Retrieval project standup
date: 2026-04-15
tags: [meeting]
---

# Standup 2026-04-15

Discussed the [[reranking]] pipeline rollout. Action items: tune
re-rank weights, add eval harness with labeled queries, ship the
groundedness self-check tool.

Next sync: 2026-04-22.
""",
    "meetings/2026-04-22.md": """\
---
title: Retrieval project standup
date: 2026-04-22
tags: [meeting]
---

# Standup 2026-04-22

Follow-up on the [[reranking]] pipeline. Eval harness landed; floor
thresholds set. Decision: hold on the embedder swap until we have
30+ labeled queries from real traffic.

Next sync: 2026-04-29.
""",
    "MOC - Knowledge.md": """\
---
type: moc
tags: [moc]
---

# Knowledge MOC

Map of content for the personal knowledge base.

- Python: [[async]], [[async-patterns]], [[decorators]],
  [[decorators-advanced]], [[typing]]
- Retrieval: [[tfidf]], [[embeddings]], [[embedding-models]],
  [[chunking]], [[reranking]]
- Tools: [[git-rebase]], [[git-cherry-pick]], [[obsidian]]
""",
    "inbox/quick-thought.md": """\
---
title: Quick thought
tags: [inbox]
---

A passing idea about prompt caching strategies — investigate later.
""",
    "archive/old-design.md": """\
---
title: Old retrieval design (archived)
tags: [archive]
---

# Pre-rerank pipeline (deprecated)

Initial cut used pure cos_sim with no graph rescoring. Replaced by
the current [[reranking]] approach in 2026-03.
""",
}


def write_corpus(vault_path: Path) -> None:
    """Materialize ``NOTES`` into ``vault_path``."""
    for rel, body in NOTES.items():
        target = vault_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
