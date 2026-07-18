"""REVIEW stage 08 — citation verification (the anti-hallucination guard).

Bucket (mapping doc task 10): **Deterministic lookup**. For every clause the register cites, confirm
that clause actually exists in the parsed document set — an index/locus lookup, NOT something the AI
is trusted to self-check. A register that departs against a clause that does not exist is one of the
worst outcomes with a client, so this deterministic check is the safeguard. Unfound citations are
surfaced, never silently accepted.
"""

from __future__ import annotations

from client_boq.models import CitationCheck, DepartureRegister, ParsedDocumentSet


def verify_citations(
    register: DepartureRegister, parsed: ParsedDocumentSet,
) -> list[CitationCheck]:
    """Confirm every cited clause exists in the parsed documents (deterministic lookup).
    Not implemented yet."""
    raise NotImplementedError("client_boq REVIEW s08 (citation verify) — scaffold only")
