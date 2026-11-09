"""Explorer HTTP hardening: host allowlist, security headers, vault access rules."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from obsidian_mcp.explorer.server import create_app  # noqa: E402


@pytest.fixture
def client(tmp_vault, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_vault))
    monkeypatch.setenv("OBSIDIAN_EMBEDDER", "none")
    return TestClient(create_app(), base_url="http://127.0.0.1:8765")


def test_rejects_foreign_host_header(client):
    # DNS rebinding: attacker.example resolves to 127.0.0.1 in the victim's browser.
    r = client.get("/api/graph", headers={"host": "attacker.example"})
    assert r.status_code == 400


def test_localhost_allowed_with_security_headers(client):
    r = client.get("/api/graph")
    assert r.status_code == 200
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_note_endpoint_enforces_access_rules(client):
    assert client.get("/api/note", params={"path": "note1.md"}).status_code == 200
    for bad in ("../../etc/passwd", ".obsidian/app.md", "schema.yml"):
        assert client.get("/api/note", params={"path": bad}).status_code == 403


def test_api_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
