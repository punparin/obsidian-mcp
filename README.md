# Obsidian MCP Server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that gives Claude Code full read/write access to an Obsidian vault. Built with [FastMCP](https://github.com/jlowin/fastmcp).

## Architecture

```mermaid
flowchart LR
    User([👤 You]) -->|prompts| Claude[🤖 Claude Code]
    Claude <-->|MCP STDIO| Server[Obsidian MCP Server]
    Server -->|file ops| Vault[(📚 Obsidian Vault)]
    Vault -.auto-loaded.-> Resources[obsidian://vault-map<br/>obsidian://mocs]
    Resources -.context.-> Claude

    style User fill:#e1f5ff
    style Claude fill:#fff4e1
    style Server fill:#e8f5e9
    style Vault fill:#f3e5f5
```

## Tool Categories

```mermaid
flowchart TD
    MCP[Obsidian MCP<br/>16 tools + 2 resources]

    MCP --> FileOps[📝 File Operations<br/>6 tools]
    MCP --> Search[🔍 Search<br/>4 tools]
    MCP --> Frontmatter[📋 Frontmatter<br/>2 tools]
    MCP --> Links[🔗 Links & Graph<br/>3 tools]
    MCP --> Templates[📄 Templates<br/>1 tool]
    MCP --> Resources[💾 Resources<br/>2 auto-loaded]

    FileOps --> F1[read_note, write_note,<br/>append_note, list_notes,<br/>delete_note, move_note]
    Search --> S1[search, search_by_tags,<br/>search_by_frontmatter,<br/>search_by_date_range]
    Frontmatter --> FM1[get_note_frontmatter,<br/>update_note_frontmatter]
    Links --> L1[get_backlinks, get_wikilinks,<br/>get_vault_graph,<br/>get_orphan_notes]
    Templates --> T1[create_note_from_template]
    Resources --> R1[vault-map index,<br/>MOC files]

    style MCP fill:#fff4e1
    style FileOps fill:#e8f5e9
    style Search fill:#e3f2fd
    style Frontmatter fill:#fff3e0
    style Links fill:#f3e5f5
    style Templates fill:#fce4ec
    style Resources fill:#e0f7fa
```

## How Claude Uses Your Vault

```mermaid
sequenceDiagram
    participant U as You
    participant C as Claude Code
    participant M as Obsidian MCP
    participant V as Vault

    U->>C: "What did we decide about API rate limiting?"
    C->>M: read obsidian://vault-map
    M->>V: scan all .md files
    V-->>M: notes index
    M-->>C: vault structure + metadata
    C->>M: search_by_tags(["rate-limiting"])
    M->>V: filter index
    V-->>M: matching notes
    M-->>C: list of notes
    C->>M: read_note("decisions/rate-limiting.md")
    M->>V: read file
    V-->>M: content
    M-->>C: full note
    C->>U: "We chose token bucket because..."
```

## Features

**16 tools + 2 resources** for complete vault management:

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
| Templates | `create_note_from_template` | Create note from template with {{variables}} |

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
