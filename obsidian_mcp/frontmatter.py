"""YAML frontmatter parsing and updating for Obsidian notes."""

import frontmatter


def has_frontmatter(content: str) -> bool:
    """Check if content starts with a YAML frontmatter block."""
    stripped = content.lstrip()
    return stripped.startswith("---\n") or stripped.startswith("---\r\n")


def get_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from note content.

    Returns empty dict if no frontmatter found.
    Normalizes tags to always be a list.
    """
    if not has_frontmatter(content):
        return {}

    post = frontmatter.loads(content)
    metadata = dict(post.metadata)

    # Normalize tags to list
    if "tags" in metadata:
        tags = metadata["tags"]
        if isinstance(tags, str):
            metadata["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
        elif not isinstance(tags, list):
            metadata["tags"] = [str(tags)]

    return metadata


def update_frontmatter(content: str, updates: dict) -> str:
    """Merge updates into existing frontmatter, return full note string.

    - If note has no frontmatter, adds a new YAML block.
    - Existing keys not in updates are preserved.
    - Setting a key to None removes it.
    - Body content is preserved exactly.
    """
    post = frontmatter.loads(content)

    for key, value in updates.items():
        if value is None:
            post.metadata.pop(key, None)
        else:
            post.metadata[key] = value

    return frontmatter.dumps(post)


def get_body(content: str) -> str:
    """Extract the body content (everything after frontmatter)."""
    post = frontmatter.loads(content)
    return post.content
