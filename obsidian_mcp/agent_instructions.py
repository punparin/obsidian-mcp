"""Server-side instructions surfaced via the MCP ``initialize`` response.

Most MCP clients (Claude Code, …) inject these into the agent's system
prompt automatically, so the user gets the right defaults without
copying anything into their own ``CLAUDE.md`` / Cursor rules.

Kept terse on purpose — every byte here ships in every session. For
the full operator-facing reference (tuning, install, troubleshooting),
see ``AGENT.md`` and ``README.md``.
"""

INSTRUCTIONS = """\
You have access to obsidian-mcp, an MCP server with read/write access
to a user's Obsidian vault. Operating rules:

## Tool choice

- `semantic_search` for conceptual queries ("what did I think about
  X?", "anything about retrieval-augmented generation"). Returns a
  score breakdown — see "Interpreting scores" below.
- `search` for exact strings: quoted phrases, error messages, code
  snippets, filenames, inline `#tags`. Substring match with line
  numbers.
- `search_by_tags` / `search_by_frontmatter` / `search_by_date_range`
  for structured filters. Prefer these over `semantic_search` when a
  data structure exists to filter on.
- `search_by_frontmatter` accepts a `filters={...}` object for
  AND-combined matching across multiple fields (e.g.
  `{"status": "draft", "type": "weekly"}`).
- Every search tool above accepts a `path` argument (e.g.
  `path="projects/"`). Use it whenever the likely folder is known —
  faster, cuts noise.
- `find_related_notes(content)` when you have a full block of source
  (an inbox note, a draft) and want to see which existing notes it
  connects to. Better than raw `semantic_search` because it also
  weighs your wikilink/tag graph.

## Discovery flow

When asked "is there a note about X already?":

1. `semantic_search("X", k=10)`.
2. If the top hit has `signals.wikilink_match: true` or high
   `tag_jaccard`, that's almost certainly the target — read it.
3. Otherwise calibrate by `cos_sim`: 0.5+ is strong, 0.35-0.5 is
   plausible (read before deciding), <0.3 with no graph signals
   usually means no good match exists yet — offer to create rather
   than force-fit. Don't expect raw `cos_sim` above ~0.6 for short
   queries; that's not how sentence-embedding similarities are
   distributed.

## Writing / editing flow

1. `read_note` before `write_note` on the same path — otherwise the
   server can't detect external conflicts.
2. Creating from scratch: `create_note_from_template` or a fresh
   `write_note` is fine (no conflict check needed).
3. For appends, prefer `append_note` — additive, won't trip the
   conflict check.
4. After moving, use `move_note` (auto-updates `[[wikilinks]]` across
   the vault). Manual rename + hand-editing references will leave the
   index inconsistent until the next reindex.

## Conflict handling

`write_note` refuses to clobber a note edited on disk since the last
`read_note` on the same path. The `NoteConflictError` carries the
current on-disk content (capped ~4 KB) so you can merge in place
without a follow-up `read_note`. Pass `force=True` only when you
mean to overwrite.

## Ingest flow

```
list_inbox
  ↓ for each item:
read_note(item.path) → find_related_notes(content) → update related
  notes → archive_inbox_note(item.path)
```

Don't `delete_note` on inbox items — archive keeps the source
recoverable.

## Auto-link suggestions

`suggest_links(min_score=0.55, limit=25)` returns note pairs that look
related but aren't wikilinked. For each:

- `apply_link_suggestion(source, target)` adds a `See also: [[target]]`
  (idempotent — checks the resolved-link graph, safe to re-apply).
- `dismiss_link_suggestion(source, target)` hides the pair forever.

Don't bulk-apply. Default 0.55 is on `suggest_links`'s own formula
(`0.7 * cos_sim + 0.3 * tag_jaccard`) — distinct from
`semantic_search`'s re-rank score. Drop to ~0.4 for an exploratory
sweep, raise to ~0.7 for high-confidence pairs only.

## Interpreting `semantic_search` scores

Each result has a breakdown:

```json
{"cos_sim": 0.65, "signals": {"wikilink_match": true,
 "tag_jaccard": 0.30, "neighbor_hops": 1, "recency": 0.80}}
```

- `cos_sim` near 1.0 → strong semantic match on the chunk body.
- `wikilink_match: true` → query explicitly `[[linked]]` this note
  (very high confidence target).
- `tag_jaccard` → `#tag` overlap.
- `neighbor_hops: 1` → direct wikilink neighbor of a query-mentioned
  note. `2` → two hops. Missing → unrelated in graph.
- `recency` → freshness weight (180-day half-life).

## Hands off

`.obsidian-mcp/` at the vault root is the local index/cache. Do not
read, edit, or commit files under it — it regenerates itself.
"""
