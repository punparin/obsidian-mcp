# Obsidian MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that gives Claude Code full read/write access to an Obsidian vault. Built with [FastMCP](https://github.com/jlowin/fastmcp).

## Architecture

```mermaid
flowchart LR
    User[You]
    Claude[Claude Code]
    Server[Obsidian MCP]
    Vault[(Obsidian Vault)]

    User --> Claude
    Claude <--> Server
    Server --> Vault
    Vault -.-> Server

    classDef user fill:#e1f5ff,stroke:#333
    classDef ai fill:#fff4e1,stroke:#333
    classDef mcp fill:#e8f5e9,stroke:#333
    classDef store fill:#f3e5f5,stroke:#333

    class User user
    class Claude ai
    class Server mcp
    class Vault store
```

## Tool Categories

```mermaid
flowchart TD
    MCP[Obsidian MCP - 16 tools]

    MCP --> FileOps[File Operations - 6 tools]
    MCP --> Search[Search - 4 tools]
    MCP --> Meta[Frontmatter - 2 tools]
    MCP --> Links[Links and Graph - 3 tools]
    MCP --> Tpl[Templates - 1 tool]
    MCP --> Res[Resources - 2 auto-loaded]

    FileOps --> F1[read_note, write_note, append_note, list_notes, delete_note, move_note]
    Search --> S1[search, search_by_tags, search_by_frontmatter, search_by_date_range]
    Meta --> FM1[get_note_frontmatter, update_note_frontmatter]
    Links --> L1[get_backlinks, get_wikilinks, get_vault_graph, get_orphan_notes]
    Tpl --> T1[create_note_from_template]
    Res --> R1[vault-map, mocs]
```

## How Claude Uses Your Vault

```mermaid
sequenceDiagram
    actor User
    participant Claude
    participant MCP as Obsidian MCP
    participant Vault

    User->>Claude: What did we decide about rate limiting?
    Claude->>MCP: read vault-map
    MCP->>Vault: scan notes
    Vault-->>MCP: notes index
    MCP-->>Claude: vault structure
    Claude->>MCP: search_by_tags rate-limiting
    MCP-->>Claude: matching notes
    Claude->>MCP: read_note decisions/rate-limiting.md
    MCP->>Vault: read file
    Vault-->>MCP: content
    MCP-->>Claude: full note
    Claude->>User: We chose token bucket because...
```

## Features

**30 tools + 2 resources** for complete vault management, self-maintaining knowledge wiki, and semantic retrieval:

| Group | Tool | Description |
|---|---|---|
| File ops | `read_note` | Read note by path |
| | `write_note` | Create/overwrite note |
| | `append_note` | Append to note |
| | `list_notes` | List .md files in folder |
| | `delete_note` | Delete a note |
| | `move_note` | Rename/move + auto-update wikilinks |
| Search | `search` | Full-text search |
| | `search_by_tags` | Find by #tags or frontmatter tags |
| | `search_by_frontmatter` | Find by any YAML property |
| | `search_by_date_range` | Filter by date (file or frontmatter) |
| Frontmatter | `get_note_frontmatter` | Parse YAML frontmatter |
| | `update_note_frontmatter` | Update properties without touching content |
| Links | `get_backlinks` | Find notes linking TO a note |
| | `get_wikilinks` | Extract outgoing wikilinks |
| | `get_vault_graph` | Full link graph (nodes + edges) |
| | `get_orphan_notes` | Find disconnected notes |
| Templates | `create_note_from_template` | Create note from template with {{variables}} |
| **Lint** (v0.2) | `find_broken_wikilinks` | Find unresolvable [[links]] |
| | `find_stale_notes` | Old notes still referenced from recent ones |
| | `find_duplicate_titles` | Notes with same filename in different folders |
| | `lint_vault` | Run all lint checks at once |
| **Schema** (v0.2) | `get_schema` | Read schema.yml from vault root |
| | `validate_note_schema` | Validate single note against schema |
| | `validate_vault_schema` | Validate entire vault |
| **Ingest** (v0.2) | `list_inbox` | List notes pending ingestion |
| | `find_related_notes` | Find existing notes related to raw content (semantic when enabled, lexical fallback) |
| | `archive_inbox_note` | Move processed note to archive/YYYY-MM/ |
| **Semantic** (v0.3) | `semantic_search` | Embedding + graph-aware re-rank over note chunks |
| | `rebuild_embeddings` | Full re-embed of the vault (idempotent) |
| | `embedding_stats` | Inspect the embedding index (counts, model, path) |
| **Suggest** (v0.5) | `suggest_links` | Find note pairs that look related but aren't wikilinked |
| | `apply_link_suggestion` | Append `See also: [[target]]` (idempotent) |
| | `dismiss_link_suggestion` | Hide a pair from future suggestions (persistent) |

