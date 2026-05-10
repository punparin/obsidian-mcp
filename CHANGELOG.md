# Changelog

All notable changes to this project are documented here. Format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.10.0] - 2026-05-10

### Added

- `check_groundedness` MCP tool — scans a draft answer for
  register-shift markers ("generally speaking", "typically,", "based
  on my training", …) so the agent can self-check before responding.
  Tool count: 33 → 34. (#58)
- Retrieval eval harness — 19-note labeled corpus + 18 hand-labeled
  `(query, expected_paths)` pairs. Marker-gated `pytest -m eval`
  asserts floors on hit@1/3/5 and MRR; CLI runner at
  `scripts/eval_retrieval.py` for ad-hoc embedder comparisons.
  Baseline on BGE-small: 0.94 / 1.00 / 1.00 / 0.972. (#59)
- CI quality gate — new `eval` job runs the eval on every PR with a
  cached fastembed model, renders metrics into the workflow's job
  summary, and gates the Docker build/push on quality. (#59)

## [0.9.0] - 2026-05-07

### Added

- Subtree-scoped search: `search`, `search_by_tags`,
  `search_by_frontmatter`, `search_by_date_range` accept `path=` to
  limit results to a folder. (#49)
- `list_notes` can include parsed YAML frontmatter alongside each
  path via `include_frontmatter=True`, avoiding per-note follow-up
  reads. (#50)
- `NoteConflictError` carries the current disk content (~4 KB cap)
  so agents can three-way-merge in place. (#51)
- Multi-field AND for `search_by_frontmatter` via
  `filters={...}`. (#52)
- MCP `instructions` field — operating rules ship via the
  `initialize` response from `obsidian_mcp/agent_instructions.py`,
  so agents don't have to paste them into their own rules. (#53)

### Changed

- AGENT.md trimmed to operator-only content; tool/flow rules now
  live in the auto-injected MCP instructions. (#54, #55)
- Reference docs (`docs/tools.md`, `docs/configuration.md`)
  refreshed for the new surface. (#56)

## [0.8.4] - 2026-05-04

### Added

- Ignore folders/files via vault config. (#37)

## [0.8.3] - 2026-05-01

### Fixed

- Stabilize Explorer viewport layout to stop scrollbar flicker.
  Thanks @neutronth. (#35)

## [0.8.2] - 2026-04-30

### Added

- LICENSE and quickstart for team onboarding. (#30)
- `CONTRIBUTING.md`. (#31)
- GitHub issue templates. (#32)
- Ollama startup health check with actionable hints. (#33)

### Changed

- README decoupled from Claude-Code-specific phrasing. (#29)

## [0.8.1] - 2026-04-30

### Changed

- Tool counts and embedder notes refreshed for the v0.8 line. (#26)
- Vault-usage diagram fixed; version markers dropped. (#27)

## [0.8.0] - 2026-04-27

### Changed

- Explorer link-suggestions view widened; both side snippets shown
  inline. (#24)

## [0.7.0] - 2026-04-26

### Changed

- `fastembed` dropped from the base install; Docker now defaults to
  Ollama. The fastembed extra remains available for single-host
  setups. (#22)
- Docs recommend `qwen3-embedding` as the top Ollama choice. (#21)

## [0.6.0] - 2026-04-26

### Added

- Ollama embedding backend. (#19)
- Auto-reindex on model change — vector store records active model
  and dim; index is cleared and re-embedded if either changes. (#19)

### Changed

- Auto-link tools covered in the Claude Code usage guide. (#18)

## [0.5.0] - 2026-04-25

### Added

- Auto-link suggestions: `suggest_links`, `apply_link_suggestion`,
  `dismiss_link_suggestion` with persistent dismissals. (#15)

### Changed

- Pre-commit hook + CI lint gate. (#16)

## [0.4.1] - 2026-04-25

### Added

- Explorer glossary section explaining each term. (#13)

## [0.4.0] - 2026-04-25

### Added

- Vault Explorer — browser UI for debugging retrieval and
  visualizing the wikilink graph. (#11)

## [0.3.1] - 2026-04-25

### Fixed

- Keep `embedding_stats` fresh on startup and after edits. (#9)

## [0.3.0] - 2026-04-25

### Added

- Live vault sync via filesystem watcher. (#5)
- Semantic retrieval with graph-aware re-rank — kNN over chunk
  embeddings, re-ranked using wikilink/tag/neighbor/recency
  signals. (#6)

### Changed

- Claude Code usage guide added. (#7)

## [0.2.0] - 2026-04-09

### Added

- Self-maintaining wiki — lint, schema validation, ingest. (#4)

### Changed

- README architecture diagrams. (#3)

## [0.0.2] - 2026-04-08

### Added

- `get_orphan_notes` tool. (#2)

## [0.0.1] - 2026-04-08

### Added

- Initial release with Docker support. (#1)
