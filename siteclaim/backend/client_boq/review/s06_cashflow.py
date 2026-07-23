"""REVIEW stage 06 — cash-flow profile from payment terms + program.

Bucket (mapping doc task 8): **Deterministic**. No AI call. From the extracted payment terms (retention
%, assessment/claim lag) and the program duration (or the default when no programme was provided),
compute a monthly high-level cash-flow profile: monthly claims, receipts lagged by the assessment
period and reduced by retention, retention released at its trigger, and the running cumulative
position. Pure math, reproducible.

Per locked decision 3A the curve attaches to the register as its own ``cashflow`` section; a
commercial finding that needs a human verdict (e.g. sustained negative cash flow) becomes a tagged
``source == cashflow`` line item.
"""

from __future__ import annotations

import re
from typing import Optional

from client_boq.models import (
    SOURCE_CASHFLOW,
    STATUS_CANDIDATE,
    CashflowPoint,
    CashflowSection,
    ContextSummary,
    DepartureItem,
    ParsedDocumentSet,
)

_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")

# High-level defaults when a value cannot be read from the terms.
DEFAULT_CONTRACT_VALUE = 1_000_000.0
DEFAULT_MONTHS = 6              # assumed duration when no programme is provided
DEFAULT_LAG_MONTHS = 1
DEFAULT_RETENTION_PCT = 10.0
DEFAULT_MARGIN = 0.10
_BUSINESS_DAYS_PER_MONTH = 20


def _num(value: str) -> Optional[float]:
    m = _NUMBER_RE.search(value or "")
    return float(m.group(1)) if m else None


def compute_cashflow(
    contract_value: float, months: int, lag_months: int, retention_pct: float,
    release_month: int, margin: float = DEFAULT_MARGIN,
) -> CashflowSection:
    """Deterministic monthly cash-flow profile. Costs are spent over the construction months; each
    month's claim is certified and paid (less retention) ``lag_months`` later; retention is released
    in ``release_month``. Returns the curve, negative periods, the working-capital peak (most-negative
    cumulative), and plain-text findings."""
    months = max(1, months)
    lag_months = max(0, lag_months)
    monthly_claim = contract_value / months
    monthly_cost = contract_value * (1 - margin) / months
    retention_total = contract_value * (retention_pct / 100.0)
    horizon = max(months + lag_months, release_month)

    points: list[CashflowPoint] = []
    cumulative = 0.0
    peak = 0.0
    negative: list[str] = []
    for m in range(1, horizon + 1):
        inflow = 0.0
        # Receipts: claims from month (m - lag), net of retention.
        claim_month = m - lag_months
        if 1 <= claim_month <= months:
            inflow += monthly_claim * (1 - retention_pct / 100.0)
        if m == release_month:
            inflow += retention_total
        outflow = monthly_cost if 1 <= m <= months else 0.0
        net = round(inflow - outflow, 2)
        cumulative = round(cumulative + net, 2)
        peak = min(peak, cumulative)
        if cumulative < 0:
            negative.append(f"M{m}")
        points.append(CashflowPoint(period=f"M{m}", inflow=round(inflow, 2),
                                    outflow=round(outflow, 2), net=net, cumulative=cumulative))

    findings: list[str] = []
    if negative:
        findings.append(f"{len(negative)} month(s) of negative cumulative cash flow ({', '.join(negative)}).")
    findings.append(f"Working-capital peak (funding requirement): {abs(peak):.2f}.")
    assumptions = [
        f"Contract value assumed {contract_value:.0f}.",
        f"Duration {months} month(s); receipt lag {lag_months} month(s); retention {retention_pct:.1f}%; "
        f"retention released in M{release_month}; margin {margin*100:.0f}%.",
    ]
    return CashflowSection(points=points, negative_periods=negative, working_capital_peak=round(peak, 2),
                           findings=findings, assumptions=assumptions)


def _retention_pct(criteria_items: list[DepartureItem]) -> float:
    for it in criteria_items:
        if it.criterion_id == "PS-04":
            n = _num(it.extracted_value)
            if n is not None:
                return n
    return DEFAULT_RETENTION_PCT


def _lag_months(criteria_items: list[DepartureItem]) -> int:
    for it in criteria_items:
        if it.criterion_id == "PS-01":
            n = _num(it.extracted_value)
            if n is not None:
                return max(1, round(n / _BUSINESS_DAYS_PER_MONTH))
    return DEFAULT_LAG_MONTHS


def check_cashflow(
    parsed: ParsedDocumentSet, summary: ContextSummary, criteria_items: list[DepartureItem],
    *, program_months: Optional[int] = None,
) -> tuple[CashflowSection, list[DepartureItem]]:
    """Derive the parameters from the extracted terms (retention from PS-04, lag from PS-01, duration
    from the programme or the default) and compute the section. Returns the section plus any
    verdict-needing line items (a working-capital finding becomes one candidate ``cashflow`` line)."""
    months = program_months or DEFAULT_MONTHS
    lag = _lag_months(criteria_items)
    retention = _retention_pct(criteria_items)
    release_month = months + lag + 1  # retention held to Final Certificate (after the works)
    section = compute_cashflow(DEFAULT_CONTRACT_VALUE, months, lag, retention, release_month)

    lines: list[DepartureItem] = []
    if section.negative_periods:
        lines.append(DepartureItem(
            clause="", source=SOURCE_CASHFLOW, kind="working_capital", status=STATUS_CANDIDATE,
            rationale=(f"Sustained negative cash flow across {len(section.negative_periods)} month(s); "
                       f"peak funding requirement {abs(section.working_capital_peak):.0f}. A commercial "
                       f"adjustment to payment terms is recommended."),
        ))
    return section, lines
