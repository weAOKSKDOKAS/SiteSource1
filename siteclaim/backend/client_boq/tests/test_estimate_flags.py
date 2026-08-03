"""Rules matrix for the five s05 validation flags — a triggering and a non-triggering case each."""

from __future__ import annotations

from client_boq.estimate import s02_schedule, s03_cost_buildup, s05_validate
from client_boq.models import EstimateSchedule, ResourceLine, ScheduleItem
from client_boq.rates import load_rates


def _flag_kinds(*items: ScheduleItem) -> set[str]:
    rates = load_rates()
    norm = s02_schedule.normalize_schedule(EstimateSchedule(duration_weeks=10, items=list(items)))
    activities = s03_cost_buildup.build_cost(norm, rates)
    return {f.kind for f in s05_validate.validate(norm, activities, rates)}


def test_missing_rate() -> None:
    trig = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="NOPE", qty=10)])
    ok = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="MAT-C40", qty=10)])
    assert "missing_rate" in _flag_kinds(trig)
    assert "missing_rate" not in _flag_kinds(ok)


def test_zero_or_negative_qty() -> None:
    trig = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="MAT-C40", qty=0)])
    ok = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="MAT-C40", qty=5)])
    assert "zero_or_negative_qty" in _flag_kinds(trig)
    assert "zero_or_negative_qty" not in _flag_kinds(ok)


def test_empty_activity() -> None:
    trig = ScheduleItem(category="direct", lines=[])
    ok = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="MAT-C40", qty=1)])
    assert "empty_activity" in _flag_kinds(trig)
    assert "empty_activity" not in _flag_kinds(ok)


def test_rate_outlier() -> None:
    # PLT-CRANE CSV rate = 12,500. Inline 25,000 deviates 100% (> ±50%) → flag; 13,000 is ~4% → no flag.
    trig = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="PLT-CRANE", inline_rate=25000, qty=1)])
    ok = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="PLT-CRANE", inline_rate=13000, qty=1)])
    assert "rate_outlier" in _flag_kinds(trig)
    assert "rate_outlier" not in _flag_kinds(ok)


def test_unclassified_item() -> None:
    trig = ScheduleItem(category="overhead")               # neither direct nor indirect
    ok = ScheduleItem(category="direct", lines=[ResourceLine(resource_ref="MAT-C40", qty=1)])
    assert "unclassified_item" in _flag_kinds(trig)
    assert "unclassified_item" not in _flag_kinds(ok)
