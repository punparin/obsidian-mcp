"""Retrieval-quality eval harness.

What this guards against: silent regressions in `rank()` weights, the
chunker, the embed queue, or the embedder default. Without a labeled
benchmark, an embedder swap or a weight tweak is untestable —
"semantic_search returns *something*" passes regardless of quality.

Layout: corpus + queries + metrics live under ``tests/eval/``; this
module is the pytest entry point. 19 notes / 18 queries, with several
sibling-note clusters (two async, two decorator, three retrieval
notes, two same-project meetings) so the ranker has to discriminate
rather than picking the only relevant note.

Baseline on the production embedder (``fastembed`` / BGE-small):
hit@1 = 0.94, hit@3 = 1.00, hit@5 = 1.00, MRR = 0.972. Floors below
leave a 1–3 miss tolerance so noise doesn't false-fire.

Marked ``eval`` so default ``pytest`` skips it (loading fastembed
adds ~5s). Run with ``pytest -m eval`` or ``pytest -m ''`` to include.
"""

from __future__ import annotations

import pytest
from eval.corpus import write_corpus
from eval.metrics import evaluate
from eval.queries import LABELED_QUERIES

from obsidian_mcp.embeddings import FastEmbedBackend
from obsidian_mcp.vault import Vault

# Floor numbers. Current baseline (BGE-small): 0.94 / 1.00 / 1.00 / 0.972.
# Floors leave 1–3 miss tolerance so a noise blip doesn't false-fire;
# anything below means a likely regression — investigate before merging.
HIT_AT_1_FLOOR = 0.80
HIT_AT_3_FLOOR = 0.90
HIT_AT_5_FLOOR = 0.94
MRR_FLOOR = 0.85


@pytest.fixture(scope="module")
def eval_vault(tmp_path_factory):
    """Materialize the corpus, embed everything, return a live Vault."""
    vault_path = tmp_path_factory.mktemp("eval-vault")
    write_corpus(vault_path)
    vault = Vault(vault_path)
    backend = FastEmbedBackend()
    vault.enable_semantic(
        embedder=backend, db_path=vault_path / ".obsidian-mcp" / "idx.db",
    )
    vault.rebuild_embeddings()
    assert vault._embed_queue.wait_idle(timeout=120), "embed queue did not drain"
    yield vault
    vault.disable_semantic()


@pytest.fixture(scope="module")
def report(eval_vault):
    def retrieve(q: str) -> list[str]:
        return [r["path"] for r in eval_vault.semantic_search(q, k=10)]

    return evaluate(LABELED_QUERIES, retrieve)


@pytest.mark.eval
def test_hit_at_1_meets_floor(report):
    score = report.hit_at_k(1)
    assert score >= HIT_AT_1_FLOOR, (
        f"hit@1 = {score:.2f} below floor {HIT_AT_1_FLOOR}; "
        f"misses: {[r.query for r in report.misses(1)]}"
    )


@pytest.mark.eval
def test_hit_at_3_meets_floor(report):
    score = report.hit_at_k(3)
    assert score >= HIT_AT_3_FLOOR, (
        f"hit@3 = {score:.2f} below floor {HIT_AT_3_FLOOR}; "
        f"misses: {[r.query for r in report.misses(3)]}"
    )


@pytest.mark.eval
def test_hit_at_5_meets_floor(report):
    score = report.hit_at_k(5)
    assert score >= HIT_AT_5_FLOOR, (
        f"hit@5 = {score:.2f} below floor {HIT_AT_5_FLOOR}; "
        f"misses: {[r.query for r in report.misses(5)]}"
    )


@pytest.mark.eval
def test_mrr_meets_floor(report):
    score = report.mrr()
    assert score >= MRR_FLOOR, f"MRR = {score:.3f} below floor {MRR_FLOOR}"


@pytest.mark.eval
def test_wikilink_query_uses_graph_signal(eval_vault):
    """A query with an explicit ``[[reranking]]`` should rank that note
    at the top — graph signal must contribute, not just cos_sim."""
    results = eval_vault.semantic_search(
        "see [[reranking]] for the pipeline overview", k=5,
    )
    assert results, "expected results"
    top = results[0]
    assert top["path"] == "retrieval/reranking.md"
    assert top["signals"]["wikilink_match"] is True
