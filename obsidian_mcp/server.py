"""Obsidian MCP Server — FastMCP entry point with all tool and resource registrations."""

import json
import logging
import os
import sys

from fastmcp import FastMCP

from .frontmatter import get_frontmatter as _get_fm
from .frontmatter import update_frontmatter as _update_fm
from .ingest import (
    archive_inbox_note as _archive_inbox,
)
from .ingest import (
    find_related_notes as _find_related,
)
from .ingest import (
    list_inbox as _list_inbox,
)
from .links import extract_wikilinks as _wikilinks
from .links import get_backlinks as _backlinks
from .links import get_graph as _graph
from .lint import (
    find_broken_wikilinks as _broken_wikilinks,
)
from .lint import (
    find_duplicate_titles as _duplicate_titles,
)
from .lint import (
    find_stale_notes as _stale_notes,
)
from .lint import (
    lint_vault as _lint_vault,
)
from .schema import (
    get_schema as _get_schema,
)
from .schema import (
    validate_note_schema as _validate_note,
)
from .schema import (
    validate_vault_schema as _validate_vault,
)
from .templates import create_from_template as _from_template
from .vault import Vault

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
vault.start_watching()
try:
    if vault.enable_semantic():
        logger.info("semantic retrieval enabled")
    else:
        # Specific reason already logged inside enable_semantic — either
        # OBSIDIAN_EMBEDDER=none, or the backend health check failed.
        logger.info("semantic retrieval disabled")
except Exception:
    logger.exception("failed to enable semantic retrieval; continuing without it")
mcp = FastMCP("obsidian")


# ── Core File Operations ──────────────────────────────────────────────


@mcp.tool()
async def read_note(path: str) -> str:
    """Read the contents of a note. Path is relative to vault root (e.g., 'projects/my-note.md')."""
    return vault.read_note(path)


@mcp.tool()
async def write_note(path: str, content: str, force: bool = False) -> str:
    """Create or overwrite a note. Creates parent directories if needed.

    Refuses to overwrite if the note changed on disk since the last read_note
    call (typically because the user edited it in Obsidian). Pass force=True
    to overwrite anyway.
    """
    return vault.write_note(path, content, force=force)


@mcp.tool()
async def append_note(path: str, content: str) -> str:
    """Append content to the end of an existing note. Creates the note if it doesn't exist."""
    return vault.append_note(path, content)


@mcp.tool()
async def list_notes(folder: str = "", include_frontmatter: bool = False) -> str:
    """List all .md files in the vault or a subfolder.

    Default returns one path per line. Pass `include_frontmatter=True`
    to get JSON `[{path, title, tags, frontmatter}]` — useful for
    triage scans by date / status / tag without an N+1 read loop.
    """
    notes = vault.list_notes(folder, include_frontmatter=include_frontmatter)
    if not notes:
        return "No notes found."
    if include_frontmatter:
        return json.dumps(notes, indent=2, default=str)
    return "\n".join(notes)


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
async def search(query: str, limit: int = 50, path: str = "") -> str:
    """Full-text search across all notes. Returns matching notes with path, line number, and context.

    Pass `path` (e.g. "projects/") to scope the search to a subtree of the vault.
    """
    results = vault.search_fulltext(query, limit, path=path)
    return json.dumps(results, indent=2) if results else "No matches found."


@mcp.tool()
async def search_by_tags(tags: list[str], path: str = "") -> str:
    """Find notes with specific tags (from frontmatter or inline #tags).

    Pass `path` (e.g. "projects/") to scope to a subtree of the vault.
    """
    results = vault.search_by_tags(tags, path=path)
    return json.dumps(results, indent=2) if results else "No notes with those tags."


@mcp.tool()
async def search_by_frontmatter(key: str, value: str, path: str = "") -> str:
    """Find notes where a frontmatter property matches a value. Supports partial matching.

    Pass `path` (e.g. "projects/") to scope to a subtree of the vault.
    """
    results = vault.search_by_frontmatter(key, value, path=path)
    return json.dumps(results, indent=2) if results else "No matching notes."


@mcp.tool()
async def search_by_date_range(start_date: str, end_date: str, date_field: str = "modified", path: str = "") -> str:
    """Find notes within a date range. date_field can be 'modified' (file mtime) or any frontmatter date field.

    Pass `path` (e.g. "projects/") to scope to a subtree of the vault.
    """
    results = vault.search_by_date_range(start_date, end_date, date_field, path=path)
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


# ── Lint / Vault Health ────────────────────────────────────────────────


@mcp.tool()
async def find_broken_wikilinks() -> str:
    """Find all wikilinks that don't resolve to any note in the vault. Critical lint check."""
    broken = _broken_wikilinks(vault)
    if not broken:
        return "No broken wikilinks found."
    return json.dumps(broken, indent=2)


@mcp.tool()
async def find_stale_notes(months: int = 6) -> str:
    """Find notes not modified in N months but still linked from recent notes (last 30 days).

    These are old content that people still reference — candidates for review or update.
    """
    stale = _stale_notes(vault, months=months)
    if not stale:
        return f"No stale notes found (older than {months} months but still referenced)."
    return json.dumps(stale, indent=2, default=str)


@mcp.tool()
async def find_duplicate_titles() -> str:
    """Find notes that share the same filename stem in different folders. Causes wikilink ambiguity."""
    dupes = _duplicate_titles(vault)
    if not dupes:
        return "No duplicate titles found."
    return json.dumps(dupes, indent=2)


