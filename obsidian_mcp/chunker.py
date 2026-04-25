"""Markdown-aware chunker — split a note body into semantic chunks.

Obsidian notes already have structure (## / ### headings, paragraphs), so
use those boundaries rather than blind token windows. Each chunk carries:

- ``heading``: breadcrumb of ancestor headings ("Context > Constraints")
- ``char_start`` / ``char_end``: offsets into the original body for snippets
- ``text``: the chunk body itself

The split strategy:
1. Walk the body, splitting on any H1/H2/H3 heading — each section is a
   candidate chunk.
2. If a section exceeds ``max_chars``, split it further on paragraph
   boundaries (blank lines), greedily packing paragraphs while respecting
   the limit. A small ``overlap_chars`` tail is prefixed to the next chunk
   so cross-paragraph context isn't lost.
3. If a section is shorter than ``min_chars``, merge it into the next
   chunk — micro-fragments rank badly and clutter results.

Frontmatter and the empty prefix before the first heading are handled by
the caller (see ``vault._index_single`` — it passes the body only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
DEFAULT_MAX_CHARS = 1600
DEFAULT_MIN_CHARS = 200
DEFAULT_OVERLAP = 120


@dataclass(frozen=True)
class Chunk:
    heading: str       # breadcrumb, may be "" for untitled lead-in
    char_start: int
    char_end: int
    text: str


def _split_sections(body: str) -> list[tuple[str, int, int]]:
    """Return [(heading_breadcrumb, start_offset, end_offset)] from H1/H2/H3."""
    sections: list[tuple[str, int, int]] = []
    # Stack of (level, title) so deeper headings inherit their parents' breadcrumb.
    stack: list[tuple[int, str]] = []
    matches = list(HEADING_RE.finditer(body))

    if not matches:
        return [("", 0, len(body))]

    # Leading text before first heading (if any) is its own chunk.
    first = matches[0]
    if first.start() > 0 and body[: first.start()].strip():
        sections.append(("", 0, first.start()))

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        # Pop any deeper-or-equal headings so we build a clean breadcrumb.
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        breadcrumb = " > ".join(t for _, t in stack)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((breadcrumb, start, end))

    return sections


def _pack_paragraphs(
    breadcrumb: str,
    body: str,
    abs_start: int,
    abs_end: int,
    max_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Split an oversized section on blank-line paragraph boundaries."""
    text = body[abs_start:abs_end]
    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[Chunk] = []

    buf: list[str] = []
    buf_start_rel = 0
    buf_len = 0
    cursor_rel = 0

    for para in paragraphs:
        para_len = len(para)
        # If adding this paragraph would bust the limit AND we already have
        # content buffered, flush the buffer.
        if buf and buf_len + 2 + para_len > max_chars:
            chunk_text = "\n\n".join(buf).strip()
            chunks.append(
                Chunk(
                    heading=breadcrumb,
                    char_start=abs_start + buf_start_rel,
                    char_end=abs_start + cursor_rel,
                    text=chunk_text,
                )
            )
            # Overlap tail: last overlap_chars of the flushed chunk seeds the next.
            if overlap_chars > 0 and len(chunk_text) > overlap_chars:
                overlap_tail = chunk_text[-overlap_chars:]
                buf = [overlap_tail, para]
                buf_start_rel = cursor_rel - len(overlap_tail)
                buf_len = len(overlap_tail) + 2 + para_len
            else:
                buf = [para]
                buf_start_rel = cursor_rel
                buf_len = para_len
        else:
            if not buf:
                buf_start_rel = cursor_rel
                buf_len = para_len
            else:
                buf_len += 2 + para_len
            buf.append(para)
        cursor_rel += para_len + 2  # +2 for the "\n\n" separator we split on

    if buf:
        chunk_text = "\n\n".join(buf).strip()
        chunks.append(
            Chunk(
                heading=breadcrumb,
                char_start=abs_start + buf_start_rel,
                char_end=abs_end,
                text=chunk_text,
            )
        )

    return chunks


def chunk_body(
    body: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split note body into retrieval-friendly chunks. See module docstring."""
    if not body or not body.strip():
        return []

    sections = _split_sections(body)

    # Pass 1: oversized sections fan out into paragraph-packed sub-chunks.
    expanded: list[Chunk] = []
    for breadcrumb, start, end in sections:
        length = end - start
        text = body[start:end].strip()
        if not text:
            continue
        if length <= max_chars:
            expanded.append(
                Chunk(heading=breadcrumb, char_start=start, char_end=end, text=text)
            )
        else:
            expanded.extend(
                _pack_paragraphs(breadcrumb, body, start, end, max_chars, overlap_chars)
            )

    # Pass 2: merge micro-chunks (< min_chars) into the next chunk so we
    # don't store one-line fragments as standalone embeddings.
    merged: list[Chunk] = []
    pending: Chunk | None = None
    for ch in expanded:
        if pending is not None:
            # Try to coalesce pending with current.
            combined_text = (pending.text + "\n\n" + ch.text).strip()
            merged_heading = pending.heading or ch.heading
            merged.append(
                Chunk(
                    heading=merged_heading,
                    char_start=pending.char_start,
                    char_end=ch.char_end,
                    text=combined_text,
                )
            )
            pending = None
            continue
        if len(ch.text) < min_chars:
            pending = ch
        else:
            merged.append(ch)
    if pending is not None:
        # Trailing micro-chunk with nothing to merge into — if the previous
        # chunk can absorb it without busting max_chars, do that; else keep.
        if merged and len(merged[-1].text) + 2 + len(pending.text) <= max_chars:
            last = merged[-1]
            merged[-1] = Chunk(
                heading=last.heading,
                char_start=last.char_start,
                char_end=pending.char_end,
                text=(last.text + "\n\n" + pending.text).strip(),
            )
        else:
            merged.append(pending)

    return merged
