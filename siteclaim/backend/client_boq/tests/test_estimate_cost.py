"""Hand-checkable arithmetic for the estimate spine.

Every expected total here is written as a hand-computed constant (not by re-running the same code
path), so the test is an independent check of the math. Rounding rule under test: round half-to-even
to 2 dp at each line/activity/indirect/total (see estimate/__init__.py).
"""

from __future__ import annotations

from client_boq.estimate import money, s03_cost_buildup, s04_indirects
from client_boq.estimate.run import assemble_estimate, load_demo_schedule
from client_boq.models import EstimateSchedule, ResourceLine, ScheduleItem
from client_boq.rates import load_rates


def _direct(item: ScheduleItem) -> list:
    return s03_cost_buildup.build_cost(EstimateSchedule(items=[item]), load_rates())


def test_productivity_line_math() -> None:
    # LAB-CARP = 580/hr. hours = 800 ÷ 2.5 = 320; amount = 320 × 580 = 185,600.
    act = _direct(ScheduleItem(item_id="A", category="direct",
                               lines=[ResourceLine(resource_ref="LAB-CARP", qty=800, productivity=2.5, unit="m2")]))[0]
    line = act.lines[0]
    assert line.hours == 320.0 and line.rate == 580.0 and line.rate_source == "csv"
    assert line.amount == 185_600.0 and act.activity_total == 185_600.0


def test_qty_times_rate_and_inline_override_and_missing() -> None:
    # MAT-C40 = 1150/m3 → 500 × 1150 = 575,000 (csv).
    a = _direct(ScheduleItem(item_id="A", category="direct",
                             lines=[ResourceLine(resource_ref="MAT-C40", qty=500, unit="m3")]))[0]
    assert a.lines[0].amount == 575_000.0 and a.lines[0].rate_source == "csv"
    # Inline rate wins over CSV: 25,000 × 10 = 250,000.
    b = _direct(ScheduleItem(item_id="B", category="direct",
                             lines=[ResourceLine(resource_ref="PLT-CRANE", inline_rate=25000, qty=10)]))[0]
    assert b.lines[0].rate == 25000.0 and b.lines[0].rate_source == "inline" and b.lines[0].amount == 250_000.0
    # Unknown resource → costed 0, marked missing (never guessed).
    c = _direct(ScheduleItem(item_id="C", category="direct",
                             lines=[ResourceLine(resource_ref="NOPE", qty=100)]))[0]
    assert c.lines[0].rate_source == "missing" and c.lines[0].amount == 0.0


def test_indirect_bases_hand_checked() -> None:
    sched = EstimateSchedule(duration_weeks=20, items=[
        ScheduleItem(item_id="I1", category="indirect", basis="per_week", rate=8000),
        ScheduleItem(item_id="I2", category="indirect", basis="pct_of_direct", pct=2.5),
        ScheduleItem(item_id="I3", category="indirect", basis="lump", amount=120000),
    ])
    by = {i.item_id: i.amount for i in s04_indirects.build_indirects(sched, total_direct=1_000_000)}
    assert by["I1"] == 160_000.0     # 8,000 × 20 weeks
    assert by["I2"] == 25_000.0      # 2.5% × 1,000,000
    assert by["I3"] == 120_000.0     # lump


def test_full_demo_totals_and_margin_hand_checked() -> None:
    est = assemble_estimate("t", 15.0, load_demo_schedule())
    t = est.totals
    # Directs: A1 1,340,600 + A2 4,120,000 + A3 192,000 = 5,652,600.
    assert t.total_direct == 5_652_600.0
    # Indirects: 160,000 (per_week) + 141,315 (2.5% of direct) + 120,000 (lump) = 421,315.
    assert t.total_indirect == 421_315.0
    assert t.total_cost == 6_073_915.0
    # price = cost × 1.15 = 6,985,002.25 ; margin = cost × 0.15 = 911,087.25.
    assert t.price == 6_985_002.25 and t.margin_pct == 15.0
    assert t.margin_amount == 911_087.25


def test_recompute_is_idempotent() -> None:
    sched = load_demo_schedule()
    assert assemble_estimate("t", 15.0, sched).model_dump_json() == assemble_estimate("t", 15.0, sched).model_dump_json()


def test_rounding_is_half_to_even() -> None:
    # Exactly-representable ties resolve to the even neighbour.
    assert money(0.125) == 0.12
    assert money(0.375) == 0.38
