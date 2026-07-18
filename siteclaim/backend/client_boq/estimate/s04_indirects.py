"""ESTIMATE stage 04 — indirect costs & allowances.

Bucket (mapping doc estimate task 11): **Deterministic formulas**. Each indirect item carries an
explicit ``basis``:

* ``lump``          — a fixed ``amount``.
* ``per_week``      — ``rate`` × the schedule's ``duration_weeks``.
* ``pct_of_direct`` — ``pct`` × the direct-cost subtotal (so it is computed AFTER s03, per the
                      estimating doc: indirects driven by contract value follow the directs).

An unrecognised basis is costed as 0 with an explanatory ``detail`` (surfaced, not guessed). No AI.

Signature change from the scaffold: ``build_indirects(EstimateSchedule, direct_total) -> list[IndirectLine]``.
"""

from __future__ import annotations

from typing import Optional

from client_boq.estimate import money
from client_boq.models import EstimateSchedule, IndirectLine


def _indirect_line(item, duration_weeks: Optional[float], total_direct: float) -> IndirectLine:
    basis = (item.basis or "").strip().lower()
    label = item.description or item.item_id
    if basis == "lump":
        amount = money(item.amount or 0.0)
        detail = f"lump sum = {amount}"
    elif basis == "per_week":
        weeks = duration_weeks or 0.0
        amount = money((item.rate or 0.0) * weeks)
        detail = f"{item.rate or 0} per week × {weeks} weeks = {amount}"
    elif basis == "pct_of_direct":
        amount = money((item.pct or 0.0) / 100.0 * total_direct)
        detail = f"{item.pct or 0}% × direct {total_direct} = {amount}"
    else:
        amount = 0.0
        detail = f"unrecognised basis {item.basis!r}; costed as 0"
    return IndirectLine(item_id=item.item_id, label=label, basis=basis, detail=detail, amount=amount)


def build_indirects(schedule: EstimateSchedule, total_direct: float) -> list[IndirectLine]:
    """Compute every indirect item's amount from its basis. Deterministic."""
    return [
        _indirect_line(item, schedule.duration_weeks, total_direct)
        for item in schedule.items
        if item.category == "indirect"
    ]


def indirect_total(indirects: list[IndirectLine]) -> float:
    return money(sum(i.amount for i in indirects))
