"""Obsidian MCP Server — FastMCP entry point with all tool and resource registrations."""

import json
import logging
import os
import sys

from fastmcp import FastMCP

from .vault import Vault
from .frontmatter import get_frontmatter as _get_fm, update_frontmatter as _update_fm
from .links import get_backlinks as _backlinks, get_graph as _graph, extract_wikilinks as _wikilinks
from .templates import create_from_template as _from_template

# Logging to stderr (STDIO transport requirement)
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("obsidian_mcp")

# Vault initialization
vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")
if not vault_path:
    logger.error("OBSIDIAN_VAULT_PATH environment variable not set")
    sys.exit(1)

vault = Vault(vault_path)
mcp = FastMCP("obsidian")


# ── Core File Operations ──────────────────────────────────────────────


@mcp.tool()
async def read_note(path: str) -> str:
    """Read the contents of a note. Path is relative to vault root (e.g., 'projects/my-note.md')."""
    return vault.read_note(path)


@mcp.tool()
async def write_note(path: str, content: str) -> str:
    """Create or overwrite a note. Creates parent directories if needed."""
    return vault.write_note(path, content)


@mcp.tool()
async def append_note(path: str, content: str) -> str:
    """Append content to the end of an existing note. Creates the note if it doesn't exist."""
    return vault.append_note(path, content)


@mcp.tool()
async def list_notes(folder: str = "") -> str:
    """List all .md files in the vault or a subfolder. Returns one path per line."""
    notes = vault.list_notes(folder)
    return "\n".join(notes) if notes else "No notes found."


@mcp.tool()
async def delete_note(path: str) -> str:
    """Delete a note from the vault."""
    return vault.delete_note(path)


@mcp.tool()
async def move_note(source: str, destination: str) -> str:
    """Move/rename a note and update all wikilinks across the vault that reference it."""
    return vault.move_note(source, destination)


# ── Search ─────────────────────────────────────────────────────────────


@mcp.tool()
async def search(query: str, limit: int = 50) -> str:
    """Full-text search across all notes. Returns matching notes with path, line number, and context."""
    results = vault.search_fulltext(query, limit)
    return json.dumps(results, indent=2) if results else "No matches found."


@mcp.tool()
async def search_by_tags(tags: list[str]) -> str:
    """Find notes with specific tags (from frontmatter or inline #tags)."""
    results = vault.search_by_tags(tags)
    return json.dumps(results, indent=2) if results else "No notes with those tags."


@mcp.tool()
async def search_by_frontmatter(key: str, value: str) -> str:
    """Find notes where a frontmatter property matches a value. Supports partial matching."""
    results = vault.search_by_frontmatter(key, value)
    return json.dumps(results, indent=2) if results else "No matching notes."


@mcp.tool()
async def search_by_date_range(start_date: str, end_date: str, date_field: str = "modified") -> str:
    """Find notes within a date range. date_field can be 'modified' (file mtime) or any frontmatter date field."""
    results = vault.search_by_date_range(start_date, end_date, date_field)
    return json.dumps(results, indent=2) if results else "No notes in that date range."


# ── Frontmatter ────────────────────────────────────────────────────────


@mcp.tool()
async def get_note_frontmatter(path: str) -> str:
    """Get parsed YAML frontmatter from a note. Returns empty dict if no frontmatter."""
    content = vault.read_note(path)
    fm = _get_fm(content)
    return json.dumps(fm, indent=2, default=str)


@mcp.tool()
async def update_note_frontmatter(path: str, updates: str) -> str:
    """Update frontmatter properties on a note. Pass updates as JSON string. Set a key to null to remove it."""
    content = vault.read_note(path)
    updates_dict = json.loads(updates)
    new_content = _update_fm(content, updates_dict)
    vault.write_note(path, new_content)
    return f"Frontmatter updated: {path}"


# ── Links & Graph ──────────────────────────────────────────────────────


@mcp.tool()
async def get_backlinks(path: str) -> str:
    """Find all notes that link TO the given note via wikilinks."""
    results = _backlinks(path, vault.index)
    return json.dumps(results, indent=2) if results else "No backlinks found."


@mcp.tool()
async def get_wikilinks(path: str) -> str:
    """Extract all outgoing wikilink targets from a note."""
    content = vault.read_note(path)
    links = _wikilinks(content)
    return json.dumps(links, indent=2) if links else "No wikilinks found."


@mcp.tool()
async def get_vault_graph() -> str:
    """Get the link graph of the entire vault. Returns nodes (notes) and edges (wikilinks)."""
    graph = _graph(vault.index)
    return json.dumps(graph, indent=2)


@mcp.tool()
async def get_orphan_notes() -> str:
    """Find notes with zero backlinks — disconnected knowledge not linked from anywhere else. Excludes templates and MOC files."""
    orphans = vault.get_orphan_notes()
    if not orphans:
        return "No orphan notes found — all notes are linked!"
    return json.dumps(orphans, indent=2)


# ── Templates ──────────────────────────────────────────────────────────


@mcp.tool()
async def create_note_from_template(
    template_path: str,
    new_note_path: str,
    variables: str = "{}",
) -> str:
    """Create a new note from a template. Supports {{title}}, {{date}}, {{time}}, {{datetime}} plus custom variables.

    variables: JSON string of key-value pairs (e.g., '{"project": "My Project"}')
    """
    vars_dict = json.loads(variables)
    content = _from_template(vault, template_path, new_note_path, vars_dict)
    return f"Created from template: {new_note_path}\n\n{content}"


# ── Resources ──────────────────────────────────────────────────────────


@mcp.resource("obsidian://vault-map")
async def vault_map() -> str:
    """Index of all notes with path, title, tags, links, modified date, and summary."""
    entries = [note.to_dict() for note in vault.index.values()]
    return json.dumps(entries, indent=2, default=str)


@mcp.resource("obsidian://mocs")
async def list_mocs() -> str:
    """List Map of Content (MOC) files — hub notes that organize areas of the vault."""
    mocs = []
    for path, note in vault.index.items():
        is_moc = (
            note.frontmatter.get("type", "").lower() == "moc"
            or "moc" in [t.lower() for t in note.tags]
            or "moc" in path.lower()
            or "map of content" in path.lower()
            or len(note.links) > 10
        )
        if is_moc:
            mocs.append(note.to_dict())
    return json.dumps(mocs, indent=2, default=str)


# ── Entry Point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
