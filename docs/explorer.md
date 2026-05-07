# Vault Explorer

A browser UI bundled in the same package — for **debugging** retrieval
("why did this note rank where it did?"), **visualizing** the wikilink
graph alongside live query hits, and **demoing** the semantic + graph
stack to teammates. Query box, ranked results with per-signal score
breakdown bars, slider-tunable re-rank weights with presets, and a
Cytoscape graph view that highlights hits and neighbors.

## Local

```bash
.venv/bin/pip install -e ".[explorer]"
OBSIDIAN_VAULT_PATH=/path/to/vault .venv/bin/python -m obsidian_mcp.explorer
# open http://127.0.0.1:8765
```

## Docker

```bash
docker pull ghcr.io/punparin/obsidian-mcp-explorer:latest
docker run --rm -p 8765:8765 -v /path/to/your/vault:/vault \
  ghcr.io/punparin/obsidian-mcp-explorer:latest
# open http://127.0.0.1:8765
```

Or build locally:

```bash
docker build -f Dockerfile.explorer -t obsidian-mcp-explorer .
docker run --rm -p 8765:8765 -v /path/to/vault:/vault obsidian-mcp-explorer
```

The Explorer imports `Vault` directly — same SQLite index as the MCP
server, so changes made through any MCP client or in Obsidian show up
live. Tuning a weight slider re-issues the query against the current
index; no server restart needed.

## Endpoints

- `GET /` — single-page UI
- `GET /api/health` — vault path, semantic state, embedding stats
- `POST /api/search` — body `{query, k, weights?}` → ranked results
  with `cos_sim`, per-signal `contributions`, and `signals` breakdown
- `GET /api/graph` — Cytoscape-friendly `{nodes, edges}` of the vault
  wikilink graph
- `GET /api/note?path=...` — full note content + frontmatter
- `GET /api/suggestions?min_score=&limit=&path=` — auto-link
  suggestions (note pairs that look related but aren't wikilinked)
- `POST /api/suggestions/apply` — body `{source, target}` → appends
  `See also: [[target]]` to the source (idempotent)
- `POST /api/suggestions/dismiss` — body `{source, target}` → hides
  the pair from future scans (persistent)
