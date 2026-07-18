"""REVIEW stage 07 — assemble the departure register.

Bucket (mapping doc task 9): **Deterministic** (template fill). Collects the s03 departures into one
:class:`DepartureRegister` structured exactly per the review doc — header fields (Project, Contract
Type, Package, Subcontract Reference, Subcontractor Name, Submission Date) plus the line items with
their Open/Closed status column. No AI.

This slice runs s01→s02→s03→s07→s08 only; ``scope_findings`` / ``program_findings`` / ``cashflow``
(s04–s06) are slice 2. When they are absent, the register records them in ``slice2_pending`` so the
gap is explicit rather than silently missing. Assembly does not approve — every verdict stays as s03
left it; only the human approve endpoint moves a line to confirmed/dismissed.
"""

from __future__ import annotations

from typing import Optional

from client_boq.models import (
    CashflowProfile,
    ContextSummary,
    DepartureRegister,
    DepartureSet,
    ParsedDocumentSet,
    ProgramFindingSet,
    ScopeAlignmentSet,
)


def assemble_register(
    set_id: str,
    parsed: ParsedDocumentSet,
    summary: ContextSummary,
    departures: DepartureSet,
    *,
    scope_findings: Optional[ScopeAlignmentSet] = None,
    program_findings: Optional[ProgramFindingSet] = None,
    cashflow: Optional[CashflowProfile] = None,
) -> DepartureRegister:
    """Assemble the departure register from the review findings (verdicts left as s03 set them)."""
    pending: list[str] = []
    if scope_findings is None:
        pending.append("scope_alignment")
    if program_findings is None:
        pending.append("program")
    if cashflow is None:
        pending.append("cashflow")

    return DepartureRegister(
        set_id=set_id,
        project=parsed.name,
        package=parsed.name,
        items=list(departures.departures),
        aligned_criteria=list(departures.aligned_criteria),
        slice2_pending=pending,
        approved=False,
    )
