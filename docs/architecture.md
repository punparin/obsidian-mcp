# Architecture

How Obsidian MCP fits between you, your agent, and your vault.

## Components

```mermaid
flowchart LR
    User[You]
    Agent[MCP Client / Agent]
    Server[Obsidian MCP]
    Vault[(Obsidian Vault)]

    User --> Agent
    Agent <--> Server
    Server --> Vault
    Vault -.-> Server

    classDef user fill:#e1f5ff,stroke:#333
    classDef ai fill:#fff4e1,stroke:#333
    classDef mcp fill:#e8f5e9,stroke:#333
    classDef store fill:#f3e5f5,stroke:#333

    class User user
    class Agent ai
    class Server mcp
    class Vault store
```

The server speaks stdio MCP — any MCP-capable client (Claude Code,
Cursor, Cline, Continue, Goose, Windsurf, etc.) can register it.

## Tool categories

```mermaid
flowchart TD
    MCP[Obsidian MCP - 34 tools]

    MCP --> FileOps[File Operations - 6 tools]
    MCP --> Search[Search - 4 tools]
    MCP --> Meta[Frontmatter - 2 tools]
    MCP --> Links[Links and Graph - 4 tools]
    MCP --> Tpl[Templates - 1 tool]
    MCP --> Lint[Lint - 4 tools]
    MCP --> Schema[Schema - 3 tools]
    MCP --> Ingest[Ingest - 3 tools]
    MCP --> Sem[Semantic - 3 tools]
    MCP --> Sug[Suggest - 3 tools]
    MCP --> Gnd[Groundedness - 1 tool]
    MCP --> Res[Resources - 2 auto-loaded]

    FileOps --> F1[read_note, write_note, append_note, list_notes, delete_note, move_note]
    Search --> S1[search, search_by_tags, search_by_frontmatter, search_by_date_range]
    Meta --> FM1[get_note_frontmatter, update_note_frontmatter]
    Links --> L1[get_backlinks, get_wikilinks, get_vault_graph, get_orphan_notes]
    Tpl --> T1[create_note_from_template]
    Lint --> LI1[find_broken_wikilinks, find_stale_notes, find_duplicate_titles, lint_vault]
    Schema --> SC1[get_schema, validate_note_schema, validate_vault_schema]
    Ingest --> IN1[list_inbox, find_related_notes, archive_inbox_note]
    Sem --> SM1[semantic_search, rebuild_embeddings, embedding_stats]
    Sug --> SG1[suggest_links, apply_link_suggestion, dismiss_link_suggestion]
    Res --> R1[vault-map, mocs]
```

See [`tools.md`](./tools.md) for the full per-tool reference.

## How an agent uses your vault

```mermaid
sequenceDiagram
    actor User
    participant Agent as MCP Client
    participant MCP as Obsidian MCP
    participant Index as In-memory index + vector store
    participant Vault

    User->>Agent: What did we decide about rate limiting?
    Agent->>MCP: semantic_search("rate limiting decision")
    MCP->>Index: embed query, kNN over chunks, graph re-rank
    Index-->>MCP: ranked notes with cos_sim + graph signals
    MCP-->>Agent: top hits + score breakdown
    Agent->>MCP: read_note decisions/rate-limiting.md
    MCP->>Vault: read file
    Vault-->>MCP: content + frontmatter
    MCP-->>Agent: full note
    Agent->>User: We chose token bucket because...
```

The index and vector store live under `<vault>/.obsidian-mcp/` and stay
in sync with the vault via the filesystem watcher — the agent never
needs to re-scan to see your latest edits.

See [`semantic.md`](./semantic.md) for the re-rank formula and
[`configuration.md`](./configuration.md#live-vault-sync) for the
watcher's conflict-detection behaviour on writes.
