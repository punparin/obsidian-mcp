"""Vault Explorer — debug, visualize, and demo the semantic + graph stack.

A FastAPI sidecar that imports ``Vault`` directly (same vault, same
vector store, same semantic stack the MCP server uses) and serves a
single-page UI for:

- **Debug**: see exactly why a note ranked where it did — per-signal
  contribution bars (cos_sim, wikilink, tag, neighbor, recency) make
  re-rank decisions inspectable.
- **Visualize**: a live Cytoscape view of the wikilink graph, with
  query hits highlighted and 1/2-hop neighbors traceable.
- **Demo**: slider-tunable weights re-issue the query against the live
  index — flip between "semantic only" and "graph heavy" presets to
  show why the graph layer matters.

Runs alongside the MCP server (separate HTTP port), sharing the same
SQLite index so edits made via Obsidian or Claude Code show up live.

    pip install -e ".[explorer]"
    OBSIDIAN_VAULT_PATH=/path/to/vault python -m obsidian_mcp.explorer
"""
