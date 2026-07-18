"""Unit tests for REVIEW s03 (criteria match) — the AI-propose → rule-flag → surface-everything stage.

Runs offline against the DEMO proposal fixture. Asserts every status path is produced, the rule layer
(not the AI) decides the numeric flags, aligned criteria are recorded, nothing is dropped, and — the
hard constraint — the stage never writes a human verdict (confirmed/dismissed), which is guaranteed
structurally because the AI proposal model has no status field at all.
"""

from __future__ import annotations

from client_boq.criteria_loader import load_criteria
from client_boq.models import (
    HUMAN_VERDICTS,
    STATUS_CANDIDATE,
    STATUS_RULE_FLAGGED,
    STATUS_UNCOVERED,
    STATUS_UNRESOLVED,
    ContextSummary,
    DepartureProposal,
    ParsedDocumentSet,
)
from client_boq.review.s03_criteria_match import match_criteria


def _run():
    return match_criteria(ParsedDocumentSet(), ContextSummary(), load_criteria())


def test_ai_proposal_model_cannot_carry_a_verdict() -> None:
    # Structural guarantee: the AI's s03 output item has no status/verdict field to write into.
    fields = set(DepartureProposal.model_fields)
    assert "status" not in fields and "verdict" not in fields


def test_every_status_path_present() -> None:
    result = _run()
    by_status: dict[str, int] = {}
    for d in result.departures:
        by_status[d.status] = by_status.get(d.status, 0) + 1

    # From the fixture: 6 numeric breaches flagged by rule (incl. the mis-cited PS-05 on 13.5, which
    # s08 later turns to citation_failed), 2 qualitative candidates, 1 uncovered clause.
    assert by_status.get(STATUS_RULE_FLAGGED) == 6
    assert by_status.get(STATUS_CANDIDATE) == 2
    assert by_status.get(STATUS_UNCOVERED) == 1
    assert by_status.get(STATUS_UNRESOLVED, 0) >= 1  # criteria no clause resolved


def test_rule_flags_are_the_expected_criteria() -> None:
    result = _run()
    flagged = {d.criterion_id for d in result.departures if d.status == STATUS_RULE_FLAGGED}
    assert flagged == {"TP-04", "PS-04", "SQD-05", "LR-05", "PS-01", "PS-05"}
    # A non-breaching numeric match aligns (no line) and is recorded richly, not dropped, not unresolved.
    assert {a.criterion_id for a in result.aligned} == {"TP-03", "LR-01"}
    # The aligned section carries the value + why (decision 2A), not just an id.
    lr01 = next(a for a in result.aligned if a.criterion_id == "LR-01")
    assert lr01.extracted_value and lr01.why


def test_no_verdict_is_written_and_nothing_dropped() -> None:
    result = _run()
    # s03 never writes a human verdict.
    assert all(d.status not in HUMAN_VERDICTS for d in result.departures)
    # Item numbers are contiguous 1..N (assembly order), so nothing was silently discarded.
    numbers = [d.item for d in result.departures]
    assert numbers == list(range(1, len(result.departures) + 1))
    # Every populated criterion is accounted for: matched (resolved/aligned) or unresolved.
    lib = load_criteria()
    unresolved = {d.criterion_id for d in result.departures if d.status == STATUS_UNRESOLVED}
    resolved = {d.criterion_id for d in result.departures if d.criterion_id and d.status != STATUS_UNRESOLVED}
    accounted = unresolved | resolved | {a.criterion_id for a in result.aligned}
    assert {c.id for c in lib.criteria} <= accounted
