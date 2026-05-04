"""Ignore-pattern matcher for vault scanning.

The MCP normally walks every `.md` file under the vault for indexing,
search, and embedding. Some folders shouldn't be surfaced — drafts, an
archive, vendored notes, scratch space — and a few infrastructure
directories (`.obsidian/`, `.git/`, our own `.obsidian-mcp/`) must
always be skipped regardless of user config.

This module loads `<vault>/.obsidian-mcp/config.yml` (key `ignore:`,
gitignore-style globs) and combines the user's patterns with a
hardcoded set of always-ignored built-ins. The resulting matcher is
the single predicate every scan/event path consults via
`Vault.is_ignored(rel_path)`.

Notes:
- Patterns are matched against the *vault-relative* posix path
  (forward slashes, no leading `/`).
- Ignore = "don't surface in scans" — explicit `read_note(path)` and
  `write_note(path)` still work on ignored paths so the model can
  poke at them when needed.
- Non-`.md` files are uniformly ignored upstream of this matcher; the
  matcher only sees markdown candidates plus directory probes from
  the watcher.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import pathspec
import yaml

logger = logging.getLogger(__name__)

CONFIG_DIR_NAME = ".obsidian-mcp"
CONFIG_FILE_NAME = "config.yml"

# Always-ignored, regardless of user config. Drawn from the previous
# watcher-only list plus our own state directory. Patterns are
# gitignore-style: `name/` matches the directory at any depth, `*.swp`
# matches the suffix anywhere.
BUILTIN_IGNORES: tuple[str, ...] = (
    ".obsidian/",
    ".obsidian-mcp/",
    ".git/",
    ".trash/",
    ".stversions/",
    "*.swp",
    "*.swx",
    "*.tmp",
    ".~lock*",
)


class IgnoreMatcher:
    """Combines built-in ignores with user-defined patterns from
    `<vault>/.obsidian-mcp/config.yml` (`ignore:` key)."""

    def __init__(self, user_patterns: Iterable[str] = ()):
        patterns = list(BUILTIN_IGNORES) + list(user_patterns)
        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        self._user_patterns: tuple[str, ...] = tuple(user_patterns)

    @property
    def user_patterns(self) -> tuple[str, ...]:
        return self._user_patterns

    def matches(self, rel_path: str) -> bool:
        """True if `rel_path` (vault-relative, forward-slash) is ignored."""
        # PathSpec expects posix-style paths; normalise to be safe.
        norm = rel_path.replace("\\", "/").lstrip("/")
        if not norm:
            return False
        return self._spec.match_file(norm)


def load_ignore_config(vault: Path) -> list[str]:
    """Read `<vault>/.obsidian-mcp/config.yml` and return its `ignore:` list.

    Returns an empty list when the file is absent or doesn't have an
    `ignore:` key (so users can keep the file around for future
    settings without forcing them to declare ignores). Raises
    `ValueError` when the file is present but malformed (unparseable
    YAML, non-list value, non-string entries).
    """
    cfg_path = vault / CONFIG_DIR_NAME / CONFIG_FILE_NAME
    if not cfg_path.exists():
        return []
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"failed to parse {cfg_path}: {e}") from e
    if data is None:
        return []
    if not isinstance(data, dict):
        raise ValueError(f"{cfg_path}: top-level must be a mapping")
    raw = data.get("ignore", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{cfg_path}: `ignore` must be a list of glob patterns")
    out: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{cfg_path}: every ignore pattern must be a non-empty string")
        out.append(entry.strip())
    return out


def build_matcher(vault: Path) -> IgnoreMatcher:
    """Convenience: read the config and return a ready-to-use matcher."""
    return IgnoreMatcher(load_ignore_config(vault))
