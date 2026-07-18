"""REVIEW stage 04 — scope alignment: contract scope vs the priced scope.

Bucket (mapping doc task 6): **AI propose → precedence rule confirms**.
The AI flags candidate scope gaps, silent assumptions, and responsibility creep
(``llm_client.complete_json``); the document order-of-precedence is a defined hierarchy applied as
a deterministic rule. The verdict goes to the human gate.
"""

from __future__ import annotations

from client_boq.models import ContextSummary, ParsedDocumentSet, ScopeAlignmentFinding

DEMO_FIXTURE = "cases/client_boq/review_scope_align.json"


def check_scope_alignment(
    parsed: ParsedDocumentSet, summary: ContextSummary,
) -> list[ScopeAlignmentFinding]:
    """Propose scope-alignment findings; confirm order-of-precedence by rule. Not implemented yet."""
    raise NotImplementedError("client_boq REVIEW s04 (scope alignment) — scaffold only")
