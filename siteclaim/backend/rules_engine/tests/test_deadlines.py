"""Spec for the SOPO deadline clock."""

from datetime import date

from rules_engine import sopo_config
from rules_engine.deadlines import business_days_between, clock, compute_deadlines
from rules_engine.tests._helpers import by_name, ff


def test_business_days_between_excludes_weekends():
    # Fri 2026-03-06 -> Mon 2026-03-09 spans a weekend: exactly 1 working day.
    assert business_days_between(date(2026, 3, 6), date(2026, 3, 9)) == 1


def test_business_days_between_excludes_a_hk_public_holiday():
    # Thu 2026-01-01 (New Year) is configured; Wed 12-31 -> Fri 01-02 skips it.
    assert "2026-01-01" in sopo_config.PUBLIC_HOLIDAYS
    assert business_days_between(date(2025, 12, 31), date(2026, 1, 2)) == 1


def test_business_days_between_excludes_a_2026_general_holiday():
    # Tuen Ng 2026-06-19 (Fri) is a gazetted general holiday: Thu 06-18 -> Mon 06-22
    # crosses the holiday + weekend, leaving exactly 1 working day (Mon).
    assert "2026-06-19" in sopo_config.PUBLIC_HOLIDAYS
    assert business_days_between(date(2026, 6, 18), date(2026, 6, 22)) == 1


def test_the_payment_response_window_is_30_calendar_days_after_service(compliant_facts, today):
    ds = compute_deadlines(compliant_facts, today)
    d = by_name(ds.deadlines, "payment_response_due")
    assert d.due_date == date(2026, 4, 1)  # 2026-03-02 + 30 calendar days (s.20)
    assert d.sopo_reference == "SOPO s.20"
    assert d.business_days_remaining > 0


def test_deadlines_fall_back_to_the_reference_date_without_a_service_date(compliant_facts, today):
    compliant_facts.claim_served_date = ff(None)
    ds = compute_deadlines(compliant_facts, today)
    assert ds.computed_from == date(2026, 2, 28)


def test_the_clock_reports_the_nearest_upcoming_deadline(compliant_facts, today):
    c = clock(compute_deadlines(compliant_facts, today), today)
    assert c.nearest.name == "payment_response_due"
    assert not c.any_breached


def test_a_breached_response_window_is_detected(compliant_facts):
    today = date(2026, 3, 2)
    compliant_facts.claim_served_date = ff(date(2026, 1, 1))  # served long ago
    ds = compute_deadlines(compliant_facts, today)
    d = by_name(ds.deadlines, "payment_response_due")
    assert d.due_date < today and d.business_days_remaining < 0
    assert clock(ds, today).any_breached
