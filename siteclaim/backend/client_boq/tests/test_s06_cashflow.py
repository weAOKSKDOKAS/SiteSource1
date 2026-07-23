"""Unit tests for REVIEW s06 (cash-flow) — pure deterministic math, incl. retention release."""

from __future__ import annotations

from client_boq.models import SOURCE_CASHFLOW, ContextSummary, DepartureItem
from client_boq.review.s01_ingest import ingest_review_documents
from client_boq.review.s06_cashflow import check_cashflow, compute_cashflow


def test_compute_cashflow_negative_then_recovers_with_retention_release() -> None:
    s = compute_cashflow(contract_value=1_000_000, months=6, lag_months=2, retention_pct=10,
                         release_month=9, margin=0.10)
    # Early months spend before receipts arrive (2-month lag) → negative cumulative.
    assert "M1" in s.negative_periods and "M2" in s.negative_periods
    assert s.working_capital_peak < 0
    # Retention (10% of 1,000,000 = 100,000) is released in M9 and recovers the position.
    m9 = next(p for p in s.points if p.period == "M9")
    assert m9.inflow >= 100_000
    assert s.points[-1].cumulative > 0        # profit (margin) + retention returned


def test_compute_cashflow_no_lag_no_retention_stays_non_negative() -> None:
    s = compute_cashflow(contract_value=1_000_000, months=6, lag_months=0, retention_pct=0,
                         release_month=7, margin=0.10)
    # Paid same month, no retention held → each month is cash-positive, never negative.
    assert s.negative_periods == []
    assert s.working_capital_peak == 0.0


def test_check_cashflow_derives_terms_and_emits_working_capital_line() -> None:
    parsed = ingest_review_documents([], "demo")
    # Terms the derivation reads: retention from PS-04, assessment lag from PS-01.
    items = [
        DepartureItem(criterion_id="PS-04", extracted_value="Retention 10%, released at Final Certificate"),
        DepartureItem(criterion_id="PS-01", extracted_value="Assessment within 30 business days"),
    ]
    section, lines = check_cashflow(parsed, ContextSummary(), items)
    assert section.negative_periods                    # held retention + lag → negative months
    assert section.assumptions                         # the parameters are disclosed
    wc = [l for l in lines if l.kind == "working_capital"]
    assert wc and wc[0].source == SOURCE_CASHFLOW      # verdict-needing finding → a tagged line item
