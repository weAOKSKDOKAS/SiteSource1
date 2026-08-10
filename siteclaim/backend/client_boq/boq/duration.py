"""BOQ — how long the drilling takes, day by day.

Bucket: **Deterministic**. No model, no judgement. The *inputs* are an estimator's judgement — how fast
his crews actually drill this ground — and this module does nothing but carry them through arithmetic.

WHY A SIMULATION AND NOT A DIVISION
-----------------------------------
``2,300 m ÷ 20 m per day`` is wrong twice over, and a real estimator's workbook models both:

1. **A day does not end when the soil does.** When soil finishes at 11am the rig starts rock after
   lunch, and that part-day belongs to rock. Losing it overstates the programme and understates every
   rate that divides by it.
2. **Whole days are paid for.** ``total_days`` rounds up; the rounding is charged to rock.

DEPTH DECAY DEFAULTS TO ZERO, AND THE MEASUREMENT IS WHY
--------------------------------------------------------
The knob below stays — an estimator may deliberately pad a hole he expects to fight — but it defaults
to **0.0**, because the data says the assumption it encoded has the wrong sign. Across **205 real
drilling-days** from 30 holes' daily logs, the rate does not fall as a hole gets deeper:

    0–20 m   4.42 m/day
    20–40 m  5.32 m/day   ← 20% FASTER, not slower
    40 m+    3.41 m/day

and per-hole, over the 21 holes with five or more drilling days, the correlation between depth and
log-rate is **+0.11 on average and positive in 13 of 21**. The 40 m+ slowdown is a *rock* effect: the
deep records are rock-socket drilling in a 74%-rock project, and across all 95 holes
``corr(rate, rock %) = −0.428`` against ``corr(rate, depth) = +0.196`` — a regression holding rock
constant gives a *positive* depth coefficient. Rock fraction is the driver, the band table already
captures it (:mod:`client_boq.boq.empirical`), and a decay curve on top double-counts it.

The old default of 5% per 20 m was not a small error. Compounded over a 600 m group it left the rig
at ``0.95^30 ≈ 21%`` of its surface rate: a 600 m single-rig group in pure soil at 20 m/day took
**69 days instead of 30**. Every rate divided by those days.

A NON-ZERO DECAY IS PER HOLE
----------------------------
``simulate`` models ONE hole: ``cumulative`` is depth down *that* hole, so the decay resets when the
rig moves. It never meant "metres this group has drilled". Feeding it a group's pooled total was the
second half of the error — see :meth:`client_boq.boq.groups.HoleGroup.duration`.

THE TWO DIFFERENT "ROCK DAYS", WHICH ARE NOT THE SAME NUMBER
------------------------------------------------------------
The reference workbook keeps both, and the distinction is deliberate:

* ``rock_days_actual`` — the day-fractions the rig genuinely spends turning in rock. What a programme
  wants.
* ``rock_days_charged`` — ``total_days − soil_days``. What the *rate* is built on.

They differ because ``total_days`` is rounded **up** to a whole day: you pay the crew for the whole of
the last day whether or not the hole finished at 3pm. Charging the rounding to rock rather than
splitting it is the workbook's convention and it is reproduced exactly, because a rate that disagrees
with the estimator's own spreadsheet is a rate he will not use.

On the reference figures — 60 m soil, 72 m rock, 20 and 10 m/day, 5% per 20 m — that is
``soil 3.1108 d``, ``rock actual 7.5958 d``, ``total 11 d``, ``rock charged 7.8892 d``. Those
figures are the workbook's, and the 5% in them is the workbook's; they are kept as the arithmetic
check on the decay path, not as a recommendation of it.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

# Depth band over which output decays. 20 m because the Method of Measurement stages drilling in 20 m
# lengths from existing ground level (SMM S02 ¶2.11A, ¶2.12 Group V).
DEPTH_BAND_M = 20.0

# A guard, not a business rule: the loop must terminate even if someone enters an output of nothing.
MAX_DAYS = 2000


class DrillDay(BaseModel):
    """One day of the simulation, kept so the estimator can read the programme back out of the rate."""

    day: int = 0
    soil_rate: float = 0.0          # what the rig could do in soil today, after decay
    soil_drilled: float = 0.0
    day_fraction_left: float = 1.0  # what is left of the day once soil stops
    rock_rate: float = 0.0
    rock_drilled: float = 0.0
    cum_soil: float = 0.0
    cum_rock: float = 0.0


class DrillDuration(BaseModel):
    """The programme, and the two day-counts a rate can be divided by."""

    soil_m: float = 0.0
    rock_m: float = 0.0
    days: list[DrillDay] = Field(default_factory=list)

    soil_days: float = 0.0          # fractional; the day soil finishes counts only its used part
    rock_days_actual: float = 0.0   # fractional; what the rig really spends in rock
    total_days: int = 0             # ROUNDUP(soil_days + rock_days_actual) — you pay whole days
    rock_days_charged: float = 0.0  # total_days − soil_days; the divisor the rock rate uses

    soil_complete_day: Optional[int] = None
    rock_complete_day: Optional[int] = None
    unfinished: bool = False        # ran out of days: an output of zero, or an absurd depth

    def days_for(self, material: str) -> float:
        """The day count a rate for this material is built on."""
        if material == "soil":
            return self.soil_days
        if material == "rock":
            return self.rock_days_charged
        raise ValueError(f"unknown material {material!r}; expected 'soil' or 'rock'")


def output_at(initial: float, cumulative: float, decay: float,
              band: float = DEPTH_BAND_M) -> float:
    """Output per day once ``cumulative`` metres are already down **this hole**.

    ``initial × (1 − decay) ^ floor(cumulative / band)`` — a step, not a curve, because the workbook
    steps it and because the measurement rules band depth the same way.

    At ``decay = 0`` this is the identity, which is the default and what the data supports.
    """
    if initial <= 0:
        return 0.0
    return initial * (1.0 - decay) ** int(cumulative // band)


def simulate(soil_m: float, rock_m: float, *, soil_output: float, rock_output: float,
             decay: float = 0.0, band: float = DEPTH_BAND_M) -> DrillDuration:
    """Drill ONE hole — ``soil_m`` then ``rock_m`` — a day at a time.

    Soil is taken first each day and rock gets whatever is left of that day — which is what actually
    happens down a hole, and what the reference workbook models.

    ``decay`` defaults to 0.0: measured ≈ 0 across 205 real drilling-days, and rock fraction is the
    driver the band table already carries. See the module docstring. A caller that wants padding
    passes it deliberately, and gets it applied down THIS hole — the depth is this hole's depth.
    """
    if soil_m < 0 or rock_m < 0:
        raise ValueError("depths cannot be negative")

    result = DrillDuration(soil_m=soil_m, rock_m=rock_m)
    cum_soil = cum_rock = 0.0
    soil_days = rock_days = 0.0

    for day in range(1, MAX_DAYS + 1):
        if cum_soil >= soil_m and cum_rock >= rock_m:
            break

        soil_rate = 0.0 if cum_soil >= soil_m else output_at(soil_output, cum_soil, decay, band)
        soil_today = min(soil_rate, soil_m - cum_soil) if soil_rate > 0 else 0.0
        # The part of the day soil did not use. With no soil left there is a whole day for rock.
        fraction_left = 1.0 if soil_rate <= 0 else 1.0 - soil_today / soil_rate

        rock_rate = 0.0 if cum_rock >= rock_m else output_at(rock_output, cum_rock, decay, band)
        rock_today = min(fraction_left * rock_rate, rock_m - cum_rock) if rock_rate > 0 else 0.0

        if soil_today <= 0 and rock_today <= 0:
            # Nothing advanced: an output of zero. Stop rather than spin, and say so.
            result.unfinished = True
            break

        cum_soil += soil_today
        cum_rock += rock_today
        soil_days += (soil_today / soil_rate) if soil_rate > 0 else 0.0
        rock_days += (rock_today / rock_rate) if rock_rate > 0 else 0.0

        result.days.append(DrillDay(
            day=day, soil_rate=soil_rate, soil_drilled=soil_today,
            day_fraction_left=fraction_left, rock_rate=rock_rate, rock_drilled=rock_today,
            cum_soil=cum_soil, cum_rock=cum_rock,
        ))
        if result.soil_complete_day is None and cum_soil >= soil_m and soil_m > 0:
            result.soil_complete_day = day
        if result.rock_complete_day is None and cum_rock >= rock_m and rock_m > 0:
            result.rock_complete_day = day
    else:
        result.unfinished = True

    result.soil_days = soil_days
    result.rock_days_actual = rock_days
    # Whole days are paid for whether or not the hole finished at 3pm.
    result.total_days = math.ceil(soil_days + rock_days) if (soil_days + rock_days) > 0 else 0
    result.rock_days_charged = max(0.0, result.total_days - soil_days)
    return result
