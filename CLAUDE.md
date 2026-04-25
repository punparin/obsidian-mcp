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

## Key Conventions
- All paths are relative to vault root
- Path security: all resolved paths checked to stay within vault
- Logging to stderr only (STDIO transport requirement)
- Vault path via `OBSIDIAN_VAULT_PATH` env var
