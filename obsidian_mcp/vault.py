"""Vault class — file operations, indexing, caching, and search."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path

from .frontmatter import get_frontmatter, get_body, has_frontmatter
from .links import extract_wikilinks, update_wikilinks_across_vault


@dataclass
class NoteIndex:
    """Cached metadata for a single note."""

    path: str
    title: str
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    modified: str = ""
    summary: str = ""
    frontmatter: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


INLINE_TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z0-9_/-]+)")


class Vault:
    """Central abstraction for an Obsidian vault."""

    def __init__(self, vault_path: str | Path):
        self.root = Path(vault_path).resolve()
        if not self.root.is_dir():
            raise ValueError(f"Vault path does not exist: {self.root}")
        self._index: dict[str, NoteIndex] | None = None

    # -- Path security --

    def _resolve_path(self, relative: str) -> Path:
        """Resolve relative path and ensure it stays within the vault."""
        resolved = (self.root / relative).resolve()
        if not str(resolved).startswith(str(self.root)):
            raise ValueError(f"Path escapes vault: {relative}")
        return resolved

    def _to_relative(self, absolute: Path) -> str:
        return str(absolute.relative_to(self.root))

    # -- Index --

    def _index_single(self, rel_path: str) -> NoteIndex:
        """Build index entry for a single note."""
        file_path = self.root / rel_path
        content = file_path.read_text(encoding="utf-8")
        fm = get_frontmatter(content)
        body = get_body(content) if has_frontmatter(content) else content

        # Tags: from frontmatter + inline
        tags = list(fm.get("tags", []))
        inline_tags = INLINE_TAG_RE.findall(body)
        for tag in inline_tags:
            if tag not in tags:
                tags.append(tag)

        # Summary: first non-empty paragraph
        summary = ""
        for line in body.strip().split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                summary = stripped[:200]
                break

        mtime = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()

        return NoteIndex(
            path=rel_path,
            title=fm.get("title", Path(rel_path).stem),
            tags=tags,
            links=extract_wikilinks(content),
            modified=mtime,
            summary=summary,
            frontmatter=fm,
        )

    def _build_index(self) -> dict[str, NoteIndex]:
        """Scan entire vault and build index."""
        index = {}
        for md_file in self.root.rglob("*.md"):
            rel = self._to_relative(md_file)
            try:
                index[rel] = self._index_single(rel)
            except Exception:
                continue  # skip unreadable files
        return index

    def rebuild_index(self) -> dict[str, NoteIndex]:
        """Force rebuild the index."""
        self._index = self._build_index()
        return self._index

    @property
    def index(self) -> dict[str, NoteIndex]:
        """Lazy-loaded vault index."""
        if self._index is None:
            self._index = self._build_index()
        return self._index

    # -- File operations --

    def read_note(self, path: str) -> str:
        """Read note content."""
        file_path = self._resolve_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        return file_path.read_text(encoding="utf-8")

    def write_note(self, path: str, content: str) -> str:
        """Create or overwrite a note."""
        file_path = self._resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        # Update index
        rel = self._to_relative(file_path)
        self.index[rel] = self._index_single(rel)
        return f"Written: {path}"

    def append_note(self, path: str, content: str) -> str:
        """Append content to existing note, or create if missing."""
        file_path = self._resolve_path(path)
        if file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            file_path.write_text(existing + "\n" + content, encoding="utf-8")
        else:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        rel = self._to_relative(file_path)
        self.index[rel] = self._index_single(rel)
        return f"Appended: {path}"

    def list_notes(self, folder: str = "") -> list[str]:
        """List all .md files in the vault or a subfolder."""
        search_path = self._resolve_path(folder) if folder else self.root
        if not search_path.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder}")
        return sorted(self._to_relative(f) for f in search_path.rglob("*.md"))

    def delete_note(self, path: str) -> str:
        """Delete a note."""
        file_path = self._resolve_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        file_path.unlink()
        rel = self._to_relative(file_path)
        self.index.pop(rel, None)
        return f"Deleted: {path}"

    def move_note(self, src: str, dest: str) -> str:
        """Move/rename a note and update all wikilinks across the vault."""
        src_path = self._resolve_path(src)
        dest_path = self._resolve_path(dest)

        if not src_path.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        if dest_path.exists():
            raise FileExistsError(f"Destination already exists: {dest}")

        old_stem = src_path.stem
        new_stem = dest_path.stem

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        src_path.rename(dest_path)

        # Update index
        old_rel = self._to_relative(src_path)
        self.index.pop(old_rel, None)
        new_rel = self._to_relative(dest_path)
        self.index[new_rel] = self._index_single(new_rel)

        # Update wikilinks across vault
        updated = update_wikilinks_across_vault(self.root, old_stem, new_stem, self.index)

        # Re-index updated files
        for p in updated:
            self.index[p] = self._index_single(p)

        return f"Moved: {src} -> {dest} (updated {len(updated)} linking notes)"

    # -- Search --

    def search_fulltext(self, query: str, limit: int = 50) -> list[dict]:
        """Full-text search across all notes."""
        results = []
        query_lower = query.lower()
        for md_file in self.root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if query_lower in line.lower():
                    results.append({
                        "path": self._to_relative(md_file),
                        "line": i,
                        "context": line.strip()[:200],
                    })
                    break  # one match per file
            if len(results) >= limit:
                break
        return results

    def search_by_tags(self, tags: list[str]) -> list[dict]:
        """Find notes with specific tags."""
        tags_lower = [t.lstrip("#").lower() for t in tags]
        results = []
        for path, note in self.index.items():
            note_tags = [t.lower() for t in note.tags]
            if any(t in note_tags for t in tags_lower):
                results.append({"path": path, "title": note.title, "tags": note.tags})
        return results

    def search_by_frontmatter(self, key: str, value: str) -> list[dict]:
        """Find notes where a frontmatter property matches a value."""
        value_lower = value.lower()
        results = []
        for path, note in self.index.items():
            fm_value = note.frontmatter.get(key)
            if fm_value is None:
                continue
            if isinstance(fm_value, list):
                if any(value_lower in str(v).lower() for v in fm_value):
                    results.append({"path": path, "title": note.title, key: fm_value})
            elif value_lower in str(fm_value).lower():
                results.append({"path": path, "title": note.title, key: fm_value})
        return results

    def search_by_date_range(
        self, start: str, end: str, date_field: str = "modified"
    ) -> list[dict]:
        """Find notes within a date range.

        date_field: 'modified' uses file mtime, anything else uses frontmatter.
        """
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
        results = []

        for path, note in self.index.items():
            if date_field == "modified":
                note_date = date.fromisoformat(note.modified[:10])
            else:
                fm_date = note.frontmatter.get(date_field)
                if not fm_date:
                    continue
                try:
                    note_date = date.fromisoformat(str(fm_date)[:10])
                except ValueError:
                    continue

            if start_date <= note_date <= end_date:
                results.append({"path": path, "title": note.title, date_field: str(note_date)})

        return results

    def get_orphan_notes(self) -> list[dict]:
        """Find notes with zero backlinks — disconnected from the vault graph.

        A note is an orphan if no other note links to it via wikilinks.
        Templates and MOC files are excluded from results.
        """
        from .links import get_backlinks

        orphans = []
        for path, note in self.index.items():
            # Skip templates and MOC files
            if "templates/" in path.lower():
                continue
            if note.frontmatter.get("type", "").lower() == "moc":
                continue

            backlinks = get_backlinks(path, self.index)
            if not backlinks:
                orphans.append({
                    "path": path,
                    "title": note.title,
                    "tags": note.tags,
                    "outgoing_links": len(note.links),
                    "modified": note.modified,
                })

        return sorted(orphans, key=lambda x: x["modified"])
