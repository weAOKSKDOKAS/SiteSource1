"""ESTIMATE stage 03 — cost build-up (quantity × rate).

Bucket (mapping doc estimate tasks 7a/8/9/10): **Deterministic**. Quantities are taken as given
(from a BOQ or manual entry — NO drawing take-off in v1), rates come from ``rates.load_rates``
(the hand-editable CSV seam), and each line's amount is ``qty × rate`` — spreadsheet math, NEVER
AI-written. This is a decision value (price), so no model touches it.
"""

from __future__ import annotations

from client_boq.models import CostBuildup, PricingSchedule, RateRow


def build_cost(
    schedule: PricingSchedule, quantities: dict[str, float], rates: list[RateRow],
) -> CostBuildup:
    """Compute qty × rate for each activity from the given quantities and the rate table.
    Deterministic. Not implemented yet."""
    raise NotImplementedError("client_boq ESTIMATE s03 (cost build-up) — scaffold only")
