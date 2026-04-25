"""Vault linting — find broken links, stale notes, duplicates, and consistency issues."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .links import resolve_wikilink

if TYPE_CHECKING:
    from .vault import Vault


def find_broken_wikilinks(vault: "Vault") -> list[dict]:
    """Find wikilinks that don't resolve to any note in the vault.

    Returns list of {source: path, broken_link: target} dicts.
    """
    broken = []
    for path, note in vault.index.items():
        for link in note.links:
            if resolve_wikilink(link, vault.index) is None:
                broken.append({"source": path, "broken_link": link})
    return broken


def find_stale_notes(vault: "Vault", months: int = 6) -> list[dict]:
    """Find notes not modified in N months but still linked from recent notes.

    These are candidates for review/update — old content people still reference.
    """
    cutoff = (date.today() - timedelta(days=months * 30)).isoformat()
    recent_cutoff = (date.today() - timedelta(days=30)).isoformat()

    # Build link target → linking notes map
    incoming = defaultdict(set)
    for path, note in vault.index.items():
        for link in note.links:
            resolved = resolve_wikilink(link, vault.index)
            if resolved:
                incoming[resolved].add(path)

    stale = []
    for path, note in vault.index.items():
        if note.modified[:10] >= cutoff:
            continue
        # Stale and linked from a recent note?
        recent_linkers = [
            p for p in incoming.get(path, set())
            if vault.index[p].modified[:10] >= recent_cutoff
        ]
        if recent_linkers:
            stale.append({
                "path": path,
                "modified": note.modified[:10],
                "title": note.title,
                "linked_from_recent": recent_linkers,
            })
    return sorted(stale, key=lambda x: x["modified"])


def find_duplicate_titles(vault: "Vault") -> list[dict]:
    """Find notes that share the same title or filename stem.

    Causes wikilink ambiguity.
    """
    by_stem = defaultdict(list)
    for path, note in vault.index.items():
        stem = Path(path).stem.lower()
        by_stem[stem].append(path)

    duplicates = []
    for stem, paths in by_stem.items():
        if len(paths) > 1:
            duplicates.append({
                "stem": stem,
                "paths": sorted(paths),
                "count": len(paths),
            })
    return sorted(duplicates, key=lambda x: -x["count"])


def find_orphan_notes(vault: "Vault") -> list[dict]:
    """Find notes with zero backlinks. Excludes templates and MOCs."""
    return vault.get_orphan_notes()


def lint_vault(vault: "Vault", stale_months: int = 6) -> dict:
    """Run all lint checks and return aggregated report.

    Returns dict with: broken_wikilinks, stale_notes, duplicate_titles, orphan_notes
    """
    return {
        "broken_wikilinks": find_broken_wikilinks(vault),
        "stale_notes": find_stale_notes(vault, months=stale_months),
        "duplicate_titles": find_duplicate_titles(vault),
        "orphan_notes": find_orphan_notes(vault),
    }
