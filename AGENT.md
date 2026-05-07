# AGENT.md

Guidance for any MCP-capable agent (Claude Code, Cursor, Cline,
Continue, Goose, Windsurf, …) on how to use **obsidian-mcp**
effectively.

Two ways to wire this up:

1. **Agents that auto-load `AGENT.md` / `AGENTS.md` / `CLAUDE.md`** —
   drop a copy of the [system-prompt block](#system-prompt-block) into
   your vault's agent file (e.g. `<vault>/AGENT.md` or
   `~/.claude/CLAUDE.md`). The agent picks it up every session.
2. **Agents configured via explicit system prompt** — paste the same
   block into your agent's prompt config.

## System-prompt block

Paste the section below verbatim into your agent's system prompt or
project-level rules file:

```markdown
## Obsidian MCP

You have access to obsidian-mcp, an MCP server with read/write access
to an Obsidian vault. Follow these rules:

- Use `semantic_search` for conceptual queries ("what did I think
  about X?", "anything about retrieval-augmented generation"). Use
  `search` for exact strings — quoted phrases, error messages, code
  snippets, filenames, inline `#tags`.
- `.obsidian-mcp/` at the vault root is a local vector index cache.
  Do not read, edit, or commit files under it. It regenerates itself.
- After renaming a note, the vault already updates wikilinks. Don't
  hand-edit references; call `move_note` instead.
- `write_note` refuses to clobber a note edited on disk since the
  last `read_note` on the same path. Re-read before overwriting, or
  pass `force=True` only when you mean it.
- The ingest flow is `list_inbox` → `read_note` →
  `find_related_notes` → update related notes → `archive_inbox_note`.
  Don't delete inbox notes; archive them so the source stays
  recoverable.
- `suggest_links` finds note pairs that look related but aren't
  wikilinked. Use `apply_link_suggestion(source, target)` to add a
  `See also: [[target]]` (idempotent), or `dismiss_link_suggestion`
  to hide a pair permanently. Don't bulk-apply — review each one.
```

## When to use each tool

### Search intent

| Use | Tool | Why |
|---|---|---|
| "Notes about X" / "anything related to Y" | `semantic_search` | Meaning-based, uses chunk-level embeddings. |
| Exact string, quoted phrase, error message | `search` | Substring match; returns line numbers. |
| `#tag` filter | `search_by_tags` | Structured, no scoring noise. |
| "Written after Mar 1, 2026" | `search_by_date_range` | Structured date filter. |
| Frontmatter property | `search_by_frontmatter` | Structured property match. |
| "This inbox item relates to which of my notes?" | `find_related_notes` | Uses semantic + your graph (wikilinks, tags). Better than raw `semantic_search` when you have a full block of source content. |
| "What notes should be linked but aren't?" | `suggest_links` | Pair-level scan; surfaces edges missing from your graph based on semantic + tag overlap. Apply with `apply_link_suggestion` or hide with `dismiss_link_suggestion`. |

Rule of thumb: if the user quoted something literally, use `search`.
If they're describing a concept, use `semantic_search`. If there's a
data structure to filter on (tag, date, frontmatter key), use the
structured tool.

If the likely location is already known (e.g. "in projects/"), every
search tool above accepts a `path` parameter that scopes the walk to
a subtree. Faster, and cuts noise from unrelated folders.

### Discovery flow

When asked "is there a note about X already?":

1. Call `semantic_search("X", k=10)` first.
2. If the top hit has `signals.wikilink_match: true` or high
   `tag_jaccard`, that's almost certainly the target — read it.
3. Otherwise, calibrate by the breakdown: a top hit at `cos_sim` 0.5+
   is strong, 0.35-0.5 is plausible (read it before deciding), and
   under 0.3 with no graph signals usually means no good match
   exists yet — offer to create rather than force-fit. Don't expect
   raw cos_sim above ~0.6 for short queries; that's not how
   sentence-embedding similarities are distributed.

### Writing / editing flow

1. `read_note` before `write_note` on the same path — otherwise the
   server can't detect external conflicts.
2. If you're creating from scratch, `create_note_from_template` or a
   fresh `write_note` is fine (no conflict check needed).
3. For appends, prefer `append_note` — it's additive and won't trip
   the conflict check.
4. After moving, use `move_note` (it auto-updates `[[wikilinks]]`
   across the vault). Manual rename + hand-editing references will
   leave the index and wikilinks inconsistent until the next reindex.

### Ingest flow

```
list_inbox
  ↓
for each item:
    read_note(item.path)
    find_related_notes(content)        ← semantic + graph
    → update those related notes
    archive_inbox_note(item.path)       ← moves to archive/YYYY-MM/
```

