# Configuration

## Vault path

Set the vault path via environment variable on the MCP server process:

```bash
export OBSIDIAN_VAULT_PATH=/path/to/your/obsidian/vault
```

When using Docker, mount the vault and rely on the image default
(`/vault`):

```bash
docker run -i --rm \
  -v /path/to/your/vault:/vault \
  ghcr.io/punparin/obsidian-mcp:latest
```

## Embedding backend

Set `OBSIDIAN_EMBEDDER` to one of `ollama`, `fastembed`, or `none`.
See [`semantic.md`](./semantic.md#embedder-selection) for the full
table and recommended models.

## Ignoring folders / files

By default the server scans every `.md` file in the vault. To keep
drafts, an archive, or vendored notes out of indexing / search /
embeddings, drop a config file at `<vault>/.obsidian-mcp/config.yml`:

```yaml
ignore:
  - "archive/**"
  - "private/**"
  - "drafts/"
  - "*.tmp.md"
```

Patterns are gitignore-style globs and are matched against the
vault-relative path. Built-ins (`.obsidian/`, `.git/`, `.trash/`,
`.stversions/`, `.obsidian-mcp/`, `*.swp`/`*.tmp`/`*.swx`,
`.~lock*`) are always ignored regardless of config.

Ignore = "don't surface in scans". Explicit `read_note(path)` /
`write_note(path)` calls still work on ignored paths so the model can
poke at them when you ask it to. The same predicate also gates the
filesystem watcher and the background embed queue, so live edits
under an ignored folder don't sneak into the index either.

A malformed config fails loudly at startup rather than silently doing
the wrong thing — fix the YAML or remove the file.

## Live vault sync

The server keeps its in-memory index in sync with the vault via a
filesystem watcher (backed by `watchdog`). Edits you make directly in
Obsidian — or any other tool — are reflected in the next MCP query
without restarting the server.

The watcher also backs **conflict detection on writes**: if a note
changed on disk between the agent's last `read_note` and its next
`write_note` on the same path, the write is refused with a
`NoteConflictError` so you don't clobber an edit made in Obsidian.
The error carries the *current disk content* (~4 KB cap) so the agent
can three-way-merge in place instead of needing a follow-up read.
Pass `force=true` to override intentionally.

Directories like `.obsidian/`, `.git/`, `.trash/`, and non-markdown
files are ignored by the watcher.
