"""Unit tests for REVIEW s08 (citation verify) — the deterministic anti-hallucination guard.

Asserts a cited clause that is absent from the parsed set, and a quote that is not contained in its
clause, are both marked ``citation_failed`` and kept visible; a real, supported citation passes; and
an unresolved line (no clause) is skipped.
"""

from __future__ import annotations

from client_boq.models import (
    STATUS_CANDIDATE,
    STATUS_CITATION_FAILED,
    STATUS_RULE_FLAGGED,
    STATUS_UNRESOLVED,
    ClauseItem,
    DepartureItem,
    DepartureRegister,
    ParsedDocumentSet,
)
from client_boq.review.s08_citation_verify import verify_citations


def _parsed() -> ParsedDocumentSet:
    return ParsedDocumentSet(
        set_id="t", name="t", slug="t",
        clauses=[
            ClauseItem(clause_id="8.3", text="Liquidated damages apply with no cap on the aggregate amount."),
            ClauseItem(clause_id="5.2", text="Retention of 10% held to the Final Certificate."),
        ],
    )


def test_missing_clause_and_bad_quote_fail_present_ones_pass() -> None:
    register = DepartureRegister(
        set_id="t",
        items=[
            DepartureItem(item=1, clause="8.3", cited_text="no cap on the aggregate amount",
                          status=STATUS_RULE_FLAGGED),                       # real + supported -> ok
            DepartureItem(item=2, clause="5.2", cited_text="a phrase that is not in the clause",
                          status=STATUS_RULE_FLAGGED),                       # present but unsupported -> fail
            DepartureItem(item=3, clause="13.5", cited_text="call security without notice",
                          status=STATUS_CANDIDATE),                          # absent clause -> fail
            DepartureItem(item=4, clause="", criterion_id="TP-02", status=STATUS_UNRESOLVED),  # skipped
        ],
    )
    checks = verify_citations(register, _parsed())

    by_item = {c.item: c for c in checks}
    assert by_item[1].ok is True
    assert by_item[2].found is True and by_item[2].supported is False
    assert by_item[3].found is False
    # The unresolved line (no clause) produced no check.
    assert 4 not in by_item

    status = {d.item: d.status for d in register.items}
    assert status[1] == STATUS_RULE_FLAGGED               # unchanged
    assert status[2] == STATUS_CITATION_FAILED            # bad quote
    assert status[3] == STATUS_CITATION_FAILED            # absent clause
    assert status[4] == STATUS_UNRESOLVED                 # untouched
    # Nothing was dropped — the failed lines are still present, just marked.
    assert len(register.items) == 4
