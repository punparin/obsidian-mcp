# Installation Guide (for AI agents)

> **For the human:** paste this file's URL into your MCP-capable agent
> (Claude Code, Cursor, Cline, …) and say *"read this and help me install
> it."* The agent will ask you everything it needs as it goes.

> **For the agent:** these are step-by-step instructions for installing
> the Obsidian MCP server on the current user's machine. Follow them
> top-to-bottom. **Ask the user any question whose answer isn't already
> in their messages or in the host environment — never assume defaults
> for paths, URLs, or models.** Only proceed once each prompt is
> answered. If a command fails, stop and report; do not guess fixes.

---

## Step 0 — Confirm the host

Before anything else, run these and report the results to the user:

```sh
uname -s             # Linux / Darwin / (WSL on Windows)
docker --version     # may fail — that's fine, we'll branch on it
python3 --version    # need 3.11+ for the local install path
```

If `docker` is not installed AND `python3` is older than 3.11, **stop and
ask the user to install one of them** before continuing. Do not try to
install Docker or upgrade Python yourself.

---

## Step 1 — Ask: which MCP client?

Ask the user which agent will host the MCP server. Examples: Claude Code,
Cursor, Cline, Continue, Goose, Windsurf, something else.

The registration command differs per client. This guide covers
**Claude Code** in detail (via `claude mcp add`). If the user names a
different client, fall through to *Step 6 — Manual JSON registration*
and build a JSON snippet they can paste into their client's MCP config —
do not invent a CLI for a client you don't know.

---

## Step 2 — Ask: where is the Obsidian vault?

Required. **Do not guess this.** Common locations the user might mention
(`~/Documents/Obsidian`, `~/Notes`, `~/vault`) are hints, not defaults.

Prompt:

> *"What is the absolute path to your Obsidian vault? (e.g.
> `/home/you/Documents/MyVault` — the folder that contains your `.md`
> files and an `.obsidian/` subfolder)"*

Then verify:

```sh
ls "<vault-path>/.obsidian" >/dev/null 2>&1 && echo "OK" || echo "MISSING"
```

If `MISSING`, ask the user to confirm the path is correct before moving
on. Don't proceed on a path that doesn't look like a vault.

Save the answer as `VAULT_PATH`.

---

## Step 3 — Ask: which runtime?

Two install paths. Ask the user to pick one:

| Option | When to use | What you'll need |
|---|---|---|
| **A. Docker** *(recommended)* | The user has Docker running. Slim, no Python deps to manage. | `docker` available |
| **B. Local virtualenv** | No Docker, or user prefers a Python install. | Python 3.11+, `git` |

If `docker --version` failed in Step 0, surface that and recommend option
B. If both work, ask the user to pick.

Save the answer as `RUNTIME` ∈ {`docker`, `local`}.

---

## Step 4 — Ask: semantic search?

The server has three embedding backends. Ask the user:

> *"Do you want semantic search over your vault? Three options:*
> *1. **`ollama`** — recommended if you already run an [Ollama](https://ollama.com)*
>    *server (e.g. on a desktop GPU box). Best quality, slim install.*
> *2. **`fastembed`** — in-process embedding, downloads ~130 MB on first*
>    *use. Single-host, no extra service needed. Local-only.*
> *3. **`none`** — skip semantic features; only lexical search and graph*
>    *tools work."*

Save the answer as `EMBEDDER` ∈ {`ollama`, `fastembed`, `none`}.

### 4a. If `EMBEDDER=ollama`, ask two follow-ups

- **Ollama URL.** Prompt: *"What's the URL of your Ollama server? (e.g.
  `http://localhost:11434` if it's on this machine, or
  `http://desktop.local:11434` for another box on your LAN)"* — save as
  `OLLAMA_URL`. Verify it's reachable:
  ```sh
  curl -sf "$OLLAMA_URL/api/tags" >/dev/null && echo "OK" || echo "UNREACHABLE"
  ```
  If `UNREACHABLE`, ask the user to confirm the URL or start Ollama
  before continuing. Don't proceed.

