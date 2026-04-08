"""Wikilink extraction, backlink resolution, and vault graph."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .vault import NoteIndex

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(content: str) -> list[str]:
    """Extract all wikilink targets from content.

    Handles:
    - [[Note Name]] -> "Note Name"
    - [[Note Name|alias]] -> "Note Name" (strips display text)
    - [[Note Name#heading]] -> "Note Name" (strips heading ref)
    - [[folder/Note Name]] -> "folder/Note Name"

    Returns deduplicated list of link targets.
    """
    targets = []
    for match in WIKILINK_RE.finditer(content):
        raw = match.group(1)
        # Strip alias (|display text)
        target = raw.split("|")[0].strip()
        # Strip heading (#heading)
        target = target.split("#")[0].strip()
        if target and target not in targets:
            targets.append(target)
    return targets


def resolve_wikilink(link_target: str, index: dict[str, NoteIndex]) -> str | None:
    """Resolve a wikilink target to a relative path in the vault.

    Obsidian resolves by:
    1. Exact path match first (with .md added if needed)
    2. Filename-only match (case-insensitive, without .md)

    Returns the relative path or None if unresolved.
    """
    # Try exact path match
    candidate = link_target if link_target.endswith(".md") else f"{link_target}.md"
    if candidate in index:
        return candidate

    # Try filename-only match (case-insensitive)
    target_lower = link_target.lower()
    for path in index:
        stem = Path(path).stem.lower()
        if stem == target_lower:
            return path

    return None


def get_backlinks(note_path: str, index: dict[str, NoteIndex]) -> list[str]:
    """Find all notes that link TO the given note via wikilinks.

    Returns list of relative paths of notes containing a link to note_path.
    """
    note_stem = Path(note_path).stem
    backlinks = []

    for path, note in index.items():
        if path == note_path:
            continue
        for link in note.links:
            resolved = resolve_wikilink(link, index)
            if resolved == note_path:
                backlinks.append(path)
                break
            # Also match by stem (Obsidian shorthand)
            if link.lower() == note_stem.lower():
                backlinks.append(path)
                break

    return backlinks


def get_graph(index: dict[str, NoteIndex]) -> dict:
    """Build adjacency-list representation of vault link graph.

    Returns {
        "nodes": [{"path": "...", "title": "...", "tags": [...]}],
        "edges": [{"source": "...", "target": "...", "resolved": bool}]
    }
    """
    nodes = []
    edges = []

    for path, note in index.items():
        nodes.append({"path": path, "title": note.title, "tags": note.tags})
        for link in note.links:
            resolved = resolve_wikilink(link, index)
            edges.append({
                "source": path,
                "target": resolved or link,
                "resolved": resolved is not None,
            })

    return {"nodes": nodes, "edges": edges}


def update_wikilinks_across_vault(
    vault_root: Path,
    old_name: str,
    new_name: str,
    index: dict[str, NoteIndex],
) -> list[str]:
    """After a note is moved/renamed, update all wikilinks that reference it.

    old_name: the previous filename stem (without .md)
    new_name: the new filename stem (without .md)

    Returns list of updated file paths (relative).
    """
    updated = []

    def _replace_link(match: re.Match) -> str:
        raw = match.group(1)
        parts = re.split(r"[|#]", raw, maxsplit=1)
        target = parts[0].strip()
        if target.lower() == old_name.lower():
            suffix = raw[len(parts[0]):] if len(parts) > 1 else ""
            return f"[[{new_name}{suffix}]]"
        return match.group(0)

    for path, note in index.items():
        # Check if this note links to the old name
        has_old_link = any(
            link.lower() == old_name.lower() for link in note.links
        )
        if not has_old_link:
            continue

        file_path = vault_root / path
        content = file_path.read_text(encoding="utf-8")
        new_content = WIKILINK_RE.sub(_replace_link, content)

        if new_content != content:
            file_path.write_text(new_content, encoding="utf-8")
            updated.append(path)

    return updated
