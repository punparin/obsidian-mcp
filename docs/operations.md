# Operations

Operator reference for **obsidian-mcp**: tuning knobs, deployment
notes, and conflict-detection semantics.

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
                        → error carries current disk content (~4 KB cap)
                        → agent merges in place, or passes force=True
```

The check only kicks in when the MCP has *previously* handed the
content of `p` to the model. First-time creates and template-based
writes are unaffected.
