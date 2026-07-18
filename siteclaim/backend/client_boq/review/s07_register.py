"""REVIEW stage 07 — assemble the departure register.

Bucket (mapping doc task 9): **Deterministic** (template fill). Collects the s03–s06 findings into
one :class:`DepartureRegister` in a fixed structure. No AI. This register is the workflow's decision
surface: the ``approved`` flag on it is the review→estimate gate, set only by a human approval
endpoint (see ``router``). Assembly here does not approve — it just builds the register with every
verdict still ``unreviewed``.
"""

from __future__ import annotations

from client_boq.models import (
    CashflowProfile,
    DepartureItem,
    DepartureRegister,
    ProgramFinding,
    ScopeAlignmentFinding,
)


def assemble_register(
    set_id: str,
    project: str,
    departures: list[DepartureItem],
    scope_findings: list[ScopeAlignmentFinding],
    program_findings: list[ProgramFinding],
    cashflow: CashflowProfile,
) -> DepartureRegister:
    """Assemble the departure register from the review findings (verdicts left unreviewed).
    Not implemented yet."""
    raise NotImplementedError("client_boq REVIEW s07 (register assemble) — scaffold only")
