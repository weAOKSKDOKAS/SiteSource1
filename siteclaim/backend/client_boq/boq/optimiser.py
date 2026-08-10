"""BOQ — the rig count as a COMPARISON, not a single answer.

Bucket: **Deterministic.** No model call anywhere. `programme.derive()` answers "how many rigs fit
the contract period" — a floor, not a choice. This module prices every rig count and shows the
curve, because the count is a commercial decision with a real trade-off in it:

    cost(n) = n·rig_rate·duration(n)                    ← CONSTANT: n × (work_days/n) = work_days
            + ceil(n / gft_ratio)·gft_cost·duration(n)   ← the GFT: steps UP with n, runs shorter
            + site_teams·team_cost·duration(n)           ← the SITE team: count fixed, falls with n
            + mob·n                                       ← rises with n, one mobilisation per rig
            + prelims_per_day·calendar(n)                 ← falls with n: the office closes sooner

    duration(n) = work_days / n                           ← the banded P50, split across n rigs

The first term is why "more rigs cost more" is wrong: total rig-days do not move with n. What moves
is supervision per day of contract, mobilisations, and how long the time-related preliminaries run.
The result is U-shaped, and the profit-maximising n is the cost-minimising one — the tendered
amount does not change with the rig count.

WHAT IS DELIBERATELY EXCLUDED from the comparison: costs constant across n (standing time is a
share of work-days; materials follow quantities). They belong in the estimate, not in a comparison
whose only job is the difference between rig counts — but the constant rig-day total IS included,
so each option's figure reads as real money rather than a delta.

The proposal is a PROPOSAL. The assumptions register already carries the rig row ("Derived, not
assumed"); the estimator confirms or overrides, and the confirmed count is theirs.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.model import DRIVER_FIXED, CostingModel, days_in
from client_boq.boq.programme import Programme

N_MAX = 12


class RigOption(BaseModel):
    """One rig count, priced."""

    n: int
    duration_work_days: float = 0.0
    duration_calendar_days: float = 0.0
    gfts: int = 0
    site_teams: float = 0.0
    rig_cost: float = 0.0               # constant across n — shown so totals are real money
    gft_cost: float = 0.0
    site_team_cost: float = 0.0
    mob_cost: float = 0.0
    prelim_cost: float = 0.0
    total_cost: float = 0.0
    feasible: bool = True               # fits inside the contract period
    proposed: bool = False
    note: str = ""


class RigCurve(BaseModel):
    """Every option, the proposal, and what the comparison could not include."""

    options: list[RigOption] = Field(default_factory=list)
    proposal_n: Optional[int] = None
    floor_n: int = 0                    # what derive() already answered: the fewest that FIT
    gft_ratio: float = 6.0
    site_teams: float = 0.0
    mob_per_rig: float = 0.0
    prelims_per_day: float = 0.0
    notes: list[str] = Field(default_factory=list)

    def proposed(self) -> Optional[RigOption]:
        return next((o for o in self.options if o.proposed), None)


def mob_cost_per_rig(model: CostingModel) -> tuple[float, str]:
    """One spread's mobilisation, from the model's own fixed rows. ``(cost, note)``.

    Read from every ``DRIVER_FIXED`` basis row's components — the same numbers the build-up prices
    — never typed here. A model with no fixed row mobilises for $0 and the note says so, because a
    curve that quietly assumed a mobilisation figure would be inventing the thing it exists to
    compare.
    """
    total = 0.0
    found = False
    for row in model.basis_rows:
        if row.driver != DRIVER_FIXED:
            continue
        for component in row.components:
            found = True
            total += model.value(component.rate_key) * model.value(component.qty_key, 1.0)
    if not found:
        return 0.0, ("no fixed-cost basis row in the model, so mobilisation enters this "
                     "comparison at $0 — the mob·n term is missing until one exists")
    return total, ""


def prelims_per_day(model: CostingModel) -> tuple[float, str]:
    """The time-related preliminaries' cost per CALENDAR day, from the model's prelim resources.

    Only resources whose unit is a duration convert ($/month, $/week); a per-count prelim (prints)
    does not run with time and stays out. Zero-rated resources contribute zero — the model marks
    those loudly elsewhere; here they simply do not move the comparison yet.
    """
    total = 0.0
    unrated = 0
    for resource in model.prelims():
        per_days = days_in((resource.unit or "").removeprefix("$/"))
        if not per_days:
            continue
        if resource.rate <= 0:
            unrated += 1
            continue
        total += resource.multiplier * resource.rate / per_days
    note = (f"{unrated} time-related preliminary resource(s) have no rate yet, so the "
            f"prelims·duration term is understated until they are entered" if unrated else "")
    return total, note


def optimise(programme: Programme, model: CostingModel, *, n_max: int = N_MAX) -> RigCurve:
    """Price every rig count 1..``n_max`` and propose the cheapest FEASIBLE one.

    Feasible means the duration fits the contract period — the same arithmetic ``derive()`` used
    for its floor. Ties go to fewer rigs: same money, less plant on site, less to go wrong.
    """
    curve = RigCurve(floor_n=programme.rigs_required)
    if not programme.work_days or programme.work_days <= 0:
        curve.notes.append("no programme work-days, so there is nothing to compare")
        return curve

    gft_ratio = model.value("gft_ratio", 6.0) or 6.0
    site_teams = model.value("site_count", 1.0) * model.value("site_team_per_site", 1.0)
    rig_day = model.cost_per_rig_day()
    team_day = model.cost_per_contract_day()
    gft_day = model.cost_per_gft_day()
    calendar_ratio = model.value("calendar_to_work_day", 1.0) or 1.0
    available = programme.work_days_available_per_rig

    mob, mob_note = mob_cost_per_rig(model)
    prelim_day, prelim_note = prelims_per_day(model)
    curve.gft_ratio, curve.site_teams = gft_ratio, site_teams
    curve.mob_per_rig, curve.prelims_per_day = mob, prelim_day
    if gft_day <= 0:
        curve.notes.append(
            "the GFT has no rate, so the term that actually steps with the rig count contributes "
            "nothing to this comparison — enter the GFT day-rate before reading the curve")
    for note in (mob_note, prelim_note):
        if note:
            curve.notes.append(note)

    for n in range(1, n_max + 1):
        duration = programme.work_days / n
        calendar = duration * calendar_ratio
        gfts = math.ceil(n / gft_ratio)
        option = RigOption(
            n=n,
            duration_work_days=duration,
            duration_calendar_days=calendar,
            gfts=gfts,
            site_teams=site_teams,
            rig_cost=rig_day * programme.work_days,          # n × rig_day × (work_days/n)
            gft_cost=gfts * gft_day * duration,
            site_team_cost=site_teams * team_day * duration,
            mob_cost=mob * n,
            prelim_cost=prelim_day * calendar,
            feasible=(available > 0 and duration <= available),
        )
        option.total_cost = (option.rig_cost + option.gft_cost + option.site_team_cost
                             + option.mob_cost + option.prelim_cost)
        if not option.feasible:
            option.note = (f"{duration:,.0f} work-days per rig does not fit the "
                           f"{available:,.0f} available in the contract period")
        curve.options.append(option)

    feasible = [o for o in curve.options if o.feasible]
    if feasible:
        cheapest = min(feasible, key=lambda o: (o.total_cost, o.n))
        cheapest.proposed = True
        curve.proposal_n = cheapest.n
        if curve.proposal_n != curve.floor_n:
            curve.notes.append(
                f"the cheapest feasible count is {curve.proposal_n} rig(s), not the floor of "
                f"{curve.floor_n} that merely fits — the difference is GFT steps, the site "
                f"team's duration, mobilisations and how long the preliminaries run")
    else:
        curve.notes.append(
            f"no rig count up to {n_max} fits the contract period — the programme does not fit "
            f"the time allowed, which is a finding in its own right, not a pricing input")
    return curve
