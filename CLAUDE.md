# CLAUDE.md

## Project Overview
Obsidian MCP Server — a FastMCP-based MCP server that gives Claude Code full read/write access to an Obsidian vault. Provides tools for note CRUD, search, frontmatter manipulation, wikilink graph traversal, and template-based note creation.

## Running
```bash
OBSIDIAN_VAULT_PATH=/path/to/vault .venv/bin/python -m obsidian_mcp.server
```

## Testing
```bash
.venv/bin/pytest tests/ -v
```

## Architecture
- `obsidian_mcp/server.py` — FastMCP server, tool/resource definitions
- `obsidian_mcp/vault.py` — Vault class, file ops, indexing, search
- `obsidian_mcp/frontmatter.py` — YAML frontmatter parsing/updating
- `obsidian_mcp/links.py` — Wikilink extraction, backlinks, graph
- `obsidian_mcp/templates.py` — Template expansion with {{variables}}
- `obsidian_mcp/watcher.py` — `watchdog`-based filesystem watcher that
  keeps the Vault index in sync with out-of-band edits and underpins
  write-conflict detection in `Vault.write_note`.
- `obsidian_mcp/ignore.py` — `IgnoreMatcher` + `load_ignore_config`. Reads
  `<vault>/.obsidian-mcp/config.yml` (`ignore:` key, gitignore-style globs)
  and combines user patterns with always-ignored built-ins (`.obsidian/`,
  `.git/`, `.trash/`, `.stversions/`, `.obsidian-mcp/`, tempfile suffixes).
  `Vault.is_ignored(rel_path)` is the single predicate consulted by
  `_build_index`, `list_notes`, `search_fulltext`, `_reindex_path`,
  `_enqueue_embed`, the watcher, and `ingest.list_inbox`. Explicit
  `read_note`/`write_note` bypass the predicate — ignore is "don't
  surface in scans", not "deny access".
- `obsidian_mcp/chunker.py` — markdown-aware splitter (H2/H3 sections,
  paragraph packing) for semantic retrieval.
- `obsidian_mcp/embeddings.py` — backend abstraction (`FastEmbedBackend`,
  `OllamaBackend` for remote inference, `FakeBackend` for tests),
  selected via `OBSIDIAN_EMBEDDER` (`fastembed` | `ollama` | `fake` |
  `none`). Factory default when the env var is unset is `fastembed`,
  but the base install (and the Docker image) ships without `fastembed`
  in deps and sets `OBSIDIAN_EMBEDDER=ollama` — installing the
  `[fastembed]` extra is required to use the in-process backend.
  Ollama also reads `OBSIDIAN_EMBEDDER_MODEL` and `OLLAMA_URL`.
  Switching models auto-clears the index on next start.
- `obsidian_mcp/vector_store.py` — chunk-level SQLite + `sqlite-vec`
  store under `<vault>/.obsidian-mcp/index.db`.
- `obsidian_mcp/semantic.py` — query pipeline: embed → kNN → graph re-rank
  (cos_sim + wikilink + tag_jaccard + neighbor_hops + recency).
- `obsidian_mcp/embed_queue.py` — background debounced worker that
  coalesces rapid edits and re-embeds changed chunks only (body_hash
  short-circuit).
- `obsidian_mcp/suggest.py` — auto-link suggestions: scans the vault
  via the chunk vector store, scores pairs by `0.7*cos_sim +
  0.3*tag_jaccard`, filters out already-linked pairs (undirected) and
  dismissals, returns top suggestions. Dismissals + `apply` are MCP
  tools and Explorer endpoints.
- `obsidian_mcp/explorer/` — Vault Explorer: optional FastAPI sidecar
  (`pip install -e ".[explorer]"`) for debugging retrieval, visualizing
  the wikilink graph, and demoing the stack. Ranked results with
  per-signal contribution bars, slider-tunable re-rank weights, live
  Cytoscape graph view. Imports `Vault` directly; same SQLite index
  as the MCP server. Built into a separate Docker image
  (`Dockerfile.explorer`, published as
  `ghcr.io/punparin/obsidian-mcp-explorer`).

## Key Conventions
- All paths are relative to vault root
- Path security: all resolved paths checked to stay within vault
- Logging to stderr only (STDIO transport requirement)
- Vault path via `OBSIDIAN_VAULT_PATH` env var
