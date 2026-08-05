"""BOQ — the site's own rules, as the general-notes drawing states them.

Bucket: **Deterministic**. These are transcribed constants, not judgements: every one is printed on
drawing GI/100 (*"General notes and details of ground investigation, testing and monitoring works"*),
and they are what turn a station schedule into bill quantities.

The defaults below are the reference contract's, verbatim in intent:

* **Field sampling** — *"MAZIER samples … shall be taken at 2.0m intervals in the drillholes"*; U76 and
  piston likewise at 2.0 m; an SPT immediately below each successful Mazier.
* **Inspection pit** — *"an inspection pit of 2m shall be carried out at the drillhole locations prior
  to the commencement of the drilling works"*, sampled every 0.5 m.
* **Trial pits** — *"in size of 1.5m width x 1.5m length and shall be terminated at 3m below the
  existing ground level"*, with block and large disturbed samples *"at 1m intervals, starting from
  0.5m below the existing ground level"* → three per pit.
* **Termination** — 5.0 m of continuous Grade III or better bedrock at ≥85% TCR per 1.0 m core, **or**
  80 m, **or** as instructed. With a sting from PS 7.45D: over-drilling *"will be at the expense of the
  Contractor"*.
* **Instruments** — *"Up to two standpipes/piezometers shall be installed in each drillhole"*, which is
  why 115 instruments sit in 91 holes. Monitoring runs *"at least 12 months"*.
* **Table 1** — tentative test numbers: 52 permeability, 30 pressuremeter, 8 acoustic televiewer.
  *The bill says 54, 31 and 8.* That divergence is real, and :mod:`client_boq.boq.derive` reports it.

They are defaults, not law: another tender will print different numbers on the same drawing, so every
one is an input.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

# Monitoring is specified in months but measured in instrument-weeks. The reference bill converts at
# 365 days ÷ 7 — 47 standpipes → 2,451 nr-wk, 68 piezometers → 3,546, 115 AGMD → 5,996, all exact.
DAYS_PER_YEAR = 365.0
DAYS_PER_WEEK = 7.0


class SamplingRules(BaseModel):
    """How often something is taken out of a hole."""

    mazier_interval_m: float = 2.0
    u76_interval_m: float = 2.0
    piston_interval_m: float = 2.0
    spt_follows_mazier: bool = True         # one SPT immediately below each successful Mazier

    def count_at_interval(self, length_m: float, interval_m: float) -> int:
        if interval_m <= 0 or length_m <= 0:
            return 0
        return math.floor(length_m / interval_m)


class PitRules(BaseModel):
    """Trial pits and the inspection pit that starts every drillhole."""

    trial_width_m: float = 1.5
    trial_length_m: float = 1.5
    trial_depth_m: float = 3.0
    trial_sample_start_m: float = 0.5       # first sample this far below existing ground
    trial_sample_interval_m: float = 1.0

    inspection_depth_m: float = 2.0         # "an inspection pit of 2m … prior to drilling"
    inspection_plan_m2: float = 0.25        # the specified minimum plan area
    inspection_allowance_m3: float = 0.5    # what one is actually dug at, working room included

    def trial_volume_m3(self, pits: int = 1) -> float:
        return pits * self.trial_width_m * self.trial_length_m * self.trial_depth_m

    def trial_samples_per_pit(self) -> int:
        """Samples at 1 m from 0.5 m to the base — 0.5, 1.5, 2.5 for a 3 m pit."""
        if self.trial_sample_interval_m <= 0:
            return 0
        depth = self.trial_depth_m - self.trial_sample_start_m
        if depth < 0:
            return 0
        return int(math.floor(depth / self.trial_sample_interval_m)) + 1

    def inspection_volume_m3(self, holes: int = 1) -> float:
        return holes * self.inspection_allowance_m3


class MonitoringRules(BaseModel):
    """Instruments, and how long they are read for."""

    max_instruments_per_hole: int = 2       # "up to two standpipes/piezometers … in each drillhole"
    monitoring_months: float = 12.0
    agmd_per_instrument: int = 1            # one automatic device per standpipe and per piezometer

    def instrument_weeks(self, instruments: int) -> int:
        """Instrument-weeks, the unit the bill measures recording in.

        Rounded to the nearest whole week, which is what reproduces the reference bill exactly:
        47 → 2,451 · 68 → 3,546 · 115 → 5,996.
        """
        weeks = instruments * (self.monitoring_months / 12.0) * DAYS_PER_YEAR / DAYS_PER_WEEK
        return int(round(weeks))


class TerminationRules(BaseModel):
    """When the driller stops — and who pays if he does not."""

    rock_core_m: float = 5.0                # continuous Grade III+ bedrock
    min_tcr_pct: float = 85.0               # per 1.0 m core
    max_depth_m: float = 80.0
    over_drilling_at_contractor_cost: bool = True   # PS 7.45D

    def warning(self) -> str:
        return (f"Terminate at {self.rock_core_m:g} m of continuous Grade III or better bedrock at "
                f"≥{self.min_tcr_pct:g}% TCR per 1.0 m core, or {self.max_depth_m:g} m, or as "
                f"instructed. Drilling beyond that is at the Contractor's expense (PS 7.45D).")


class TentativeTestCounts(BaseModel):
    """The tentative in-situ test numbers printed on the general-notes drawing.

    Held separately from the bill's numbers so the two can be compared — on the reference contract
    they differ, and an estimator wants to know that before he prices either.
    """

    permeability: int = 0
    pressuremeter: int = 0
    acoustic_televiewer: int = 0


class SiteCriteria(BaseModel):
    """Everything the general-notes drawing says, in one object."""

    source_sheet: str = ""                  # "60740338/GI/100"
    sampling: SamplingRules = Field(default_factory=SamplingRules)
    pits: PitRules = Field(default_factory=PitRules)
    monitoring: MonitoringRules = Field(default_factory=MonitoringRules)
    termination: TerminationRules = Field(default_factory=TerminationRules)
    tests: TentativeTestCounts = Field(default_factory=TentativeTestCounts)
    notes: list[str] = Field(default_factory=list)