Don't `delete_note` on inbox items after processing — archiving keeps
the source recoverable and the audit trail intact.

### Auto-link suggestion flow

```
suggest_links(min_score=0.55, limit=25)
  ↓
for each suggestion:
    read both notes  ← decide if the link makes sense
    apply_link_suggestion(source, target)   ← appends "See also: [[target]]"
    OR
    dismiss_link_suggestion(source, target) ← hides it forever
```

Rules of thumb:

- Default threshold is 0.55 on `suggest_links`'s own score formula
  (`0.7 * cos_sim + 0.3 * tag_jaccard`) — distinct from
  `semantic_search`'s re-rank score, so don't compare them. Drop to
  ~0.4 for an exploratory sweep, raise to ~0.7 if you only want
  high-confidence pairs.
- `apply_link_suggestion` is idempotent (it checks the resolved-link
  graph, not just substring), so re-applying is a safe no-op. The
  link is added as a `See also` line at the end of the source.
- Dismissals persist in `index.db` and survive server restarts. If
  you change your mind, the same pair won't reappear unless you
  re-enable it (no MCP tool for that yet — clear from
  `dismissed_link_suggestions` directly if needed).
- Suggestions are deduped by canonical pair, so applying or
  dismissing one direction handles both.

## Interpreting `semantic_search` results

Each result includes a score breakdown:

```json
{
  "path": "projects/graph-retrieval.md",
  "title": "Graph Retrieval Design",
  "score": 1.22,
  "cos_sim": 0.65,
  "signals": {
    "wikilink_match": true,
    "tag_jaccard": 0.30,
    "neighbor_hops": 1,
    "recency": 0.80
  },
  "snippet": "…",
  "heading": "Re-rank formula"
}
```

- `cos_sim` near 1.0 → strong semantic match on the chunk body.
- `wikilink_match: true` → the query explicitly `[[linked]]` this
  note (very high confidence it's the target).
- `tag_jaccard` → overlap of `#tags` in query vs note.
- `neighbor_hops: 1` → direct wikilink neighbor of a query-mentioned
  note. `2` → two hops away. Missing → unrelated in the graph.
- `recency` → freshness weight (half-life 180 days).

If users complain results feel off, these signals tell you *why* and
help decide whether to ignore a high-semantic-but-disconnected hit.

## Tuning

Re-rank weights are environment variables. Defaults favour the user's
explicit graph over raw semantic similarity:

| Var | Default | Role |
|---|---|---|
| `OBSIDIAN_W_SEM` | 1.00 | cosine similarity weight |
| `OBSIDIAN_W_LINK` | 0.40 | `[[wikilink]]` match from query |
| `OBSIDIAN_W_TAG` | 0.30 | `#tag` Jaccard |
| `OBSIDIAN_W_NEIGHBOR` | 0.15 | graph-neighbor bonus |
| `OBSIDIAN_W_RECENCY` | 0.10 | recency decay |

Lower `W_LINK` + `W_TAG` if you want results to feel more exploratory
and less "the agent keeps surfacing the same explicitly-linked notes."

## Operational notes

- **First run** rebuilds the index from scratch. With
  `OBSIDIAN_EMBEDDER=fastembed` (local install via the `[fastembed]`
  extra) the first run also downloads `BAAI/bge-small-en-v1.5`
  (~130MB, ~15s on a Pi). With `OBSIDIAN_EMBEDDER=ollama` (Docker
  default) no model download happens locally — the Ollama server
  pulls the model on its end. Subsequent runs reuse the cache.
- **Git-tracked vault?** Add `/.obsidian-mcp/` to the vault's
  `.gitignore`. The SQLite WAL churns on every edit and isn't worth
  committing.
- **Dropbox/iCloud/Syncthing vault?** Same — exclude `.obsidian-mcp/`
  from sync. SQLite files don't merge across machines. If you want a
  multi-machine setup, give each machine its own MCP server + index.
- **Index corruption?** Delete `<vault>/.obsidian-mcp/index.db` and
  call `rebuild_embeddings`. Idempotent and cheap.
- **Disable semantic entirely:** set `OBSIDIAN_EMBEDDER=none`.
  `find_related_notes` falls back to the lexical scorer;
  `semantic_search` / `rebuild_embeddings` / `embedding_stats` return
  a disabled hint.

## Conflict detection quick reference

```
read_note(p)          → records disk mtime
user edits p in Obsidian
write_note(p, …)      → NoteConflictError (mtime advanced)
→ agent should re-read, merge, retry
→ or pass force=True to overwrite deliberately
```

The check only kicks in when the MCP has *previously* handed the
content of `p` to the model. First-time creates and template-based
writes are unaffected.
