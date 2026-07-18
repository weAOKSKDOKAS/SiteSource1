"""REVIEW stage 06 — cash-flow profile from payment terms + program.

Bucket (mapping doc task 8): **Deterministic**. Pure math/spreadsheet — no AI. The numbers are
deterministic; the model touches nothing here.
"""

from __future__ import annotations

from client_boq.models import CashflowProfile, ContextSummary, ParsedDocumentSet


def build_cashflow(parsed: ParsedDocumentSet, summary: ContextSummary) -> CashflowProfile:
    """Compute a period-by-period cash-flow profile and flag negative periods. Not implemented yet."""
    raise NotImplementedError("client_boq REVIEW s06 (cashflow) — scaffold only")
