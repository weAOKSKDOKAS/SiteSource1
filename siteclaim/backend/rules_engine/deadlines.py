"""Deadline arithmetic for SOPO (Layer 1, deterministic — NO LLM).

Computes the statutory clock for a claim from its reference / service dates using
the constants in :mod:`rules_engine.sopo_config`. Calendar-day windows (e.g. the
s.20 payment-response period) are added with calendar arithmetic; "business days
remaining" is counted in working days honoring weekends + HK general holidays
(``sopo_config.PUBLIC_HOLIDAYS`` — SOURCED, 2026 gazette).

No statutory number is hard-coded here; every value is imported from config.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from schemas.models import Deadline, DeadlineSet, ExtractedFacts

from . import business_days, sopo_config


def hk_public_holidays() -> set[date]:
    """HK general holidays from config as ``date`` objects.

    Source: ``sopo_config.PUBLIC_HOLIDAYS`` (2026 HK General Holidays — SOURCED,
    gazette 16 May 2025). Note: only 2026 is currently loaded.
    """
    return {date.fromisoformat(s) for s in sopo_config.PUBLIC_HOLIDAYS}


def business_days_between(start: date, end: date) -> int:
    """Working days from ``start`` (exclusive) to ``end``, honoring weekends + HK holidays.

    Positive when ``end`` is after ``start``, negative when before, ``0`` when
    equal. Uses the adjudication working-day definition (Sat + Sun excluded).
    """
    return business_days.working_days_between(start, end, holidays=hk_public_holidays())


def _deadline(name: str, due: date, today: date, sopo_reference: str) -> Deadline:
    return Deadline(
        name=name,
        due_date=due,
        business_days_remaining=business_days_between(today, due),
        sopo_reference=sopo_reference,
    )


def compute_deadlines(facts: ExtractedFacts, today: date) -> DeadlineSet:
    """Compute every live statutory deadline for the claim, relative to ``today``.

    Anchored on the claim's service date (falling back to the reference date).
    Returns an empty set if neither is known.
    """
    served = facts.claim_served_date.value or facts.reference_date.value
    if served is None:
        return DeadlineSet(deadlines=[], computed_from=None)

    deadlines: list[Deadline] = []

    # Payment response window — s.20 (calendar days).
    resp_due = business_days.add_calendar_days(served, sopo_config.PAYMENT_RESPONSE_DAYS)
    deadlines.append(_deadline("payment_response_due", resp_due, today, "SOPO s.20"))

    # Payment of the (admitted/claimed) amount — calendar days.
    pay_due = business_days.add_calendar_days(served, sopo_config.MAX_PAYMENT_DEADLINE_DAYS)
    deadlines.append(_deadline("payment_due", pay_due, today, "SOPO Cap.652 (payment deadline)"))

    # Adjudication initiation — s.24 (calendar days) from when the payment dispute
    # arises. Earliest that is the close of the response window, unless a served
    # response actively disputes the claim, in which case the dispute arises then.
    disputes = facts.payment_response.disputes_claim.value
    resp_served_date = facts.payment_response.date_served.value
    if facts.payment_response.served.value and disputes and resp_served_date is not None:
        dispute_date = resp_served_date
    else:
        dispute_date = resp_due
    adj_due = business_days.add_calendar_days(dispute_date, sopo_config.ADJUDICATION_INIT_DAYS)
    deadlines.append(_deadline("adjudication_init_due", adj_due, today, "SOPO s.24"))

    return DeadlineSet(deadlines=deadlines, computed_from=served)


@dataclass(frozen=True)
class DeadlineClock:
    """A read of the deadline 'clock' relative to a given day."""

    today: date
    nearest: Optional[Deadline]  # soonest deadline still in the future (or None)
    breached: list[Deadline]  # deadlines whose due date has already passed

    @property
    def any_breached(self) -> bool:
        """True if any deadline is already past its due date."""
        return bool(self.breached)


def clock(deadline_set: DeadlineSet, today: date) -> DeadlineClock:
    """Summarise a :class:`DeadlineSet`: the nearest upcoming deadline and any breaches."""
    breached = [d for d in deadline_set.deadlines if d.due_date < today]
    upcoming = [d for d in deadline_set.deadlines if d.due_date >= today]
    nearest = min(upcoming, key=lambda d: d.due_date) if upcoming else None
    return DeadlineClock(today=today, nearest=nearest, breached=breached)
