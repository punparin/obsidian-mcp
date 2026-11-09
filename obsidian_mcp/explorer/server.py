"""FastAPI app powering the Vault Explorer (debug + visualize + demo)."""

from __future__ import annotations

import logging
import os
from importlib import metadata
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..links import get_graph
from ..vault import AccessDenied, Vault, env_flag

# Only answer requests addressed to these hostnames. Blocks DNS-rebinding,
# where a malicious website points its own domain at 127.0.0.1 to read
# your vault through the browser. Add more via OBSIDIAN_EXPLORER_HOSTS.
DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

logger = logging.getLogger(__name__)


def _package_version() -> str:
    """Resolve the installed package version, falling back to 'dev' when the
    explorer is run from a non-installed checkout."""
    try:
        return metadata.version("obsidian-mcp")
    except metadata.PackageNotFoundError:
        return "dev"


class SearchRequest(BaseModel):
    query: str
    k: int = Field(default=10, ge=1, le=50)
    weights: dict[str, float] | None = None


class DismissRequest(BaseModel):
    source: str
    target: str


class ApplyRequest(BaseModel):
    source: str
    target: str


def _build_vault() -> Vault:
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if not vault_path:
        raise RuntimeError(
            "OBSIDIAN_VAULT_PATH is not set — point it at your Obsidian vault."
        )
    v = Vault(vault_path, read_only=env_flag("OBSIDIAN_READ_ONLY"))
    # Watcher keeps the index live; semantic stack reuses the same
    # SQLite index the MCP server uses, so the demo and Claude Code can
    # share state during a presentation.
    v.start_watching()
    enabled = v.enable_semantic()
    if not enabled:
        logger.warning(
            "semantic disabled — set OBSIDIAN_EMBEDDER (unset OBSIDIAN_EMBEDDER=none) "
            "for the full explorer experience"
        )
    return v


def create_app() -> FastAPI:
    vault = _build_vault()
    # No interactive API docs: nothing should be reachable that the UI doesn't use.
    app = FastAPI(title="obsidian-mcp explorer", docs_url=None, redoc_url=None, openapi_url=None)
    extra_hosts = [h.strip() for h in os.environ.get("OBSIDIAN_EXPLORER_HOSTS", "").split(",") if h.strip()]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=DEFAULT_ALLOWED_HOSTS + extra_hosts)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    static_dir = Path(__file__).parent / "static"

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "vault": str(vault.root),
            "semantic_enabled": vault.semantic_enabled,
            "stats": vault.embedding_stats(),
            "version": _package_version(),
        }

    @app.post("/api/search")
    async def search(req: SearchRequest) -> dict[str, Any]:
        if not vault.semantic_enabled:
            raise HTTPException(503, "semantic search disabled")
        results = vault.semantic_search(req.query, k=req.k, weights=req.weights)
        return {"query": req.query, "results": results}

    @app.get("/api/graph")
    async def graph() -> dict[str, Any]:
        return get_graph(vault.index)

    @app.get("/api/suggestions")
    async def suggestions(
        path: str | None = None, limit: int = 25, min_score: float = 0.55
    ) -> dict[str, Any]:
        if not vault.semantic_enabled:
            raise HTTPException(503, "semantic search disabled")
        results = vault.suggest_links(path=path, limit=limit, min_score=min_score)
        return {"results": results, "count": len(results)}

    @app.post("/api/suggestions/dismiss")
    async def dismiss(req: DismissRequest) -> dict[str, Any]:
        vault.dismiss_link_suggestion(req.source, req.target)
        return {"dismissed": [req.source, req.target]}

    @app.post("/api/suggestions/apply")
    async def apply_(req: ApplyRequest) -> dict[str, Any]:
        try:
            msg = vault.apply_link_suggestion(req.source, req.target)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from None
        except AccessDenied as exc:
            raise HTTPException(403, str(exc)) from None
        return {"message": msg}

    @app.get("/api/note")
    async def note(path: str) -> dict[str, Any]:
        try:
            content = vault.read_note(path)
        except FileNotFoundError:
            raise HTTPException(404, f"note not found: {path}") from None
        except AccessDenied as exc:
            raise HTTPException(403, str(exc)) from None
        entry = vault.index.get(path)
        return {
            "path": path,
            "title": entry.title if entry else Path(path).stem,
            "tags": entry.tags if entry else [],
            "content": content,
        }

    app.mount(
        "/static",
        StaticFiles(directory=str(static_dir)),
        name="static",
    )
    return app


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="obsidian_mcp.explorer")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
