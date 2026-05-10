# Tool Reference

**34 tools + 2 auto-loaded resources** for complete vault management,
self-maintaining knowledge wiki, and semantic retrieval.

| Group | Tool | Description |
|---|---|---|
| File ops | `read_note` | Read note by path. Records mtime for write-conflict detection |
| | `write_note` | Create/overwrite note. Raises `NoteConflictError` (with the current disk content) if the file moved under you since the last `read_note` |
| | `append_note` | Append to note |
| | `list_notes` | List `.md` files in folder. `include_frontmatter=True` returns parsed YAML alongside each path so triage avoids a per-note follow-up read |
| | `delete_note` | Delete a note |
| | `move_note` | Rename/move + auto-update wikilinks |
| Search | `search` | Full-text search. `path=` scopes to a subtree (e.g. `path="projects/"`) |
| | `search_by_tags` | Find by `#tags` or frontmatter tags. Supports `path=` subtree scope |
| | `search_by_frontmatter` | Find by YAML properties: single `key=value`, or multiple AND-combined fields via `filters={...}`. Substring match on strings; element match on list values. `path=` subtree scope |
| | `search_by_date_range` | Filter by date (file or frontmatter). `path=` subtree scope |
| Frontmatter | `get_note_frontmatter` | Parse YAML frontmatter |
| | `update_note_frontmatter` | Update properties without touching content |
| Links | `get_backlinks` | Find notes linking TO a note |
| | `get_wikilinks` | Extract outgoing wikilinks |
| | `get_vault_graph` | Full link graph (nodes + edges) |
| | `get_orphan_notes` | Find disconnected notes |
| Templates | `create_note_from_template` | Create note from template with `{{variables}}` |
| **Lint** | `find_broken_wikilinks` | Find unresolvable `[[links]]` |
| | `find_stale_notes` | Old notes still referenced from recent ones |
| | `find_duplicate_titles` | Notes with same filename in different folders |
| | `lint_vault` | Run all lint checks at once |
| **Schema** | `get_schema` | Read `schema.yml` from vault root |
| | `validate_note_schema` | Validate single note against schema |
| | `validate_vault_schema` | Validate entire vault |
| **Ingest** | `list_inbox` | List notes pending ingestion |
| | `find_related_notes` | Find existing notes related to raw content (semantic when enabled, lexical fallback) |
| | `archive_inbox_note` | Move processed note to `archive/YYYY-MM/` |
| **Semantic** | `semantic_search` | Embedding + graph-aware re-rank over note chunks |
| | `rebuild_embeddings` | Full re-embed of the vault (idempotent) |
| | `embedding_stats` | Inspect the embedding index (counts, model, path) |
| **Suggest** | `suggest_links` | Find note pairs that look related but aren't wikilinked |
| | `apply_link_suggestion` | Append `See also: [[target]]` (idempotent) |
| | `dismiss_link_suggestion` | Hide a pair from future suggestions (persistent) |
| **Groundedness** | `check_groundedness` | Scan a draft answer for generic-language markers ("generally speaking", "based on my training", …) — non-empty hits mean retrieval probably failed |

## Resources (auto-loaded context)

- `obsidian://vault-map` — index of all notes (path, title, tags, links, modified, summary)
- `obsidian://mocs` — Map of Content hub notes
