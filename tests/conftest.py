import pytest

from obsidian_mcp.vault import Vault


@pytest.fixture
def tmp_vault(tmp_path):
    """Create a temporary vault with sample notes."""
    (tmp_path / "note1.md").write_text(
        "---\ntitle: Note One\ntags: [project, active]\ndate: 2026-01-10\n---\n\nFirst paragraph of note one.\n\nSome more content.\n\n[[note2]] and [[subfolder/note3]]\n"
    )
    (tmp_path / "note2.md").write_text(
        "---\ntitle: Note Two\ntags: [reference]\ndate: 2026-01-15\n---\n\nSecond note content.\n\n[[note1]] and [[note3]]\n"
    )
    (tmp_path / "subfolder").mkdir()
    (tmp_path / "subfolder" / "note3.md").write_text(
        "# Note Three\n\nNo frontmatter here.\n\n#inline-tag\n\n[[note1]]\n"
    )
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "daily.md").write_text(
        "---\ntitle: {{title}}\ndate: {{date}}\n---\n\n## {{title}}\n\nCreated on {{date}} at {{time}}.\n"
    )
    (tmp_path / "MOC - Projects.md").write_text(
        "---\ntype: moc\ntags: [moc]\n---\n\n# Projects\n\n[[note1]]\n[[note2]]\n"
    )
    return tmp_path


@pytest.fixture
def vault(tmp_vault):
    return Vault(tmp_vault)
