# Contributing

Thanks for picking this up. The bar is "small, focused PRs with tests" — that's it. The repo is open to teammates and to the wider community on the same terms.

## Dev setup

```bash
git clone https://github.com/punparin/obsidian-mcp.git
cd obsidian-mcp
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,explorer]"
.venv/bin/pre-commit install   # gates `git commit` on lint
```

`fastembed` is an optional extra (`pip install -e ".[dev,fastembed]"`). The base install + `OBSIDIAN_EMBEDDER=ollama` is the default path used in CI and Docker. Pick whichever fits your machine.

## Running tests

```bash
.venv/bin/pytest tests/ -v
```

Tests use a `fake` embedding backend, so you don't need Ollama or a downloaded model to run the suite.

## Linting

```bash
.venv/bin/ruff check .
.venv/bin/ruff check --fix .          # auto-fix
.venv/bin/pre-commit run --all-files  # what CI runs
```

Lint failures block the Docker build job in CI. Fix locally before pushing.

## Branch naming

`<type>/<short-kebab-description>` where `<type>` is one of `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`.

Examples: `feat/explorer-link-suggestions`, `fix/wikilink-resolver-case-sensitivity`.

## Commit + PR title

[Conventional Commits](https://www.conventionalcommits.org/): `<type>(<scope>)?: <imperative summary, lowercase, no trailing period>`, ≤70 characters.

Examples:
- `feat(explorer): show package version in header`
- `fix(semantic): keep embedding_stats fresh on startup`
- `docs: refresh tool counts and embedder notes`

## PR body

```markdown
## Summary
- 1–3 bullets: what changed and why
```

Include "Closes #N" if it fixes an open issue. Skip the AI-coauthor footers — they don't add anything.

## What we look for

- **Tests for new behavior.** Especially in `semantic.py`, `suggest.py`, `vector_store.py`, `links.py` — these are the parts where regressions are easiest to introduce and hardest to spot.
- **One logical change per PR.** A bug fix doesn't need surrounding cleanup; a new tool doesn't need to refactor the watcher. Two changes → two PRs.
- **No new config knobs without docs.** If you're adding an env var or tool argument, document it in the README and (if it's a load-bearing convention) in `CLAUDE.md`.
- **For Explorer UI changes**, drop a screenshot or short clip in the PR.

## Releases

Maintainer cuts releases. Workflow:

1. Bump `pyproject.toml` to the new version.
2. Merge as `chore: release vX.Y.Z`.
3. Push the matching tag (`git tag vX.Y.Z && git push origin vX.Y.Z`).

Tag push triggers `docker.yml` (builds + pushes ghcr images) and `release.yml` (creates the GitHub Release with auto-generated notes). No manual release-notes editing needed unless something exceptional happened.
