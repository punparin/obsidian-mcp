"""Cheap downstream tripwire for "the LLM stopped using the vault."

When retrieval fails — wrong notes, no notes, or notes the model
couldn't tie back to the question — Claude rarely says "I don't
know." It pivots to its priors and the prose register changes:
"generally speaking, …", "typically, …", "based on my general
knowledge, …". A tiny phrase list catches that register shift.

The check costs nothing, runs only on the response string, and is
correlated enough with retrieval failure to be useful as a regression
sniff in eval and as a self-correction nudge for agents at runtime.
It is *not* a quality metric — a marker-clean answer can still be
wrong, and a marker-tripped answer can occasionally be intentional
("typically" inside a quoted code comment, e.g.). Treat the output
as a signal to investigate, not a verdict.
"""

from __future__ import annotations

GENERIC_MARKERS: tuple[str, ...] = (
    "generally speaking",
    "in general,",
    "typically,",
    "usually,",
    "as a general rule",
    "however, based on my knowledge",
    "based on general knowledge",
    "based on my training",
    "i don't have access to",
    "without access to",
)


def check_register(answer: str) -> list[str]:
    """Return the markers from ``GENERIC_MARKERS`` present in ``answer``.

    Case-insensitive substring match. Empty/None input returns an empty
    list. Each marker appears at most once in the result even if it
    occurs multiple times in the answer.
    """
    if not answer:
        return []
    lower = answer.lower()
    return [m for m in GENERIC_MARKERS if m in lower]