**Resources** (auto-loaded context):
- `obsidian://vault-map` -- index of all notes (path, title, tags, links, modified, summary)
- `obsidian://mocs` -- Map of Content hub notes

## Installation

### Docker (recommended)

Pre-built image from GitHub Container Registry:

```bash
docker pull ghcr.io/punparin/obsidian-mcp:latest
```

Or build locally:

```bash
git clone https://github.com/punparin/obsidian-mcp.git
cd obsidian-mcp
docker build -t obsidian-mcp .
```

### Local virtualenv

```bash
git clone https://github.com/punparin/obsidian-mcp.git
cd obsidian-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Register with Claude Code

### Docker

```bash
claude mcp add \
  -s user \
  obsidian \
  -- docker run -i --rm -v /path/to/your/vault:/vault ghcr.io/punparin/obsidian-mcp:latest
```

### Local

```bash
claude mcp add \
  -e OBSIDIAN_VAULT_PATH=/path/to/your/vault \
  -s user \
  obsidian \
  -- /path/to/obsidian-mcp/.venv/bin/python -m obsidian_mcp
```

## Configuration

Set the vault path via environment variable:

```bash
export OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault
```

## Using With Claude Code

See [`docs/using-with-claude-code.md`](docs/using-with-claude-code.md)
for rules on tool choice (semantic vs exact), writing flow, ingest
flow, interpreting score signals, and a ready-to-paste block for your
`CLAUDE.md`.

## Semantic Retrieval (v0.3)

Local-first semantic search over your vault, using your hand-curated graph
(wikilinks, tags, frontmatter) to re-rank the raw embedding results.

**How it works:**
1. On server start, each note's body is split into markdown-aware chunks
   (H2/H3 sections, packed to ≤1600 chars with paragraph overlap).
2. Each chunk is embedded with [`fastembed`](https://github.com/qdrant/fastembed)
   using `BAAI/bge-small-en-v1.5` (ONNX, local, ~100MB download on first run).
3. Vectors live in `<vault>/.obsidian-mcp/index.db` (SQLite + `sqlite-vec`).
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

Your explicit wikilinks can beat a marginally higher semantic score — the
bias is deliberate. Tune via `OBSIDIAN_W_SEM`, `OBSIDIAN_W_LINK`,
`OBSIDIAN_W_TAG`, `OBSIDIAN_W_NEIGHBOR`, `OBSIDIAN_W_RECENCY`.

**Lifecycle:**
- Edits (from MCP or Obsidian) are picked up by the filesystem watcher and
  re-embedded in the background with a 200ms debounce.
- Body unchanged? `body_hash` short-circuits the embed.
- `find_related_notes` automatically uses the semantic pipeline when
  enabled, with the lexical scorer as a fallback.

**Disabling:** set `OBSIDIAN_EMBEDDER=none` to skip all of this; the three
new tools will no-op and `find_related_notes` falls back to lexical.

## Auto-Link Suggestions (v0.5)

Find pairs of notes that look related but aren't wikilinked yet — and
grow your graph without re-reading the whole vault.

**How it works:**

1. For each note, embed the body and pull the top-K nearest neighbors
   from the chunk vector store.
2. Skip self-pairs and pairs already wikilinked in either direction
   (treated as undirected) and pairs you've previously dismissed.
3. Score = `0.7 * cos_sim + 0.3 * tag_jaccard`. Above a threshold
   (default 0.55) it shows up as a suggestion.
4. Dedupe by canonical pair so A→B and B→A are one suggestion.

```python
# MCP tools
suggest_links(path="", limit=25, min_score=0.55)
apply_link_suggestion(source, target)   # idempotent — adds "See also: [[target]]"
dismiss_link_suggestion(source, target) # persistent across runs
```

The Vault Explorer has a **Link suggestions** tab that lists results
with score + shared tags + snippet, plus per-row Apply / Dismiss
buttons. Apply re-fetches the index naturally on the next scan, so
applied pairs disappear automatically once the vault is updated.

## Live Vault Sync

The server keeps its in-memory index in sync with the vault via a
filesystem watcher (backed by `watchdog`). Edits you make directly in
Obsidian — or any other tool — are reflected in the next MCP query
without restarting the server.

The watcher also backs **conflict detection on writes**: if a note
changed on disk between Claude's last `read_note` and its next
`write_note` on the same path, the write is refused with a
`NoteConflictError` so you don't clobber an edit made in Obsidian. Pass
`force=true` to override intentionally.

Directories like `.obsidian/`, `.git/`, `.trash/`, and non-markdown
files are ignored by the watcher.

## Frontmatter Convention

For best results, standardize your notes with YAML frontmatter:

```yaml
---
title: Meeting Notes
type: meeting-note    # note, project, meeting-note, reference, journal, moc
tags: [work, planning]
date: 2026-04-08
status: active        # draft, active, archived
---
```

The `type` field helps Claude understand what kind of note it's looking at without reading the full content.

## Templates

Place templates in a `templates/` folder in your vault. Use `{{variables}}` for expansion:

```markdown
---
title: {{title}}
date: {{date}}
---

