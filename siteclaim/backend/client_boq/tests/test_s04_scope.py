"""Unit tests for REVIEW s04 (scope alignment) + the deterministic precedence rule."""

from __future__ import annotations

from client_boq import rules
from client_boq.models import (
    SOURCE_SCOPE_ALIGNMENT,
    STATUS_CANDIDATE,
    STATUS_RULE_FLAGGED,
    ContextSummary,
)
from client_boq.review.s01_ingest import ingest_review_documents
from client_boq.review.s04_scope_align import check_scope_alignment


def _parsed():
    # DEMO: returns the fixture parse (offline), including the inverted precedence clause 2.1.
    return ingest_review_documents([], "demo")


def test_precedence_extraction_and_violation() -> None:
    order = rules.extract_precedence_order(
        "documents take precedence in the following order: the Specification, the Drawings, "
        "the Scope of Works, and this Agreement."
    )
    assert order == ["specification", "drawings", "scope", "contract"]
    assert rules.precedence_violation(order) is True                       # inverted
    assert rules.precedence_violation(["contract", "scope", "drawings", "specification"]) is False
    assert rules.precedence_violation(["contract", "drawings"]) is False   # partial, in order
    assert rules.precedence_violation(["drawings", "contract"]) is True    # inverted pair
    assert rules.precedence_violation([]) is False                        # nothing to judge


def test_scope_alignment_demo_produces_tagged_lines() -> None:
    lines = check_scope_alignment(_parsed(), ContextSummary())
    assert all(l.source == SOURCE_SCOPE_ALIGNMENT for l in lines)

    # Deterministic precedence breach (clause 2.1 lists specs above the contract) → rule_flagged.
    prec = [l for l in lines if l.kind == "precedence"]
    assert prec and prec[0].status == STATUS_RULE_FLAGGED and prec[0].clause == "2.1"
    assert prec[0].rule_ref == "SQD-01"

    # The AI-proposed scope finding is a candidate (the human decides), with a citation.
    ai = [l for l in lines if l.kind == "responsibility_creep"]
    assert ai and ai[0].status == STATUS_CANDIDATE and ai[0].clause == "3.2"

    # Absent inputs (letter of offer / clarifications / estimate) are surfaced, not skipped.
    assert any(l.kind == "input_missing" for l in lines)
