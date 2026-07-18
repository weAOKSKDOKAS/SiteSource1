"""ESTIMATE stage 01 — tender & scope review.

Bucket (mapping doc estimate task 1/2): **AI draft** (human-reviewed). Reads the approved
document context into inclusions, exclusions, ambiguities, conflicts, and drafts clarifying
questions + assumptions (``llm_client.complete_json`` against :class:`ScopeReviewResult`). Draft
only — no decision value.

Runs only AFTER the review register for this document set is human-approved (the review→estimate
gate; enforced by ``router``).
"""

from __future__ import annotations

from client_boq.models import ParsedDocumentSet, ScopeReviewResult

DEMO_FIXTURE = "cases/client_boq/estimate_scope_review.json"


def review_scope(parsed: ParsedDocumentSet) -> ScopeReviewResult:
    """Draft inclusions/exclusions/ambiguities and clarifying questions. Not implemented yet."""
    raise NotImplementedError("client_boq ESTIMATE s01 (scope review) — scaffold only")
