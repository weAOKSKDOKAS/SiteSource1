"""Unit tests for ESTIMATE s01 (scope review) + the register→estimate wiring.

Confirmed departures are injected into the scope as register-sourced assumptions; dismissed items are
never carried (they must not resurface as scope risks). Runs offline (DEMO fixture for the draft).
"""

from __future__ import annotations

from client_boq.estimate.s01_scope_review import review_scope
from client_boq.models import (
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    ContextSummary,
    DepartureItem,
    DepartureRegister,
)
from client_boq.review.s01_ingest import ingest_review_documents

_CONFIRMED_POSITION = "Liquidated damages capped at 10% of the Subcontract value"
_DISMISSED_POSITION = "Delete the fitness-for-purpose warranty entirely"


def _register() -> DepartureRegister:
    return DepartureRegister(set_id="t", items=[
        DepartureItem(item=1, clause="8.3", criterion_id="TP-04", clause_area="Liquidated Damages",
                      proposed_position=_CONFIRMED_POSITION, status=STATUS_CONFIRMED),
        DepartureItem(item=2, clause="3.2", criterion_id="SQD-06", clause_area="Warranties",
                      proposed_position=_DISMISSED_POSITION, status=STATUS_DISMISSED),
    ])


def test_confirmed_injected_dismissed_excluded() -> None:
    parsed = ingest_review_documents([], "demo")
    scope = review_scope(parsed, ContextSummary(), _register())

    # The AI draft came through (summary + notes from the fixture).
    assert scope.summary and scope.notes

    texts = [n.text for n in scope.notes]
    # The confirmed departure's agreed position is injected as a register-sourced assumption.
    assert any(_CONFIRMED_POSITION in t for t in texts)
    injected = [n for n in scope.notes if n.source == "register"]
    assert injected and all(n.kind == "assumption" for n in injected)
    # The dismissed item never resurfaces anywhere in the scope.
    assert all(_DISMISSED_POSITION not in t for t in texts)


def test_no_confirmed_means_no_injection() -> None:
    parsed = ingest_review_documents([], "demo")
    empty = DepartureRegister(set_id="t", items=[
        DepartureItem(item=1, criterion_id="TP-04", status="rule_flagged", proposed_position="x"),
    ])
    scope = review_scope(parsed, ContextSummary(), empty)
    assert all(n.source == "draft" for n in scope.notes)  # nothing confirmed → nothing injected
