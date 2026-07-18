"""REVIEW stage 03 — match each contract clause against the criteria library.

Bucket (mapping doc tasks 5a/5b/5c): **AI propose → rule pre-flag → human gate**.
The AI proposes which criterion each clause maps to, extracts the numeric field, and drafts the
departure rationale/proposed position (``llm_client.complete_json``). The RULE layer then pre-flags
ONLY the numeric criteria in the threshold table (``ThresholdRule``) — a deterministic threshold
test. The breach VERDICT is never written here: every departure stays ``verdict="unreviewed"``
until a human gate (s07 / router) sets it. The AI never writes "breach / no breach".

No referenced criterion is silently dropped: a criterion that cannot be resolved against the
documents is surfaced as unresolved, not skipped.
"""

from __future__ import annotations

from client_boq.models import ContextSummary, CriteriaLibrary, DepartureItem, ParsedDocumentSet

DEMO_FIXTURE = "cases/client_boq/review_criteria_match.json"


def match_criteria(
    parsed: ParsedDocumentSet, summary: ContextSummary, library: CriteriaLibrary,
) -> list[DepartureItem]:
    """Propose clause↔criterion matches, extract fields, apply the numeric pre-flag rule, and draft
    departures — verdicts left for the human gate. Not implemented yet."""
    raise NotImplementedError("client_boq REVIEW s03 (criteria match) — scaffold only")
