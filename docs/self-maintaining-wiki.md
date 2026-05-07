# Self-Maintaining Wiki

Inspired by [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
Three layers turn your vault into a knowledge base that compounds over
time.

## 1. Lint — find rot before it spreads

Run `lint_vault` periodically. It catches:

- **Broken wikilinks** — notes you renamed without updating references.
- **Stale notes** — old content still linked from recent work; review
  or update.
- **Duplicate titles** — causes wikilink ambiguity.
- **Orphan notes** — disconnected knowledge.

## 2. Schema — structured note types

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

Then run `validate_vault_schema` to find notes missing required
fields.

## 3. Ingest — raw content → wiki

Drop articles, rough notes, or research into the vault's `inbox/`
folder. Workflow:

```
1. list_inbox                  → see what's pending
2. read each item              → understand the content
3. find_related_notes(content) → discover existing notes it relates to
4. update those notes          → integrate the new knowledge
5. archive_inbox_note          → move source to archive/YYYY-MM/
```

The agent does the synthesis. The MCP just handles bookkeeping.
