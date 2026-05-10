#!/usr/bin/env python3
"""Run the retrieval eval harness and print metrics + a per-query breakdown.

Useful for tuning rank() weights or comparing embedders without
having to read pytest output. Reuses ``tests/eval/`` so the labeled
corpus is the same one CI runs against.

    python scripts/eval_retrieval.py
    OBSIDIAN_EMBEDDER=ollama OBSIDIAN_EMBEDDER_MODEL=nomic-embed-text \\
        python scripts/eval_retrieval.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from eval.corpus import write_corpus  # noqa: E402
from eval.metrics import evaluate  # noqa: E402
from eval.queries import LABELED_QUERIES  # noqa: E402

from obsidian_mcp.embeddings import get_backend  # noqa: E402
from obsidian_mcp.vault import Vault  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        vault_path = Path(td)
        write_corpus(vault_path)
        vault = Vault(vault_path)
        backend = get_backend()
        print(f"embedder: {backend.model_id}")
        vault.enable_semantic(
            embedder=backend, db_path=vault_path / ".obsidian-mcp" / "idx.db",
        )
        vault.rebuild_embeddings()
        if not vault._embed_queue.wait_idle(timeout=120):
            print("error: embed queue did not drain", file=sys.stderr)
            return 2

        def retrieve(q: str) -> list[str]:
            return [r["path"] for r in vault.semantic_search(q, k=10)]

        report = evaluate(LABELED_QUERIES, retrieve)
        print()
        print(f"hit@1: {report.hit_at_k(1):.2f}  ({_count(report, 1)}/{len(report.per_query)})")
        print(f"hit@3: {report.hit_at_k(3):.2f}  ({_count(report, 3)}/{len(report.per_query)})")
        print(f"hit@5: {report.hit_at_k(5):.2f}  ({_count(report, 5)}/{len(report.per_query)})")
        print(f"MRR:   {report.mrr():.3f}")
        print()
        for r in report.per_query:
            ok = any(e in r.retrieved[:5] for e in r.expected)
            mark = "  OK " if ok else "MISS "
            print(f"{mark} {r.query!r}")
            print(f"      expected: {r.expected}")
            print(f"      top-5:    {r.retrieved[:5]}")
        return 0


def _count(report, k: int) -> int:
    return sum(
        1 for r in report.per_query if any(e in r.retrieved[:k] for e in r.expected)
    )


if __name__ == "__main__":
    sys.exit(main())
