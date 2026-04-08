from obsidian_mcp.templates import create_from_template


class TestCreateFromTemplate:
    def test_basic_expansion(self, vault, tmp_vault):
        content = create_from_template(vault, "templates/daily.md", "daily/2026-04-08.md")
        assert "2026-04-08" in content  # {{title}} expanded
        assert (tmp_vault / "daily" / "2026-04-08.md").exists()

    def test_builtin_variables(self, vault):
        content = create_from_template(vault, "templates/daily.md", "test-note.md")
        assert "test-note" in content  # {{title}}

    def test_custom_variables(self, vault, tmp_vault):
        (tmp_vault / "templates" / "project.md").write_text("# {{project_name}}\n\nOwner: {{owner}}")
        content = create_from_template(
            vault, "templates/project.md", "projects/new.md",
            variables={"project_name": "LifeOS", "owner": "PK"},
        )
        assert "LifeOS" in content
        assert "PK" in content

    def test_missing_template(self, vault):
        import pytest
        with pytest.raises(FileNotFoundError):
            create_from_template(vault, "templates/nonexistent.md", "out.md")
