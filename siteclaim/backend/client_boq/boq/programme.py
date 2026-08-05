"""BOQ — quantities to work-days to rigs. The production model.

Bucket: **Deterministic**, over a **human** model. Nothing is guessed; everything follows from the
bill's own quantities and the bands in :mod:`client_boq.boq.model`.

TWO METHODS, AND WHY BOTH RUN
-----------------------------
**Method A — the banded lookup.** Rock fraction picks a band; the band gives an all-in blended rate;
total metres divided by that rate is the programme. Rock fraction measures *mode of working* — a 20%
rock hole is washboring with a short socket, a 70% hole is a coring operation — which is why it
predicts better than metres alone.

**Method B — the split rates.** A fitted model: fixed set-up per hole, plus soil metres over a soil
rate, plus rock metres over a rock rate.

A is the pricing basis. B is a **cross-check**, and the template is blunt about what to do when they
disagree: *"If A and B diverge, do not price."* The engine reports rather than refuses — the sweep is
the app's only hard stop — but it says so in a sentence nobody can miss.

They also do different jobs. **A sets the total; B sets how that total divides** between set-up, soil
and rock. :attr:`Programme.allocation` is the factor that reconciles them, and it is what lets one
banded total produce three separate item rates without inventing a second production model.

THE THREE CHECKS
----------------
Each returns a sentence, not a boolean, because each is a thing an estimator has to decide about:

* **convergence** — how far apart A and B landed
* **depth extrapolation** — this tender's mean hole depth against the depth the band was calibrated
  at. Over 30% either way and the band is being used outside the data behind it.
* **band confidence** — the number of holes behind the selected band

WHAT IS DELIBERATELY ABSENT
---------------------------
A depth-decay curve. An earlier version of this engine slowed drilling 5% per 20 m on one estimator's
assumption; the 95-hole corpus in :mod:`client_boq.boq.empirical` says shallow holes are *slower* per
metre because fixed set-up dominates. The evidence won.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.empirical import Band
from client_boq.boq.model import CostingModel


class Quantities(BaseModel):
    """What the bill asks for. The only tender-specific input the programme needs."""

    holes: float = 0.0
    soil_m: float = 0.0
    rock_m: float = 0.0
    hard_m: float = 0.0             # artificial hard material or boulder — priced at the rock rate

    @property
    def total_m(self) -> float:
        return self.soil_m + self.rock_m + self.hard_m

    @property
    def rock_and_hard_m(self) -> float:
        return self.rock_m + self.hard_m

    @property
    def rock_fraction(self) -> float:
        """Rock plus hard material as a share of everything drilled. Read from the bill, never typed."""
        return self.rock_and_hard_m / self.total_m if self.total_m else 0.0

    @property
    def mean_hole_depth_m(self) -> float:
        return self.total_m / self.holes if self.holes else 0.0

    def problems(self) -> list[str]:
        out = []
        if self.total_m <= 0:
            out.append("no drilled length, so there is no programme to derive")
        if self.holes <= 0:
            out.append("no drillholes, so per-hole set-up and the mean depth cannot be worked out")
        return out


class Check(BaseModel):
    """One thing worth knowing before pricing, and how much it matters."""

    key: str
    verdict: str                    # "ok" | "marginal" | "stop"
    message: str
    value: Optional[float] = None

    @property
    def blocking(self) -> bool:
        """Whether the template would say do not price. Reported, never enforced here."""
        return self.verdict == "stop"


class Programme(BaseModel):
    """The derived programme: days, rigs, standing time, and the material quantities that follow."""

    quantities: Quantities = Field(default_factory=Quantities)

    rock_fraction: float = 0.0
    band: Optional[Band] = None

    work_days: float = 0.0          # P50 — the pricing basis
    work_days_p10: float = 0.0
    work_days_p90: float = 0.0
    blended_rate: float = 0.0       # m per work-day actually implied

    setup_days: float = 0.0         # Method B's split, before scaling
    soil_days: float = 0.0
    rock_days: float = 0.0
    method_b_days: float = 0.0
    divergence: float = 0.0
    allocation: float = 1.0         # A ÷ B — reconciles the split to the banded total

    calendar_days: float = 0.0
    work_days_available_per_rig: float = 0.0
    rigs_required: int = 0
    rigs_exact: float = 0.0
    standing_hours: float = 0.0

    mazier_samples: int = 0
    soil_in_tubes_m: float = 0.0
    soil_for_boxing_m: float = 0.0
    soil_boxes: int = 0
    rock_boxes: int = 0
    core_boxes: int = 0
    grout_litres: float = 0.0

    checks: list[Check] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)

    def usable(self) -> bool:
        return not self.problems and self.band is not None

    def stops(self) -> list[Check]:
        return [c for c in self.checks if c.blocking]

    def scaled_days(self, kind: str) -> float:
        """Method B's split, scaled so it sums to the banded total. The build-up's driver."""
        base = {"setup": self.setup_days, "soil": self.soil_days, "rock": self.rock_days}[kind]
        return base * self.allocation


def derive(quantities: Quantities, model: CostingModel) -> Programme:
    """Run the production model. Reports what it cannot do rather than guessing past it."""
    programme = Programme(quantities=quantities, problems=list(quantities.problems()))
    if programme.problems:
        return programme

    programme.rock_fraction = quantities.rock_fraction
    band = model.bands.select(programme.rock_fraction)
    if band is None:
        lowest = model.bands.sorted_bands()[0].lower if model.bands.bands else 0.0
        programme.problems.append(
            f"this job is {programme.rock_fraction:.1%} rock and the lowest band starts at "
            f"{lowest:.0%} — there is no band for it, so nothing is priced from metres")
        return programme
    programme.band = band

    residual = model.value("residual_site_factor", 1.0)

    # --- Method A: the band sets the total -----------------------------------
    programme.work_days = quantities.total_m / band.rate * residual
    programme.work_days_p10 = programme.work_days * model.value("p10_multiplier", 1.0)
    programme.work_days_p90 = programme.work_days * model.value("p90_multiplier", 1.0)
    programme.blended_rate = (quantities.total_m / programme.work_days
                              if programme.work_days else 0.0)

    # --- Method B: the split sets the division -------------------------------
    programme.setup_days = quantities.holes * model.value("setup_days_per_hole")
    soil_rate = model.value("soil_m_per_day")
    rock_rate = model.value("rock_m_per_day")
    programme.soil_days = quantities.soil_m / soil_rate if soil_rate else 0.0
    programme.rock_days = quantities.rock_and_hard_m / rock_rate if rock_rate else 0.0
    programme.method_b_days = (
        (programme.setup_days + programme.soil_days + programme.rock_days) * residual)

    if programme.method_b_days:
        programme.divergence = programme.method_b_days / programme.work_days - 1.0
        programme.allocation = programme.work_days / programme.method_b_days

    # --- programme and resources ---------------------------------------------
    programme.calendar_days = programme.work_days * model.value("calendar_to_work_day", 1.0)
    programme.work_days_available_per_rig = (
        model.value("contract_period_months") * model.value("working_days_per_month"))
    if programme.work_days_available_per_rig:
        programme.rigs_exact = programme.work_days / programme.work_days_available_per_rig
        programme.rigs_required = math.ceil(programme.rigs_exact)
    programme.standing_hours = (programme.work_days * model.value("standing_allowance")
                                * model.value("hours_per_day", 8.0))

    _materials(programme, model)
    programme.checks = _checks(programme, model)
    return programme


def _materials(programme: Programme, model: CostingModel) -> None:
    """Derived material quantities — computed from the schedule, never estimated."""
    quantities = programme.quantities
    interval = model.value("mazier_interval_m")
    programme.mazier_samples = int(round(quantities.soil_m / interval)) if interval else 0
    programme.soil_in_tubes_m = (programme.mazier_samples
                                 * model.value("mazier_sample_length_m"))
    programme.soil_for_boxing_m = quantities.soil_m - programme.soil_in_tubes_m

    soil_capacity = model.value("soil_box_capacity_m")
    rock_capacity = model.value("rock_box_capacity_m")
    programme.soil_boxes = (math.ceil(programme.soil_for_boxing_m / soil_capacity)
                            if soil_capacity and programme.soil_for_boxing_m > 0 else 0)
    programme.rock_boxes = (math.ceil(quantities.rock_and_hard_m / rock_capacity)
                            if rock_capacity else 0)
    # Rounded up separately: soil and rock core do not share a box.
    programme.core_boxes = programme.soil_boxes + programme.rock_boxes

    radius = model.value("grout_hole_diameter_m") / 2.0
    programme.grout_litres = math.pi * radius * radius * quantities.total_m * 1000.0


def _checks(programme: Programme, model: CostingModel) -> list[Check]:
    band = programme.band
    settings = model.method
    checks: list[Check] = []

    # 1. Do the two methods agree?
    gap = abs(programme.divergence)
    if gap > settings.divergent_threshold:
        checks.append(Check(
            key="convergence", verdict="stop", value=programme.divergence,
            message=(f"The banded model and the split-rate model are {gap:.1%} apart "
                     f"({programme.work_days:,.0f} against {programme.method_b_days:,.0f} "
                     f"work-days). Over {settings.divergent_threshold:.0%} means one of them does "
                     f"not fit this tender — find out which before pricing.")))
    elif gap > settings.marginal_threshold:
        checks.append(Check(
            key="convergence", verdict="marginal", value=programme.divergence,
            message=(f"The two methods are {gap:.1%} apart ({programme.work_days:,.0f} against "
                     f"{programme.method_b_days:,.0f} work-days). Inside the "
                     f"{settings.divergent_threshold:.0%} stop, but worth a second look.")))
    else:
        checks.append(Check(
            key="convergence", verdict="ok", value=programme.divergence,
            message=f"The two methods agree to {gap:.1%}."))

    # 2. Is the band being used outside the data behind it?
    departure = 0.0
    if band and band.calibration_depth_m:
        departure = programme.quantities.mean_hole_depth_m / band.calibration_depth_m - 1.0
    if abs(departure) > settings.depth_departure_threshold:
        checks.append(Check(
            key="depth", verdict="marginal", value=departure,
            message=(f"Mean hole depth on this tender is "
                     f"{programme.quantities.mean_hole_depth_m:,.1f} m against the "
                     f"{band.calibration_depth_m:,.1f} m the band was calibrated at — "
                     f"{departure:+.1%}. The band is being extrapolated.")))
    else:
        checks.append(Check(
            key="depth", verdict="ok", value=departure,
            message=(f"Mean hole depth {programme.quantities.mean_hole_depth_m:,.1f} m against "
                     f"{band.calibration_depth_m:,.1f} m calibration — {departure:+.1%}, "
                     f"within the band.")))

    # 3. How much data is behind the band?
    checks.append(Check(
        key="band_confidence",
        verdict="marginal" if band.indicative_only else "ok",
        value=float(band.holes), message=band.confidence()))

    return checks


def against_the_bill(programme: Programme, billed_standing_hours: Optional[float]) -> Optional[Check]:
    """The derived standing time against what the client actually billed.

    Worth its own check because the gap can be enormous and nothing else would surface it. On the
    reference contract the model derives ~1,431 hours where Bill 2.3 carries 455 — a three-fold
    difference on a remeasured item, which is either a very different idle assumption or a very
    different job. Reported with both numbers; never reconciled away.
    """
    if billed_standing_hours is None or not programme.standing_hours:
        return None
    ratio = programme.standing_hours / billed_standing_hours if billed_standing_hours else 0.0
    if 0.75 <= ratio <= 1.25:
        return Check(key="standing_time", verdict="ok", value=ratio,
                     message=(f"Derived standing time {programme.standing_hours:,.0f} h against the "
                              f"{billed_standing_hours:,.0f} h billed — within a quarter."))
    return Check(
        key="standing_time", verdict="marginal", value=ratio,
        message=(f"The model derives {programme.standing_hours:,.0f} hours of standing time and the "
                 f"client billed {billed_standing_hours:,.0f} — {ratio:.1f}x. On a remeasured item "
                 f"that is either a different idle assumption or a different job. Worth a query "
                 f"before the idle allowance is priced."))
