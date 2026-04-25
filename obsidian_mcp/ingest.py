"""Inbox ingestion — process raw notes and find related existing notes.

Workflow:
1. Drop raw content (article, rough notes) in vault `inbox/` folder
2. Call `list_inbox` to see what's pending
3. Call `find_related_notes` for each item to find existing notes it relates to
4. Claude reads the source + related notes, decides updates, applies them
5. Call `archive_inbox_note` to move source to `archive/YYYY-MM/` when done
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from .links import extract_wikilinks

if TYPE_CHECKING:
    from .vault import Vault

INBOX_FOLDER = "inbox"
ARCHIVE_FOLDER = "archive"

# Words to ignore when extracting keywords
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "to", "of", "in",
    "on", "at", "by", "for", "with", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "what", "which",
    "who", "when", "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "very", "also", "if", "then", "else",
    "their", "there", "them", "your", "my", "his", "her", "its", "our", "us",
    "me", "him", "about", "out", "up", "down", "off", "over", "again", "further",
}


def _extract_keywords(content: str, top_n: int = 20) -> list[str]:
    """Extract top keywords from content (lowercase, no stopwords, no short words)."""
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", content.lower())
    words = [w for w in words if w not in STOPWORDS]
    return [w for w, _ in Counter(words).most_common(top_n)]


def list_inbox(vault: "Vault") -> list[dict]:
    """List notes in the inbox/ folder pending ingestion."""
    inbox = vault.root / INBOX_FOLDER
    if not inbox.is_dir():
        return []

    items = []
    for f in sorted(inbox.rglob("*.md")):
        rel = str(f.relative_to(vault.root))
        try:
            content = f.read_text(encoding="utf-8")
            preview = content.strip()[:300]
        except Exception:
            preview = "(unreadable)"
        items.append({
            "path": rel,
            "title": f.stem,
            "modified": f.stat().st_mtime,
            "size": f.stat().st_size,
            "preview": preview,
        })
    return items


def find_related_notes(vault: "Vault", content: str, limit: int = 10) -> list[dict]:
    """Find existing vault notes related to a piece of content.

    When semantic retrieval is enabled on the vault, this delegates to the
    embedding + graph re-rank pipeline (see ``semantic.rank``). Otherwise
    it falls back to a lexical scorer:

    - +5 if existing note's wikilinks include keywords from content
    - +3 per shared tag with content (extract #tags from content)
    - +2 per keyword match in title or path
    - +1 per keyword match in summary

    Returns top N matches with score and matching reasons.
    """
    if vault.semantic_enabled:
        return vault.find_related_semantic(content, limit=limit)

    keywords = _extract_keywords(content)
    keyword_set = set(keywords)

    # Extract content tags and wikilink mentions
    content_tags = set(re.findall(r"(?:^|\s)#([a-zA-Z0-9_/-]+)", content))
    content_wikilinks = set(extract_wikilinks(content))

    scored = []
    for path, note in vault.index.items():
        if path.startswith(f"{INBOX_FOLDER}/"):
            continue
        if path.startswith(f"{ARCHIVE_FOLDER}/"):
            continue

        score = 0
        reasons = []

        # Wikilink mentions in content match this note's title/path
        note_stem = Path(path).stem.lower()
        if note_stem in {wl.lower() for wl in content_wikilinks}:
            score += 5
            reasons.append("mentioned via wikilink")

        # Tag overlap
        note_tags_lower = {t.lower() for t in note.tags}
        shared_tags = note_tags_lower & {t.lower() for t in content_tags}
        if shared_tags:
            score += 3 * len(shared_tags)
            reasons.append(f"shared tags: {', '.join(sorted(shared_tags))}")

        # Title/path keyword match
        title_words = set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", note.title.lower()))
        title_match = title_words & keyword_set
        if title_match:
            score += 2 * len(title_match)
            reasons.append(f"title matches: {', '.join(sorted(title_match))}")

        # Summary keyword match
        summary_words = set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", note.summary.lower()))
        summary_match = summary_words & keyword_set
        if summary_match:
            score += len(summary_match)
            reasons.append(f"summary matches: {', '.join(sorted(list(summary_match)[:5]))}")

        if score > 0:
            scored.append({
                "path": path,
                "title": note.title,
                "score": score,
                "reasons": reasons,
                "tags": note.tags,
            })

    return sorted(scored, key=lambda x: -x["score"])[:limit]


def archive_inbox_note(vault: "Vault", path: str) -> str:
    """Move a note from inbox/ to archive/YYYY-MM/."""
    if not path.startswith(f"{INBOX_FOLDER}/"):
        raise ValueError(f"Not an inbox note: {path}")

    src = vault._resolve_path(path)
    if not src.exists():
        raise FileNotFoundError(f"Inbox note not found: {path}")

    today = date.today()
    archive_subdir = f"{ARCHIVE_FOLDER}/{today.strftime('%Y-%m')}"
    dest_rel = f"{archive_subdir}/{Path(path).name}"
    dest = vault._resolve_path(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)

    src.rename(dest)

    # Update index
    vault.index.pop(path, None)
    vault.index[dest_rel] = vault._index_single(dest_rel)

    return f"Archived: {path} -> {dest_rel}"
