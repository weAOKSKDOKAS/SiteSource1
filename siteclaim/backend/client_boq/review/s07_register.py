"""REVIEW stage 07 — assemble the ONE departure register.

Bucket (mapping doc task 9): **Deterministic** (template fill). Folds every check into a single
register (locked decision 3A): s03 criteria departures, s04 scope-alignment lines, and s05 program
lines all become tagged line ``items``; s06's cash-flow curve attaches as the ``cashflow`` section
(with its own verdict-needing lines already tagged ``source == cashflow``); s03's compliant numeric
criteria are the ``aligned`` section. No AI.

Line numbering puts the actionable lines first and the grouped ``unresolved`` criteria last (locked
decision 1A is a presentation concern handled in the router payload; here we simply keep unresolved
lines after the actionable ones so their item numbers are stable and high). Assembly does not
approve — verdicts stay as the stages left them; only the human approve endpoint moves a line to
confirmed/dismissed.
"""

from __future__ import annotations

from typing import Optional

from client_boq.models import (
    STATUS_UNRESOLVED,
    CashflowSection,
    ContextSummary,
    DepartureItem,
    DepartureRegister,
    DepartureSet,
    ParsedDocumentSet,
)


def assemble_register(
    set_id: str,
    parsed: ParsedDocumentSet,
    summary: ContextSummary,
    departures: DepartureSet,
    *,
    scope_items: Optional[list[DepartureItem]] = None,
    program_items: Optional[list[DepartureItem]] = None,
    cashflow: Optional[CashflowSection] = None,
    cashflow_items: Optional[list[DepartureItem]] = None,
) -> DepartureRegister:
    """Assemble the one register from all review findings (verdicts left as the stages set them)."""
    criteria_actionable = [d for d in departures.departures if d.status != STATUS_UNRESOLVED]
    unresolved = [d for d in departures.departures if d.status == STATUS_UNRESOLVED]

    # Actionable lines first (criteria, then scope, program, cashflow), grouped-unresolved last.
    ordered = [
        *criteria_actionable,
        *(scope_items or []),
        *(program_items or []),
        *(cashflow_items or []),
        *unresolved,
    ]
    for i, item in enumerate(ordered, start=1):
        item.item = i

    return DepartureRegister(
        set_id=set_id,
        project=parsed.name,
        package=parsed.name,
        items=ordered,
        aligned=list(departures.aligned),
        cashflow=cashflow,
        approved=False,
    )