- **Embedding model.** Prompt: *"Which embedding model? Options that show
  up in `ollama list` on your server. Common picks: `qwen3-embedding:8b`
  (best, ~16 KB/vector), `qwen3-embedding:4b` (sweet spot), `bge-m3`
  (lightweight multilingual), `nomic-embed-text` (small, fast). If
  unsure, `qwen3-embedding:4b` is a safe default — confirm with me
  before I use it."* Save as `EMBEDDER_MODEL`.

  Verify the model exists on the server:
  ```sh
  curl -sf "$OLLAMA_URL/api/tags" | grep -q "\"$EMBEDDER_MODEL\"" \
    && echo "OK" || echo "MODEL_MISSING"
  ```
  If `MODEL_MISSING`, tell the user how to pull it (`ollama pull
  $EMBEDDER_MODEL` on the Ollama host) and **wait for them to confirm
  before proceeding**.

### 4b. If `EMBEDDER=fastembed` and `RUNTIME=docker`

The default Docker image does **not** include `fastembed`. Tell the
user: *"The Docker image ships without fastembed. Switch to `ollama`,
`none`, or use the local runtime to keep fastembed."* Re-ask Step 3 or
Step 4 based on what they want.

### 4c. If `EMBEDDER=none`

Nothing extra to ask. The semantic tools will be no-ops.

---

## Step 5 — Ask: scope?

Ask: *"Should this MCP be available in **all your projects** (user
scope) or only in the **current project** (project scope, written to a
checked-in `.mcp.json`)?"*

Save as `SCOPE` ∈ {`user`, `project`}. Translate to flag:

- `user` → `-s user`
- `project` → `-s project`

If the user's client is not Claude Code, this maps to whatever the
client's equivalent is — see Step 6.

---

## Step 6 — Install

### Path A — Docker

Pull the image first:

```sh
docker pull ghcr.io/punparin/obsidian-mcp:latest
```

Then build the registration command. Compose env-var flags from the
user's answers:

```sh
# Build env flags based on EMBEDDER answer:
#   ollama:    -e OBSIDIAN_EMBEDDER=ollama \
#              -e OBSIDIAN_EMBEDDER_MODEL=$EMBEDDER_MODEL \
#              -e OLLAMA_URL=$OLLAMA_URL
#   none:      -e OBSIDIAN_EMBEDDER=none
#   fastembed: (not supported on Docker — see 4b)

claude mcp add -s "$SCOPE" obsidian -- \
  docker run -i --rm \
    -v "$VAULT_PATH:/vault" \
    <env flags from above> \
    ghcr.io/punparin/obsidian-mcp:latest
```

**Show the user the exact command you're about to run, with their
answers substituted, and ask them to confirm before executing.**

### Path B — Local virtualenv

Ask: *"Where should I clone the repo? (e.g. `~/repos/obsidian-mcp`)"* —
save as `INSTALL_DIR`. Then:

```sh
git clone https://github.com/punparin/obsidian-mcp.git "$INSTALL_DIR"
cd "$INSTALL_DIR"
python3 -m venv .venv
```

Pick the `pip install` command based on `EMBEDDER`:

- `EMBEDDER=fastembed` → `.venv/bin/pip install -e ".[fastembed]"`
- `EMBEDDER=ollama` or `EMBEDDER=none` → `.venv/bin/pip install -e .`

Register with Claude Code. Build env flags:

```sh
# Common to all:
#   -e OBSIDIAN_VAULT_PATH=$VAULT_PATH
# Plus, depending on EMBEDDER:
#   ollama:    -e OBSIDIAN_EMBEDDER=ollama \
#              -e OBSIDIAN_EMBEDDER_MODEL=$EMBEDDER_MODEL \
#              -e OLLAMA_URL=$OLLAMA_URL
#   fastembed: -e OBSIDIAN_EMBEDDER=fastembed
#   none:      -e OBSIDIAN_EMBEDDER=none

claude mcp add -s "$SCOPE" obsidian \
  <env flags> \
  -- "$INSTALL_DIR/.venv/bin/python" -m obsidian_mcp
```