@mcp.tool()
async def lint_vault(stale_months: int = 6) -> str:
    """Run all lint checks: broken wikilinks, stale notes, duplicate titles, orphan notes.

    Returns aggregated report of vault health issues.
    """
    report = _lint_vault(vault, stale_months=stale_months)
    return json.dumps(report, indent=2, default=str)


# ── Schema Validation ─────────────────────────────────────────────────


@mcp.tool()
async def get_schema() -> str:
    """Read the vault's schema.yml — defines note types, required fields, and folder mappings.

    Returns empty dict if no schema is defined.
    """
    schema = _get_schema(vault)
    if not schema:
        return "No schema.yml found at vault root. Create one to enable validation."
    return json.dumps(schema, indent=2, default=str)


@mcp.tool()
async def validate_note_schema(path: str) -> str:
    """Validate a single note against the vault schema. Returns list of errors or 'valid'."""
    errors = _validate_note(vault, path)
    if not errors:
        return f"{path}: valid"
    return json.dumps({"path": path, "errors": errors}, indent=2)


@mcp.tool()
async def validate_vault_schema() -> str:
    """Validate every note in the vault against the schema. Returns dict of {path: [errors]}."""
    issues = _validate_vault(vault)
    if not issues:
        return "All notes are valid against the schema."
    return json.dumps(issues, indent=2, default=str)


# ── Inbox / Ingest Workflow ───────────────────────────────────────────


@mcp.tool()
async def list_inbox() -> str:
    """List notes in the inbox/ folder pending ingestion into the wiki."""
    items = _list_inbox(vault)
    if not items:
        return "Inbox is empty."
    return json.dumps(items, indent=2, default=str)


@mcp.tool()
async def find_related_notes(content: str, limit: int = 10) -> str:
    """Given a piece of content (raw note, article, etc.), find existing vault notes that relate to it.

    When semantic retrieval is enabled (the default), delegates to the
    embedding + graph re-rank pipeline and returns the same per-result
    breakdown as semantic_search (cos_sim, signals, contributions).
    Otherwise falls back to a lexical scorer (keyword overlap, tag
    matching, wikilink mentions) and returns score + reasons.
    """
    matches = _find_related(vault, content, limit=limit)
    if not matches:
        return "No related notes found."
    return json.dumps(matches, indent=2, default=str)


@mcp.tool()
async def archive_inbox_note(path: str) -> str:
    """Move a processed note from inbox/ to archive/YYYY-MM/. Use after ingesting its content into the wiki."""
    return _archive_inbox(vault, path)


# ── Semantic Retrieval ────────────────────────────────────────────────


@mcp.tool()
async def semantic_search(query: str, k: int = 10, path: str = "") -> str:
    """Embedding-based search with graph-aware re-rank.

    Returns ranked notes with score breakdown (cos_sim, wikilink match,
    tag overlap, neighbor distance, recency). Use this when the user's
    intent is semantic ("what notes are about X?") rather than an exact
    string lookup — for exact matches, use `search`.

    Pass `path` (e.g. "projects/") to scope to a subtree of the vault.
    """
    if not vault.semantic_enabled:
        return "Semantic retrieval disabled (set OBSIDIAN_EMBEDDER to enable)."
    results = vault.semantic_search(query, k=k, path=path)
    if not results:
        return "No results."
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def rebuild_embeddings() -> str:
    """Re-embed every note in the vault. Safe to run anytime; idempotent."""
    result = vault.rebuild_embeddings()
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def embedding_stats(wait: bool = False) -> str:
    """Inspect the embedding index (note count, chunk count, model, db path).

    Edits are embedded asynchronously with a 200ms debounce, so the raw
    counts can briefly trail recent writes. The response includes
    ``queue_pending`` (paths still in flight) and ``queue_idle`` (true
    when fully caught up). Pass ``wait=true`` to block until the queue
    drains so the returned counts reflect the latest edits.
    """
    return json.dumps(vault.embedding_stats(wait=wait), indent=2, default=str)


@mcp.tool()
async def suggest_links(path: str = "", limit: int = 25, min_score: float = 0.55) -> str:
    """Find note pairs that look related but aren't wikilinked yet.

    For each note (or just ``path`` if specified), pulls semantic
    neighbors from the chunk index, drops pairs that already share a
    wikilink or were dismissed, scores by cosine + tag overlap, and
    returns the top ``limit`` above ``min_score``. Use this to grow the
    vault graph based on what's already in your notes.
    """
    if not vault.semantic_enabled:
        return "Auto-link suggestions need semantic enabled (set OBSIDIAN_EMBEDDER)."
    results = vault.suggest_links(
        path=path or None, limit=limit, min_score=min_score,
    )
    if not results:
        return "No suggestions above threshold."
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def apply_link_suggestion(source: str, target: str) -> str:
    """Append a wikilink from ``source`` to ``target`` (idempotent).

    Adds a ``See also: [[target]]`` line at the end of the source note.
    Re-applying is a no-op once the link is present.
    """
    return vault.apply_link_suggestion(source, target)


@mcp.tool()
async def dismiss_link_suggestion(source: str, target: str) -> str:
    """Hide this pair from future ``suggest_links`` results.

    Stored persistently in the vector store DB; pair is order-independent.
    """
    vault.dismiss_link_suggestion(source, target)
    return f"dismissed: {source} <-> {target}"


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
