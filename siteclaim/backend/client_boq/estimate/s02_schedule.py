"""ESTIMATE stage 02 — pricing-schedule structure.

Bucket (mapping doc estimate tasks 3/4): **Deterministic structure**. In this slice the pricing
schedule arrives already structured (request payload in live, fixture in DEMO); s02 validates and
normalises it — assigns stable item IDs and normalises the declared ``category`` — without guessing.
An unknown category is left as-is for s05 to flag as ``unclassified_item`` (never silently coerced to
direct/indirect).

SEAM for slice 2: the full design has the AI propose the activity breakdown *before* this point. That
AI proposal half is slice 2 and will produce exactly this ``EstimateSchedule`` shape, so it slots in
front of ``normalize_schedule`` without reshaping storage or any downstream stage.

Signature change from the scaffold: ``normalize_schedule(EstimateSchedule) -> EstimateSchedule``
(was ``build_schedule(ScopeReviewResult) -> PricingSchedule``), because the schedule is now a
structured input rather than an AI draft.
"""

from __future__ import annotations

from client_boq.models import EstimateSchedule, ScheduleItem

VALID_CATEGORIES = {"direct", "indirect"}


def normalize_schedule(schedule: EstimateSchedule) -> EstimateSchedule:
    """Return a normalised copy: every item has a stable ``item_id`` and a trimmed lowercase
    ``category``. Deterministic — same input yields the same IDs (positional ``I1``, ``I2``, … for
    blanks). Structural validity is already enforced by pydantic at the request boundary."""
    items: list[ScheduleItem] = []
    for i, item in enumerate(schedule.items, start=1):
        item_id = (item.item_id or "").strip() or f"I{i}"
        category = (item.category or "").strip().lower()
        items.append(item.model_copy(update={"item_id": item_id, "category": category}))
    return schedule.model_copy(update={"items": items})