**Confirm the command with the user before running.**

### Path C — Manual JSON for non-Claude-Code clients

If the user's client isn't Claude Code (e.g. Cursor, Cline, Goose),
print a JSON snippet they can paste into their client's MCP config and
ask them to confirm where their config file lives — do not write to it
yourself unless they tell you the exact path.

For Docker:

```json
{
  "obsidian": {
    "command": "docker",
    "args": [
      "run", "-i", "--rm",
      "-v", "<VAULT_PATH>:/vault",
      "-e", "OBSIDIAN_EMBEDDER=<EMBEDDER>",
      "...other -e flags as above...",
      "ghcr.io/punparin/obsidian-mcp:latest"
    ]
  }
}
```

For local:

```json
{
  "obsidian": {
    "command": "<INSTALL_DIR>/.venv/bin/python",
    "args": ["-m", "obsidian_mcp"],
    "env": {
      "OBSIDIAN_VAULT_PATH": "<VAULT_PATH>",
      "OBSIDIAN_EMBEDDER": "<EMBEDDER>",
      "...": "..."
    }
  }
}
```

Substitute every `<…>` placeholder with the user's answers. **Do not
ship placeholders.**

---

## Step 7 — Verify

After registration, ask the user to:

1. **Restart their MCP client** (Claude Code: quit and reopen; for other
   clients, follow that client's docs).
2. Ask the agent something like *"list the notes I have under projects/"*
   and confirm the agent calls `list_notes` and returns results.

If the agent says it doesn't see the `obsidian` MCP, run:

```sh
claude mcp list           # Claude Code only
```

…and report the output. If `obsidian` is missing from the list, the
registration didn't take — re-check the command from Step 6 with the
user.

If the server appears but tool calls fail, ask the user to share the
client-side error message verbatim. Common causes:

- Vault path is wrong or not mounted (Docker `-v` flag).
- `OBSIDIAN_VAULT_PATH` env var not propagated (local install).
- For semantic tools: `OLLAMA_URL` unreachable from inside the container.
  Test from inside Docker: `docker run --rm
  ghcr.io/punparin/obsidian-mcp:latest curl -sf "$OLLAMA_URL/api/tags"`.
- For semantic tools with `fastembed`: first call downloads ~130 MB
  silently. Tail the agent's MCP logs to see progress; warn the user
  the first query may take a minute.

---

## Step 8 — Optional: Vault Explorer

Ask: *"Do you want the browser-based Vault Explorer too? It runs
alongside the MCP server on port 8765 and is useful for debugging which
notes the agent finds and why."*

If yes, mirror the runtime choice from Step 3:

- **Docker:**
  ```sh
  docker pull ghcr.io/punparin/obsidian-mcp-explorer:latest
  docker run --rm -p 8765:8765 -v "$VAULT_PATH:/vault" \
    ghcr.io/punparin/obsidian-mcp-explorer:latest
  ```
- **Local:**
  ```sh
  cd "$INSTALL_DIR"
  .venv/bin/pip install -e ".[explorer]"
  OBSIDIAN_VAULT_PATH="$VAULT_PATH" .venv/bin/python -m obsidian_mcp.explorer
  ```

Then open <http://127.0.0.1:8765>. The Explorer reads the same SQLite
index the MCP writes to, so changes from the agent (or from Obsidian
itself) show up live.

---

## Step 9 — Done

Summarize back to the user:

- Vault path
- Runtime (Docker / local)
- Embedder (ollama + model + URL, fastembed, or none)
- Scope
- Whether the Explorer was installed

…and tell them which client restart they still need to do, if any.
