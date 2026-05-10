"""Hit@k and MRR over labeled (query, expected_paths) pairs.

Definitions:
- ``hit@k(query)`` = 1 if any expected path is in the top-k retrieved
  paths, else 0. Aggregate is the mean across all queries.
- ``MRR`` = mean of 1/rank, where rank is the position (1-indexed) of
  the first expected path in the retrieved list. Queries with no
  expected hit contribute 0.
- ``register_clean_rate`` is unused at retrieval-only level but
  exposed for future end-to-end answer eval; it counts the fraction
  of LLM responses with no generic-marker hits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class QueryResult:
    query: str
    expected: list[str]
    retrieved: list[str]  # ranked paths, top-1 first


@dataclass
class EvalReport:
    per_query: list[QueryResult] = field(default_factory=list)

    def hit_at_k(self, k: int) -> float:
        if not self.per_query:
            return 0.0
        hits = sum(
            1
            for r in self.per_query
            if any(exp in r.retrieved[:k] for exp in r.expected)
        )
        return hits / len(self.per_query)

    def mrr(self) -> float:
        if not self.per_query:
            return 0.0
        total = 0.0
        for r in self.per_query:
            best = 0.0
            for exp in r.expected:
                if exp in r.retrieved:
                    rank = r.retrieved.index(exp) + 1
                    best = max(best, 1.0 / rank)
            total += best
        return total / len(self.per_query)

    def misses(self, k: int = 5) -> list[QueryResult]:
        return [
            r
            for r in self.per_query
            if not any(exp in r.retrieved[:k] for exp in r.expected)
        ]


def evaluate(
    labeled: Sequence[tuple[str, list[str]]],
    retrieve: callable,  # (query: str) -> list[str]
) -> EvalReport:
    """Run ``retrieve`` on each query, collect a report."""
    report = EvalReport()
    for query, expected in labeled:
        retrieved = retrieve(query)
        report.per_query.append(
            QueryResult(query=query, expected=expected, retrieved=retrieved),
        )
    return report
