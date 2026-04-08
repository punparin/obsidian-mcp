"""Template expansion for creating notes from templates."""

from datetime import datetime
from pathlib import Path

from .vault import Vault


def create_from_template(
    vault: Vault,
    template_path: str,
    new_note_path: str,
    variables: dict[str, str] | None = None,
) -> str:
    """Create a new note from a template file.

    template_path: relative path to template in vault (e.g., "templates/Daily Note.md")
    new_note_path: relative path for the new note
    variables: dict of {{key}} -> value replacements

    Built-in variables (always available, overridable):
    - {{title}}: filename of new note (without .md)
    - {{date}}: today's date (YYYY-MM-DD)
    - {{time}}: current time (HH:MM)
    - {{datetime}}: full ISO datetime

    Returns the content of the created note.
    """
    template_content = vault.read_note(template_path)

    now = datetime.now()
    builtins = {
        "title": Path(new_note_path).stem,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "datetime": now.isoformat(),
    }

    # User variables override builtins
    all_vars = {**builtins, **(variables or {})}

    content = template_content
    for key, value in all_vars.items():
        content = content.replace(f"{{{{{key}}}}}", value)

    vault.write_note(new_note_path, content)
    return content
