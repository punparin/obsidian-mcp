"""Schema validation — define note types and required frontmatter fields.

Vault schema lives at vault root as `schema.yml`:

```yaml
note_types:
  project:
    required: [title, status, area]
    optional: [tags, due_date]
    status_values: [active, paused, done, archived]
  decision:
    required: [title, date, status]
    optional: [project, participants, tags]
    status_values: [proposed, decided, superseded]
  meeting-note:
    required: [title, date]
    optional: [participants, project, tags]

folders:
  projects: project
  decisions: decision
  meetings: meeting-note
```
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .vault import Vault

SCHEMA_FILE = "schema.yml"


def get_schema(vault: "Vault") -> dict:
    """Read schema.yml from vault root. Returns empty dict if missing."""
    schema_path = vault.root / SCHEMA_FILE
    if not schema_path.exists():
        return {}
    return yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}


def validate_note_schema(vault: "Vault", path: str) -> list[str]:
    """Validate a single note against the schema. Returns list of error messages."""
    schema = get_schema(vault)
    if not schema:
        return []  # no schema = no validation

    note = vault.index.get(path)
    if note is None:
        return [f"Note not in index: {path}"]

    fm = note.frontmatter
    note_type = fm.get("type")

    # Auto-detect type from folder if not in frontmatter
    if not note_type:
        folders = schema.get("folders", {})
        for folder, folder_type in folders.items():
            if path.startswith(f"{folder}/"):
                note_type = folder_type
                break

    if not note_type:
        return []  # not a typed note, skip

    note_types = schema.get("note_types", {})
    if note_type not in note_types:
        return [f"Unknown note type: {note_type}"]

    type_schema = note_types[note_type]
    errors = []

    # Check required fields
    for field in type_schema.get("required", []):
        if field not in fm:
            errors.append(f"Missing required field: {field}")
        elif not fm[field]:
            errors.append(f"Required field is empty: {field}")

    # Check status values if defined
    if "status" in fm and "status_values" in type_schema:
        if fm["status"] not in type_schema["status_values"]:
            errors.append(
                f"Invalid status '{fm['status']}'. Must be one of {type_schema['status_values']}"
            )

    return errors


def validate_vault_schema(vault: "Vault") -> dict:
    """Validate entire vault against schema. Returns dict of {path: [errors]}."""
    schema = get_schema(vault)
    if not schema:
        return {"_warning": ["No schema.yml found at vault root — no validation performed"]}

    issues = {}
    for path in vault.index:
        errors = validate_note_schema(vault, path)
        if errors:
            issues[path] = errors
    return issues