## {{title}}

Created on {{date}} at {{time}}.
```

Built-in variables: `{{title}}`, `{{date}}`, `{{time}}`, `{{datetime}}`

## Self-Maintaining Wiki (v0.2)

Inspired by [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). Three layers turn your vault into a knowledge base that compounds over time:

### 1. Lint — find rot before it spreads

Run `lint_vault` periodically. It catches:
- Broken wikilinks (notes you renamed without updating references)
- Stale notes (old content still linked from recent work — review or update)
- Duplicate titles (causes wikilink ambiguity)
- Orphan notes (disconnected knowledge)

### 2. Schema — structured note types

Create `schema.yml` at vault root:

```yaml
note_types:
  project:
    required: [title, status, area]
    optional: [tags, due_date]
    status_values: [active, paused, done, archived]
  decision:
    required: [title, date, status]
    optional: [project, participants, tags]
    status_values: [proposed, decided, superseded]
  meeting-note:
    required: [title, date]
    optional: [participants, project, tags]

folders:
  projects: project
  decisions: decision
  meetings: meeting-note
```

Then run `validate_vault_schema` to find notes missing required fields.

### 3. Ingest — raw content → wiki

Drop articles, rough notes, or research into vault `inbox/` folder. Workflow:

```
1. list_inbox                  → see what's pending
2. read each item              → understand the content
3. find_related_notes(content) → discover existing notes it relates to
4. update those notes          → integrate the new knowledge
5. archive_inbox_note          → move source to archive/YYYY-MM/
```

Claude does the synthesis. The MCP just handles bookkeeping.

## Development

```bash
# Install dev dependencies
.venv/bin/pip install -e ".[dev]"

# Run tests
.venv/bin/pytest tests/ -v

# Lint
.venv/bin/ruff check .
```

## Testing with MCP Inspector

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m obsidian_mcp
```

## Vault Explorer

A browser UI bundled in the same package — for **debugging** retrieval
("why did this note rank where it did?"), **visualizing** the wikilink
graph alongside live query hits, and **demoing** the semantic + graph
stack to teammates. Query box, ranked results with per-signal score
breakdown bars, slider-tunable re-rank weights with presets, and a
Cytoscape graph view that highlights hits and neighbors.

### Local

```bash
.venv/bin/pip install -e ".[explorer]"
OBSIDIAN_VAULT_PATH=/path/to/vault .venv/bin/python -m obsidian_mcp.explorer
# open http://127.0.0.1:8765
```

### Docker

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
server, so changes you make in Claude Code or Obsidian show up live.
Tuning a weight slider re-issues the query against the current index;
no server restart needed.

#### Endpoints

- `GET /` — single-page UI
- `GET /api/health` — vault path, semantic state, embedding stats
- `POST /api/search` — body `{query, k, weights?}` → ranked results with
  `cos_sim`, per-signal `contributions`, and `signals` breakdown
- `GET /api/graph` — Cytoscape-friendly `{nodes, edges}` of the vault
  wikilink graph
- `GET /api/note?path=...` — full note content + frontmatter

