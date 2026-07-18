"""Orchestrate the ESTIMATE deterministic spine: s02 → s03 → s04 → s05 + totals/margin.

Pure deterministic assembly (no AI in this slice). Threads the structured schedule through
normalisation, cost build-up, indirects (which need the direct subtotal), and validation, then
computes totals and the margin readout, and persists to the ``client_boq_*`` tables + the artifact.

Margin: ``margin_pct`` is a required run input (the human states it). The math is cost → price →
margin amount; there is NO profitable/not verdict and no threshold flag on margin — the readout is
presented and the human decides.

Idempotent: the same schedule + margin yields byte-identical totals (all rounding is the single
``money`` half-to-even at 2 dp).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from client_boq import store
from client_boq.estimate import money, s02_schedule, s03_cost_buildup, s04_indirects, s05_validate
from client_boq.rates import load_rates
from client_boq.models import Estimate, EstimateSchedule, EstimateTotals
from pipeline.workspace import Workspace

ProgressCB = Callable[[str], None]
DEMO_MARGIN_PCT = 15.0  # the DEMO fixture margin (the human enters this in a live run)

# backend/client_boq/estimate/run.py -> parents[2] == backend/
_DEMO_SCHEDULE_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "cases" / "client_boq" / "estimate_schedule.json"
)


def load_demo_schedule() -> EstimateSchedule:
    """The DEMO pricing schedule (offline fixture)."""
    return EstimateSchedule.model_validate_json(_DEMO_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))


def assemble_estimate(set_id: str, margin_pct: float, schedule: EstimateSchedule) -> Estimate:
    """Run the spine and compute totals/margin. Pure — no persistence, no I/O — so it is trivially
    unit-testable and reused by the persisting ``run_estimate``."""
    rates = load_rates()
    norm = s02_schedule.normalize_schedule(schedule)
    activities = s03_cost_buildup.build_cost(norm, rates)
    total_direct = s03_cost_buildup.direct_total(activities)
    indirects = s04_indirects.build_indirects(norm, total_direct)
    total_indirect = s04_indirects.indirect_total(indirects)
    flags = s05_validate.validate(norm, activities, rates)
    unclassified = [i for i in norm.items if i.category not in s02_schedule.VALID_CATEGORIES]

    total_cost = money(total_direct + total_indirect)
    price = money(total_cost * (1 + margin_pct / 100.0))
    margin_amount = money(price - total_cost)
    totals = EstimateTotals(
        total_direct=total_direct, total_indirect=total_indirect, total_cost=total_cost,
        margin_pct=margin_pct, price=price, margin_amount=margin_amount,
    )
    return Estimate(
        set_id=set_id, duration_weeks=norm.duration_weeks, activities=activities,
        indirects=indirects, unclassified=unclassified, flags=flags, totals=totals,
    )


def run_estimate(
    set_id: str, margin_pct: float, schedule: EstimateSchedule, *,
    progress_cb: Optional[ProgressCB] = None,
) -> Estimate:
    """Assemble the estimate and persist it (tables + artifact). Returns the estimate."""
    def step(stage: str) -> None:
        if progress_cb:
            progress_cb(stage)

    step("costing")
    estimate = assemble_estimate(set_id, margin_pct, schedule)

    step("persisting")
    ws = Workspace()
    conn = store.get_conn()
    try:
        store.save_estimate(conn, estimate)
        store.save_estimate_artifact(ws, set_id, estimate)
    finally:
        conn.close()
    return estimate
