"""Access rules: the agent can only touch non-hidden, non-ignored .md notes inside the vault."""

import os

import pytest

from obsidian_mcp.templates import create_from_template
from obsidian_mcp.vault import AccessDenied, Vault


@pytest.fixture
def sandbox(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    (vault_dir / "note.md").write_text("hello")
    # Sibling folder whose name starts with the vault's name — the old
    # string-prefix check let `../vault-secret/...` through.
    secret = tmp_path / "vault-secret"
    secret.mkdir()
    (secret / "keys.md").write_text("SECRET")
    return vault_dir, secret


@pytest.mark.parametrize(
    "path",
    [
        "../vault-secret/keys.md",
        "../../etc/passwd",
        "/etc/passwd",
        "sub/../../vault-secret/keys.md",
        "note.md\x00.txt",
    ],
)
def test_escapes_are_denied(sandbox, path):
    v = Vault(sandbox[0])
    with pytest.raises(AccessDenied):
        v.read_note(path)


def test_delete_outside_vault_is_denied(sandbox):
    vault_dir, secret = sandbox
    v = Vault(vault_dir)
    with pytest.raises(AccessDenied):
        v.delete_note("../vault-secret/keys.md")
    assert (secret / "keys.md").exists()


@pytest.mark.parametrize(
    "path",
    [
        ".obsidian/plugins/evil/main.md",
        ".obsidian-mcp/config.md",
        ".git/hooks/pre-commit.md",
        "folder/.hidden.md",
    ],
)
def test_hidden_paths_are_denied(sandbox, path):
    v = Vault(sandbox[0])
    with pytest.raises(AccessDenied, match="Hidden"):
        v.write_note(path, "x")


@pytest.mark.parametrize("path", [".obsidian/plugins/evil/main.js", "schema.yml", "script.sh", "note"])
def test_non_markdown_is_denied(sandbox, path):
    v = Vault(sandbox[0])
    with pytest.raises(AccessDenied):
        v.write_note(path, "x")
    assert not (sandbox[0] / path).exists()


def test_symlink_out_of_vault_is_denied_and_not_indexed(sandbox):
    vault_dir, secret = sandbox
    os.symlink(secret / "keys.md", vault_dir / "link.md")
    v = Vault(vault_dir)
    with pytest.raises(AccessDenied):
        v.read_note("link.md")
    assert "link.md" not in v.index
    assert v.search_fulltext("SECRET") == []


def test_folder_scopes_are_checked(sandbox):
    v = Vault(sandbox[0])
    with pytest.raises(AccessDenied):
        v.list_notes("../vault-secret")
    with pytest.raises(AccessDenied):
        v.search_fulltext("SECRET", path="../vault-secret")
    with pytest.raises(AccessDenied):
        v.list_notes(".obsidian")


def test_read_only_blocks_every_write(sandbox):
    vault_dir, _ = sandbox
    v = Vault(vault_dir, read_only=True)
    assert v.read_note("note.md") == "hello"
    for call in (
        lambda: v.write_note("new.md", "x"),
        lambda: v.append_note("note.md", "x"),
        lambda: v.delete_note("note.md"),
        lambda: v.move_note("note.md", "moved.md"),
    ):
        with pytest.raises(AccessDenied, match="read-only"):
            call()
    assert (vault_dir / "note.md").read_text() == "hello"


def test_delete_moves_to_trash(sandbox):
    vault_dir, _ = sandbox
    v = Vault(vault_dir)
    v.delete_note("note.md")
    assert not (vault_dir / "note.md").exists()
    assert (vault_dir / ".trash" / "note.md").read_text() == "hello"
    # A second delete of the same name doesn't clobber the first.
    (vault_dir / "note.md").write_text("again")
    v.delete_note("note.md")
    assert len(list((vault_dir / ".trash").glob("note*.md"))) == 2


def test_size_limit(sandbox, monkeypatch):
    import obsidian_mcp.vault as vault_mod

    monkeypatch.setattr(vault_mod, "MAX_NOTE_BYTES", 10)
    v = Vault(sandbox[0])
    with pytest.raises(ValueError, match="larger than"):
        v.write_note("big.md", "x" * 11)


def test_template_does_not_overwrite_existing_note(sandbox):
    vault_dir, _ = sandbox
    (vault_dir / "tpl.md").write_text("# {{title}}")
    v = Vault(vault_dir)
    with pytest.raises(FileExistsError):
        create_from_template(v, "tpl.md", "note.md")
    assert (vault_dir / "note.md").read_text() == "hello"


def test_archive_rejects_traversal_out_of_inbox(sandbox):
    vault_dir, _ = sandbox
    v = Vault(vault_dir)
    from obsidian_mcp.ingest import archive_inbox_note

    with pytest.raises(ValueError, match="Not an inbox note"):
        archive_inbox_note(v, "inbox/../note.md")
