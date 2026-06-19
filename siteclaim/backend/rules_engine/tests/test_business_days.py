"""Tests for the CALENDAR-vs-WORKING day helpers and the two working-day modes.

The distinctions guarded here are legally load-bearing (SOPO s.20 runs in
calendar days; the s.24–s.42 adjudication timetable in working days; the two
working-day definitions differ on Saturdays). Anchor dates are verified weekdays:
2026-06-19 Fri, 2026-06-20 Sat, 2026-06-21 Sun, 2026-06-22 Mon, 2026-06-23 Tue.
"""

from datetime import date

import pytest

from rules_engine import business_days as bd
from rules_engine import sopo_config

FRIDAY = date(2026, 6, 19)
SATURDAY = date(2026, 6, 20)
SUNDAY = date(2026, 6, 21)
MONDAY = date(2026, 6, 22)
TUESDAY = date(2026, 6, 23)


def test_anchor_weekdays() -> None:
    assert (FRIDAY.weekday(), SATURDAY.weekday(), SUNDAY.weekday(), MONDAY.weekday()) == (4, 5, 6, 0)


def test_add_calendar_days_includes_weekend() -> None:
    assert bd.add_calendar_days(FRIDAY, 3) == MONDAY  # Sat/Sun counted
    assert bd.add_calendar_days(FRIDAY, 0) == FRIDAY
    assert bd.add_calendar_days(MONDAY, -3) == FRIDAY


# --- adjudication mode (default): Saturdays + Sundays excluded ---------------
def test_add_working_days_adjudication_skips_weekend() -> None:
    assert bd.add_working_days(FRIDAY, 1) == MONDAY  # default mode='adjudication'
    assert bd.add_working_days(FRIDAY, 0) == FRIDAY


def test_is_working_day_adjudication() -> None:
    assert bd.is_working_day(FRIDAY) is True
    assert bd.is_working_day(SATURDAY) is False  # Saturday excluded in adjudication
    assert bd.is_working_day(SUNDAY) is False
    assert bd.is_working_day(MONDAY, holidays=[MONDAY]) is False


def test_add_working_days_skips_holiday() -> None:
    assert bd.add_working_days(FRIDAY, 1, holidays=[MONDAY]) == TUESDAY


# --- part4 mode: Saturdays COUNT, only Sundays/holidays excluded -------------
def test_part4_mode_counts_saturday() -> None:
    assert bd.is_working_day(SATURDAY, mode="part4") is True
    assert bd.is_working_day(SUNDAY, mode="part4") is False
    assert bd.add_working_days(FRIDAY, 1, mode="part4") == SATURDAY


def test_modes_diverge_on_saturday() -> None:
    # Same call, different mode -> different result. This is the load-bearing bit.
    assert bd.add_working_days(FRIDAY, 1, mode="adjudication") == MONDAY
    assert bd.add_working_days(FRIDAY, 1, mode="part4") == SATURDAY


def test_working_days_between_differs_by_mode() -> None:
    # Fri -> Mon: 1 working day under adjudication (Sat+Sun off), 2 under part4
    # (Sat counts, only Sun off).
    assert bd.working_days_between(FRIDAY, MONDAY, mode="adjudication") == 1
    assert bd.working_days_between(FRIDAY, MONDAY, mode="part4") == 2
    assert bd.working_days_between(FRIDAY, FRIDAY) == 0
    assert bd.working_days_between(MONDAY, FRIDAY) == -1


# --- weather suspension (black rainstorm / gale) excluded in both modes ------
def test_weather_suspension_skipped_adjudication() -> None:
    assert bd.add_working_days(FRIDAY, 1, weather_suspension_dates=[MONDAY]) == TUESDAY


def test_weather_suspension_skipped_part4() -> None:
    # Saturday would count under part4, but a weather suspension on it rolls to Monday.
    assert bd.add_working_days(FRIDAY, 1, mode="part4", weather_suspension_dates=[SATURDAY]) == MONDAY


def test_add_working_days_rejects_negative() -> None:
    with pytest.raises(ValueError):
        bd.add_working_days(FRIDAY, -1)


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError):
        bd.add_working_days(FRIDAY, 1, mode="bogus")  # type: ignore[arg-type]


def test_part4_mode_excludes_a_saturday_general_holiday() -> None:
    # This is exactly why Saturday general holidays are kept in the SOURCED list:
    # part4 normally counts Saturdays, so a Saturday that IS a general holiday must
    # still be excluded when the gazetted holidays are supplied.
    holidays = {date.fromisoformat(s) for s in sopo_config.PUBLIC_HOLIDAYS}
    sat_holiday = date(2026, 4, 4)  # "day following Good Friday" — a Saturday
    assert sat_holiday in holidays and sat_holiday.weekday() == 5
    assert bd.is_working_day(sat_holiday, holidays=holidays, mode="part4") is False
    # Control: a non-holiday Saturday DOES count as a working day under part4.
    plain_saturday = date(2026, 4, 11)
    assert plain_saturday.weekday() == 5 and plain_saturday not in holidays
    assert bd.is_working_day(plain_saturday, holidays=holidays, mode="part4") is True
