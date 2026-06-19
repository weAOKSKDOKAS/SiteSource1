"""Day-count helpers for SOPO deadline arithmetic (Layer 1, deterministic).

The Construction Industry Security of Payment Ordinance (Cap. 652) mixes
**CALENDAR days** and **WORKING days**, and the distinction is legally
load-bearing (e.g. s.20 payment-response runs in calendar days; the s.24–s.42
adjudication timetable runs in working days). Pair ``*_DAYS`` constants with
:func:`add_calendar_days` and ``*_WORKING_DAYS`` constants with
:func:`add_working_days`.

The Ordinance further uses **two different working-day definitions**, selected by
the ``mode`` argument:

* ``mode="adjudication"`` (default; CIC FAQ Q36) — excludes Saturdays, general
  holidays (which include Sundays) and black rainstorm / gale-warning days.
* ``mode="part4"`` (CIC FAQ Q54) — excludes general holidays and black
  rainstorm/gale days only; **Saturdays count** as working days. Used for the
  Part 4 suspension-notice period.

``weather_suspension_dates`` (black rainstorm / gale-warning days) is injectable
and defaults to empty. Those warnings are issued dynamically in real time, so a
production system must feed in the actual suspension dates; treating it as empty
is a known demo limitation. General holidays come in via ``holidays`` —
see ``sopo_config.PUBLIC_HOLIDAYS`` (2026 gazette, SOURCED).
"""

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Literal

from . import sopo_config

WorkingDayMode = Literal["adjudication", "part4"]


def _excluded_weekdays(mode: WorkingDayMode) -> tuple[int, ...]:
    """Return the ``date.weekday()`` indices that are non-working under ``mode``.

    - ``"adjudication"`` (CIC FAQ Q36): Saturdays AND Sundays are excluded
      (Sundays fall within 'general holidays'); uses ``sopo_config.WEEKEND_DAYS``.
    - ``"part4"`` (CIC FAQ Q54): only Sundays recur as non-working; Saturdays
      count as working days.
    """
    if mode == "adjudication":
        return tuple(sopo_config.WEEKEND_DAYS)
    if mode == "part4":
        return (6,)  # Sunday only; Saturdays count under the Part 4 definition
    raise ValueError(f"unknown working-day mode: {mode!r}")


def add_calendar_days(start: date, n: int) -> date:
    """Return ``start`` plus ``n`` CALENDAR days (weekends and holidays included).

    ``n`` may be negative to move backwards.
    """
    return start + timedelta(days=n)


def is_working_day(
    day: date,
    holidays: Iterable[date] = (),
    *,
    mode: WorkingDayMode = "adjudication",
    weather_suspension_dates: Iterable[date] = (),
) -> bool:
    """True if ``day`` is a working day under ``mode``.

    Excludes the mode's recurring non-working weekdays, ``holidays`` (HK
    general/public holidays), and ``weather_suspension_dates`` (black rainstorm /
    gale-warning days) — the Ordinance treats the latter as non-working in both
    modes.
    """
    if day.weekday() in _excluded_weekdays(mode):
        return False
    if day in set(holidays):
        return False
    if day in set(weather_suspension_dates):
        return False
    return True


def add_working_days(
    start: date,
    n: int,
    holidays: Iterable[date] = (),
    *,
    mode: WorkingDayMode = "adjudication",
    weather_suspension_dates: Iterable[date] = (),
) -> date:
    """Return the date ``n`` WORKING days after ``start`` under ``mode``.

    ``n`` must be non-negative; ``n == 0`` returns ``start`` unchanged (even if
    ``start`` is itself non-working). See :func:`is_working_day` for what counts.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    holiday_set = set(holidays)
    weather_set = set(weather_suspension_dates)
    excluded = _excluded_weekdays(mode)
    current = start
    counted = 0
    while counted < n:
        current += timedelta(days=1)
        if current.weekday() not in excluded and current not in holiday_set and current not in weather_set:
            counted += 1
    return current


def working_days_between(
    start: date,
    end: date,
    holidays: Iterable[date] = (),
    *,
    mode: WorkingDayMode = "adjudication",
    weather_suspension_dates: Iterable[date] = (),
) -> int:
    """Count WORKING days from ``start`` to ``end`` (exclusive of ``start``).

    Positive when ``end`` is after ``start``, ``0`` when equal, negative when
    before. Useful for a 'business days remaining until a deadline' figure.
    """
    if end == start:
        return 0
    step = 1 if end > start else -1
    holiday_set = set(holidays)
    weather_set = set(weather_suspension_dates)
    excluded = _excluded_weekdays(mode)
    count = 0
    current = start
    while current != end:
        current += timedelta(days=step)
        if current.weekday() not in excluded and current not in holiday_set and current not in weather_set:
            count += step
    return count


__all__ = [
    "WorkingDayMode",
    "add_calendar_days",
    "is_working_day",
    "add_working_days",
    "working_days_between",
]
