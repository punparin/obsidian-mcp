# Semantic Retrieval & Auto-Link Suggestions

Local-first semantic search over your vault, plus AI-driven link
suggestions — both powered by the same chunk vector store.

## Semantic search

**How it works:**

1. On server start, each note's body is split into markdown-aware
   chunks (H2/H3 sections, packed to ≤1600 chars with paragraph
   overlap).
2. Each chunk is embedded — either by a remote
   [Ollama](https://ollama.com) server (default in Docker) or by an
   in-process [`fastembed`](https://github.com/qdrant/fastembed) model
   (opt-in extra). See [Embedder selection](#embedder-selection) below.
3. Vectors live in `<vault>/.obsidian-mcp/index.db` (SQLite +
   `sqlite-vec`).
4. On query: embed the query → top-K chunks via cosine distance →
   aggregate to notes → re-rank with graph signals.

**Re-rank formula** (weights all env-tunable):

```
final = 1.00 * cos_sim              # semantic similarity
      + 0.40 * wikilink_match       # 1 if candidate is [[linked]] from query
      + 0.30 * tag_jaccard          # |shared tags| / |union|
      + 0.15 * neighbor_bonus       # 1/hops if within 2 hops of a query-linked note
      + 0.10 * recency_decay        # exp(-age_days/180)
```

Your explicit wikilinks can beat a marginally higher semantic score —
the bias is deliberate. Tune via `OBSIDIAN_W_SEM`, `OBSIDIAN_W_LINK`,
`OBSIDIAN_W_TAG`, `OBSIDIAN_W_NEIGHBOR`, `OBSIDIAN_W_RECENCY`.

**Interpreting scores:** sentence-embedding cosine similarities are
not calibrated probabilities. For typical short queries against a
real vault, expect:

| `cos_sim` range | What it usually means |
|---|---|
| `> 0.6` | Strong match — query and chunk share most of the topic. Rare for short queries. |
| `0.45 – 0.6` | Solid topical match. Treat as a likely target. |
| `0.3 – 0.45` | Plausible — read before relying on it. Often the right answer when no stronger signal exists. |
| `< 0.3` | Weak. Without a graph signal (`wikilink_match`, `tag_jaccard > 0.2`, or `neighbor_hops`), assume no good match. |

The **final re-rank score** (after the formula above) often lands
~0.4–0.7 on the top hit even for clearly relevant notes — that's
expected, not a sign of a tuning problem. Use the breakdown
(`cos_sim`, `signals`, `contributions`) to decide whether the match
is semantic-driven or graph-driven before treating a low number as
"no match."

There is no single hard threshold below which `semantic_search` says
"this doesn't exist." That call belongs to the agent and depends on
whether any graph signal accompanies the cosine number.

**Lifecycle:**

- Edits (from MCP or Obsidian) are picked up by the filesystem watcher
  and re-embedded in the background with a 200 ms debounce.
- Body unchanged? `body_hash` short-circuits the embed.
- `find_related_notes` automatically uses the semantic pipeline when
  enabled, with the lexical scorer as a fallback.

**Disabling:** set `OBSIDIAN_EMBEDDER=none` to skip all of this; the
three semantic tools no-op and `find_related_notes` falls back to
lexical scoring.

## Embedder selection

Two backends are available; pick one with `OBSIDIAN_EMBEDDER`:

| `OBSIDIAN_EMBEDDER` | Where it runs | When to use |
|---|---|---|
| `ollama` (Docker default) | HTTP to a remote [Ollama](https://ollama.com) server | Recommended. Lets you pick any embedding model without bloating the MCP host. Required for the slim Docker image. |
| `fastembed` (factory default when unset) | In-process ONNX, downloads `BAAI/bge-small-en-v1.5` (~130 MB) on first use | Single-host setups where you don't want a separate Ollama server. Requires `pip install ".[fastembed]"` — base install will fail to start with a hint pointing here. |
| `fake` | Deterministic stub | Tests only |
| `none` | — | Disable semantic features entirely |

**Env vars:**

```bash
OBSIDIAN_EMBEDDER=ollama
OBSIDIAN_EMBEDDER_MODEL=qwen3-embedding:8b   # or :4b, bge-m3, mxbai-embed-large, ...
OLLAMA_URL=http://desktop.local:11434        # default http://localhost:11434
```

**Recommended models** (descending quality, all via Ollama unless noted):

| Model | Dim | Notes |
|---|---|---|
| `qwen3-embedding:8b` | 4096 | **Recommended.** SOTA on MTEB, strong multilingual (Thai/Chinese/Japanese). ~16 KB per vector — heaviest, but best quality |
| `qwen3-embedding:4b` | 2560 | Sweet spot: close to 8B quality at ~⅔ storage and noticeably faster |
| `bge-m3` | 1024 | Lightweight multilingual fallback, long context (8 k) |
| `mxbai-embed-large` | 1024 | Strong English-only option; older but well-supported |
| `nomic-embed-text` | 768 | Balanced quality/speed; 8 k context |
| `BAAI/bge-small-en-v1.5` | 384 | Default fastembed model — Pi-friendly, English only |

Rankings shift fast — cross-check the
[MTEB leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
before committing to a model for a large vault. Larger dim = better
recall but more disk + slower kNN.

**Switching is safe:** the vector store records the active model and
dim. On startup, if either has changed, the index is cleared and the
reconcile loop re-embeds every note in the background. Expect a few
minutes of degraded search quality after a switch on large vaults.

## Eval harness

A labeled retrieval benchmark lives under `tests/eval/`: 19 themed
notes + 18 hand-labeled `(query, expected_paths)` pairs. Several
topics have multiple sibling notes that share vocabulary (two async
notes, two decorator notes, three retrieval notes, two same-project
meetings on different dates) so ranking is non-trivial — the
embedder has to discriminate, not just pick the only relevant note.
Use it to measure quality before/after weight tweaks or embedder
swaps rather than guessing whether a change made retrieval better.

**Run as pytest** (CI-friendly, asserts floor thresholds):

```bash
pytest -m eval
```

The eval is marker-gated so default `pytest` skips it (it loads the
real fastembed model). Floors are calibrated against the current
baseline (`hit@1 = 0.94, hit@3 = hit@5 = 1.00, MRR = 0.972`) with
1–3 miss tolerance — `hit@1 ≥ 0.80, hit@3 ≥ 0.90, hit@5 ≥ 0.94,
MRR ≥ 0.85`. Anything below means a likely regression.

**Run as CLI** (ad-hoc, prints metrics + per-query breakdown):

```bash
python scripts/eval_retrieval.py
# or with an alternative embedder:
OBSIDIAN_EMBEDDER=ollama OBSIDIAN_EMBEDDER_MODEL=nomic-embed-text \
    python scripts/eval_retrieval.py
```

Adding queries: append to `tests/eval/queries.py`. The corpus is
intentionally small to keep first-run cost low; if you need broader
coverage, prefer adding labeled queries against the existing notes
before adding new notes.

## Auto-link suggestions

Find pairs of notes that look related but aren't wikilinked yet — and
grow your graph without re-reading the whole vault.

**How it works:**

1. For each note, embed the body and pull the top-K nearest neighbors
   from the chunk vector store.
2. Skip self-pairs and pairs already wikilinked in either direction
   (treated as undirected) and pairs you've previously dismissed.
3. Score = `0.7 * cos_sim + 0.3 * tag_jaccard` — note this is
   `suggest_links`'s own scoring, distinct from the `semantic_search`
   re-rank above. Above a threshold (default 0.55) the pair shows up
   as a suggestion.
4. Dedupe by canonical pair so A→B and B→A are one suggestion.

```python
# MCP tools
suggest_links(path="", limit=25, min_score=0.55)
apply_link_suggestion(source, target)   # idempotent — adds "See also: [[target]]"
dismiss_link_suggestion(source, target) # persistent across runs
```

The [Vault Explorer](./explorer.md) has a **Link suggestions** tab
that lists results with score + shared tags + snippet, plus per-row
Apply / Dismiss buttons. Apply re-fetches the index naturally on the
next scan, so applied pairs disappear automatically once the vault is
updated.
