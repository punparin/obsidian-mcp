from obsidian_mcp.schema import get_schema, validate_note_schema, validate_vault_schema


class TestGetSchema:
    def test_no_schema(self, vault):
        assert get_schema(vault) == {}

    def test_with_schema(self, vault, tmp_vault):
        (tmp_vault / "schema.yml").write_text("""
note_types:
  project:
    required: [title, status]
    optional: [tags]
""")
        schema = get_schema(vault)
        assert "note_types" in schema
        assert "project" in schema["note_types"]


class TestValidateNote:
    def test_no_schema_no_errors(self, vault):
        assert validate_note_schema(vault, "note1.md") == []

    def test_missing_required_field(self, vault, tmp_vault):
        (tmp_vault / "schema.yml").write_text("""
note_types:
  project:
    required: [title, status, area]
""")
        (tmp_vault / "myproject.md").write_text("---\ntype: project\ntitle: Test\n---\nBody")
        vault.rebuild_index()
        errors = validate_note_schema(vault, "myproject.md")
        assert any("status" in e for e in errors)
        assert any("area" in e for e in errors)

    def test_invalid_status(self, vault, tmp_vault):
        (tmp_vault / "schema.yml").write_text("""
note_types:
  project:
    required: [title, status]
    status_values: [active, done]
""")
        (tmp_vault / "myproject.md").write_text(
            "---\ntype: project\ntitle: Test\nstatus: bogus\n---\nBody"
        )
        vault.rebuild_index()
        errors = validate_note_schema(vault, "myproject.md")
        assert any("Invalid status" in e for e in errors)

    def test_folder_auto_type(self, vault, tmp_vault):
        (tmp_vault / "schema.yml").write_text("""
note_types:
  project:
    required: [title, status]
folders:
  projects: project
""")
        (tmp_vault / "projects").mkdir(exist_ok=True)
        (tmp_vault / "projects" / "thing.md").write_text("---\ntitle: Thing\n---\nNo status")
        vault.rebuild_index()
        errors = validate_note_schema(vault, "projects/thing.md")
        assert any("status" in e for e in errors)


class TestValidateVault:
    def test_no_schema_returns_warning(self, vault):
        result = validate_vault_schema(vault)
        assert "_warning" in result

    def test_returns_issues(self, vault, tmp_vault):
        (tmp_vault / "schema.yml").write_text("""
note_types:
  project:
    required: [title, status, area]
""")
        (tmp_vault / "bad.md").write_text("---\ntype: project\ntitle: Bad\n---\nBody")
        vault.rebuild_index()
        result = validate_vault_schema(vault)
        assert "bad.md" in result
