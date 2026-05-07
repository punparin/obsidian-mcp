"""Smoke checks on the system-prompt payload the server injects via MCP.

Two failure modes worth catching: (1) someone empties the constant by
accident, killing the auto-load story; (2) a tool gets renamed but the
instructions still reference the old name. The phrase list below is
deliberately small — covers the most-load-bearing tool names so the
test bites on real drift but doesn't break on prose tweaks.
"""

from obsidian_mcp.agent_instructions import INSTRUCTIONS


def test_instructions_non_empty():
    assert isinstance(INSTRUCTIONS, str)
    assert len(INSTRUCTIONS) > 500


def test_instructions_reference_load_bearing_tools():
    for phrase in (
        "semantic_search",
        "search_by_frontmatter",
        "find_related_notes",
        "write_note",
        "NoteConflictError",
        "suggest_links",
        "archive_inbox_note",
    ):
        assert phrase in INSTRUCTIONS, phrase
