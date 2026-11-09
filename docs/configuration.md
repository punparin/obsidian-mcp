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

## Security model

The server is locked down so a confused or prompt-injected agent can't
do damage outside your notes:

- **Notes only.** Every tool can only touch `.md` files inside the
  vault. `..`, absolute paths, and symlinks that point outside the
  vault are refused.
- **No hidden folders.** Anything under a dot-folder (`.obsidian/`,
  `.git/`, `.trash/`, `.obsidian-mcp/`, …) is off-limits — so the agent
  can't install an Obsidian plugin, edit git hooks, or change its own
  ignore config.
- **Ignored paths are invisible.** See below.
- **No blind overwrites.** `write_note` won't replace an existing note
  the agent hasn't read first (see *Live vault sync*).
- **Deletes are recoverable.** `delete_note` moves the note into
  `.trash/` (Obsidian's own trash) instead of erasing it.
- **Size cap.** Notes larger than `OBSIDIAN_MAX_NOTE_BYTES` (default
  5 MB) can't be read or written.
- **Read-only mode.** Set `OBSIDIAN_READ_ONLY=1` and the write tools
  (`write_note`, `append_note`, `delete_note`, `move_note`,
  `update_note_frontmatter`, `create_note_from_template`,
  `archive_inbox_note`, `apply_link_suggestion`) aren't exposed at all.

With Docker you can tighten things further — no network (when
`OBSIDIAN_EMBEDDER=none`), no Linux capabilities, read-only image:

```bash
docker run -i --rm \
  --network none --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  -v /path/to/your/vault:/vault \
  -e OBSIDIAN_EMBEDDER=none -e OBSIDIAN_READ_ONLY=1 \
  ghcr.io/punparin/obsidian-mcp:latest
```

If you use a remote embedder (Ollama etc.), drop `--network none`.
Mount only the vault — never your home directory.

## Embedding backend

Set `OBSIDIAN_EMBEDDER` to one of `ollama`, `openai-compatible`,
`fastembed`, or `none`.
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

Ignored paths are fully off-limits: they're skipped by scans *and*
explicit `read_note(path)` / `write_note(path)` calls are refused. The
same predicate also gates the
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
Overwriting an existing note that was never read in this session is
refused the same way. Pass `force=true` to override intentionally.

Directories like `.obsidian/`, `.git/`, `.trash/`, and non-markdown
files are ignored by the watcher.
