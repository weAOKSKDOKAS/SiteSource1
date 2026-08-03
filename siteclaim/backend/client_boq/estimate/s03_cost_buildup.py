"""ESTIMATE stage 03 — cost build-up (quantity × rate).

Bucket (mapping doc estimate tasks 7a/8/9/10): **Deterministic**. Quantities are given; rates resolve
from ``rates.py`` (the CSV seam) or an inline rate; productivity (output per hour) converts a work
quantity into hours before the rate applies. Each line records a full trace — qty, rate, where the
rate came from (``csv`` | ``inline`` | ``missing``), and any hours — so a human can recompute it by
hand. A referenced resource with no resolvable rate is costed as **0** and marked
``rate_source == "missing"`` (s05 surfaces the ``missing_rate`` flag) — visible, never guessed.

Signature change from the scaffold: ``build_cost(EstimateSchedule, list[RateRow]) -> list[CostActivity]``.
"""

from __future__ import annotations

from client_boq import rates as rates_mod
from client_boq.estimate import money
from client_boq.models import CostActivity, CostLine, EstimateSchedule, RateRow, ResourceLine


def _resolve_rate(line: ResourceLine, idx: dict[str, RateRow]) -> tuple[float, str]:
    """(rate, source). An inline rate wins (it is a deliberate override); otherwise the CSV rate for
    the resource_ref; otherwise 0 / 'missing'."""
    if line.inline_rate is not None:
        return float(line.inline_rate), "inline"
    if line.resource_ref:
        row = idx.get(line.resource_ref)
        if row is not None:
            return float(row.rate), "csv"
    return 0.0, "missing"


def _cost_line(item_id: str, line: ResourceLine, idx: dict[str, RateRow]) -> CostLine:
    rate, source = _resolve_rate(line, idx)
    hours = None
    if line.productivity is not None and line.productivity > 0:
        hours = money(line.qty / line.productivity)
        amount = money(hours * rate)
    else:
        amount = money(line.qty * rate)
    return CostLine(
        item_id=item_id, description=line.description, resource_ref=line.resource_ref,
        qty=line.qty, unit=line.unit, productivity=line.productivity, hours=hours,
        rate=rate, rate_source=source, amount=amount,
    )


def build_cost(schedule: EstimateSchedule, rates: list[RateRow]) -> list[CostActivity]:
    """Price every direct activity's resource lines. Deterministic; item numbers/ids come from s02."""
    idx = rates_mod.rate_index(rates)
    activities: list[CostActivity] = []
    for item in schedule.items:
        if item.category != "direct":
            continue
        lines = [_cost_line(item.item_id, rl, idx) for rl in item.lines]
        activity_total = money(sum(l.amount for l in lines))
        activities.append(CostActivity(
            item_id=item.item_id, description=item.description, category="direct",
            unit=item.unit, lines=lines, activity_total=activity_total,
        ))
    return activities


def direct_total(activities: list[CostActivity]) -> float:
    """The direct-cost subtotal — sum of the (already-rounded) activity totals."""
    return money(sum(a.activity_total for a in activities))
