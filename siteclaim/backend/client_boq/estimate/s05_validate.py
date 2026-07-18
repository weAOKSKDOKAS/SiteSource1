"""ESTIMATE stage 05 — validation flags.

Bucket (mapping doc estimate task 12): **Rule-based flags** (never verdicts, never blocking). Five
concrete v1 checks, each a named flag carrying the offending ``item_id`` for the human:

* ``missing_rate``        — a costed line whose rate could not be resolved (``rate_source == missing``).
* ``zero_or_negative_qty``— a resource line with ``qty <= 0``.
* ``empty_activity``      — a direct item with no resource lines.
* ``rate_outlier``        — an inline rate deviating > ±50% from the CSV rate for the same resource
                            (a benchmark flag, NOT a correction — the inline rate still stands).
* ``unclassified_item``   — an item whose category is neither ``direct`` nor ``indirect``.

Flags read state the earlier stages recorded (s02's normalised category, s03's ``rate_source``); this
stage is the single place the flags are surfaced. Nothing here changes a number.
"""

from __future__ import annotations

from client_boq import rates as rates_mod
from client_boq.models import CostActivity, EstimateFlag, EstimateSchedule, RateRow

RATE_OUTLIER_BAND = 0.50  # ±50%
VALID_CATEGORIES = {"direct", "indirect"}


def validate(
    schedule: EstimateSchedule, activities: list[CostActivity], rates: list[RateRow],
) -> list[EstimateFlag]:
    """Run the five deterministic checks and return the flags (order stable)."""
    idx = rates_mod.rate_index(rates)
    flags: list[EstimateFlag] = []

    # From the schedule structure: unclassified items, empty direct activities, qty and rate-outlier.
    for item in schedule.items:
        if item.category not in VALID_CATEGORIES:
            flags.append(EstimateFlag(kind="unclassified_item", item_id=item.item_id,
                                      message=f"category {item.category!r} is neither direct nor indirect"))
        if item.category == "direct" and not item.lines:
            flags.append(EstimateFlag(kind="empty_activity", item_id=item.item_id,
                                      message="direct activity has no resource lines"))
        for line in item.lines:
            if line.qty <= 0:
                flags.append(EstimateFlag(kind="zero_or_negative_qty", item_id=item.item_id,
                                          message=f"resource {line.resource_ref or line.description!r} has qty {line.qty}"))
            if line.inline_rate is not None and line.resource_ref:
                row = idx.get(line.resource_ref)
                if row is not None and row.rate > 0:
                    dev = abs(line.inline_rate - row.rate) / row.rate
                    if dev > RATE_OUTLIER_BAND:
                        flags.append(EstimateFlag(
                            kind="rate_outlier", item_id=item.item_id,
                            message=(f"inline rate {line.inline_rate} for {line.resource_ref} deviates "
                                     f"{dev*100:.0f}% from CSV rate {row.rate} (benchmark only)"),
                        ))

    # From the costed lines: any line that resolved no rate.
    for act in activities:
        for line in act.lines:
            if line.rate_source == "missing":
                flags.append(EstimateFlag(kind="missing_rate", item_id=act.item_id,
                                          message=f"no rate for {line.resource_ref or line.description!r}; costed as 0"))
    return flags
