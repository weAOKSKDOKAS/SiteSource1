"""BOQ — the as-built data the production rates are calibrated from.

Bucket: **Evidence.** Not a model and not a judgement: 95 drillholes across three completed Hong Kong
ground investigation contracts, and what they turned out to say. Everything here is read-only
reference — the numbers a person would want to see before trusting a rate.

WHY BANDS AND NOT A REGRESSION
------------------------------
Fitting rock fraction as a regression coefficient returns a **negative intercept of −4.67 work-days**
and a rock rate of 15.4 m/day — faster than soil at 2.9. Rock metres and rock fraction are collinear,
so the fit predicts adequately and describes nothing physical. With n = 89 and correlated features
that will keep happening, and every new work type starts with a thinner corpus than this one.

A band that says *"15–35% rock, 3.69 m/work-day, n = 32"* is honest and degrades gracefully. A
coefficient of 0.0648 with a negative intercept is a fit artifact.

TWO FINDINGS THAT CONTRADICT THE OBVIOUS
----------------------------------------
**Depth does not slow drilling.** Shallow holes are *slower* per metre, because fixed set-up time
dominates a short hole. Under 25 m: 1.45 m/work-day. Over 45 m: 3.23. This is why the app does not
apply a depth-decay curve — an earlier version of this engine did, on one estimator's assumption, and
the data says the opposite.

**Weather is not a production driver.** The project that ran entirely inside typhoon season was the
fastest of the three; the relationship is inverse. Work-days already exclude non-working days by
construction, so weather cannot move the production rate — it moves the calendar. That is why the
calendar-to-work-day ratio exists as a separate input.

    DATA CAVEAT, stated because it matters: the Non-working Day sheet is present in all three source
    files and populated in none of them. No typhoon day was ever logged. Weather is *invisible* in
    this dataset rather than proven absent, and logging non-working days is a data-collection ask.

Rock fraction measures **mode of working**, not hardness. A 20% rock hole is washboring with a short
socket; a 70% rock hole is a coring operation. That is why it is the primary driver.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Below this many holes behind a band, the rate is indicative and the residual site factor is
# carrying the estimate rather than the evidence.
THIN_CORPUS = 10


class Band(BaseModel):
    """One production band: a rock-fraction floor, and what was actually achieved above it.

    ``rate`` is **all-in and blended** — total metres divided by total work-days, including per-hole
    set-up. It is not a drilling rate; it is what a hole in this band costs in days.
    """

    label: str = ""
    lower: float = 0.0                  # rock fraction at or above which this band applies
    rate: float = 0.0                   # m per work-day
    holes: int = 0                      # the n behind it — confidence follows this
    calibration_depth_m: float = 0.0    # the mean hole depth the band was measured at

    @property
    def indicative_only(self) -> bool:
        """A band this thin is a starting point, not a measurement."""
        return self.holes < THIN_CORPUS

    def confidence(self) -> str:
        if self.indicative_only:
            return (f"{self.holes} holes behind this band — under {THIN_CORPUS} the rate is "
                    f"indicative only, and the residual site factor is carrying the estimate")
        return f"{self.holes} holes behind this band"


class BandTable(BaseModel):
    """The bands, in ascending order of rock fraction.

    Editable: the template says so in terms — *"Refit whenever the corpus changes. Update n and
    calibration depth together with the rate."* Adding a band is adding a row here.
    """

    bands: list[Band] = Field(default_factory=list)

    def sorted_bands(self) -> list[Band]:
        return sorted(self.bands, key=lambda b: b.lower)

    def select(self, rock_fraction: float) -> Optional[Band]:
        """The band a rock fraction falls in — Excel ``MATCH(value, lower_bounds, 1)``.

        The largest lower bound that does not exceed the value. Returns ``None`` below the first
        bound rather than clamping: a table whose lowest band starts at 15% genuinely has nothing to
        say about a 5% rock job, and saying so is better than quietly pricing it as if it did.
        """
        found = None
        for band in self.sorted_bands():
            if rock_fraction >= band.lower:
                found = band
            else:
                break
        return found

    def problems(self) -> list[str]:
        """What is wrong with the table itself. Empty means usable."""
        out: list[str] = []
        if not self.bands:
            return ["there are no production bands, so nothing can be priced from metres"]
        seen: set[float] = set()
        for band in self.bands:
            if band.lower in seen:
                out.append(f"two bands both start at {band.lower:.0%} rock — the lower bounds have "
                           f"to be distinct or the lookup is ambiguous")
            seen.add(band.lower)
            if band.rate <= 0:
                out.append(f"band {band.label!r} has no production rate")
        if self.sorted_bands()[0].lower > 0:
            out.append(f"the lowest band starts at {self.sorted_bands()[0].lower:.0%} rock, so a job "
                       f"below that has no band — it will be reported, not priced")
        return out


# The bands as measured. Four rows, monotonic decline above 35% rock, 2.0x span end to end.
DEFAULT_BANDS = BandTable(bands=[
    Band(label="under 15% rock", lower=0.00, rate=3.39, holes=12, calibration_depth_m=56.5),
    Band(label="15% to 35% rock", lower=0.15, rate=3.69, holes=32, calibration_depth_m=34.8),
    Band(label="35% to 60% rock", lower=0.35, rate=2.64, holes=22, calibration_depth_m=36.0),
    Band(label="over 60% rock", lower=0.60, rate=1.82, holes=23, calibration_depth_m=31.8),
])


class SourceContract(BaseModel):
    """One completed contract in the corpus."""

    name: str
    holes: int
    total_m: float
    soil_m: float
    rock_m: float
    work_days: int
    calendar_to_work_day: float = 0.0
    idle_share: float = 0.0
    holes_started_in_typhoon_season: str = ""

    @property
    def rock_fraction(self) -> float:
        return self.rock_m / self.total_m if self.total_m else 0.0

    @property
    def blended_rate(self) -> float:
        return self.total_m / self.work_days if self.work_days else 0.0


SOURCE_CONTRACTS = [
    SourceContract(name="Lok Ma Chau (YL/2018/02)", holes=30, total_m=996.52, soil_m=688.98,
                   rock_m=307.54, work_days=234, calendar_to_work_day=1.19, idle_share=0.19,
                   holes_started_in_typhoon_season="30/30 = 100%"),
    SourceContract(name="Water Reservoirs (ND/2021/03)", holes=31, total_m=1060.67, soil_m=302.17,
                   rock_m=758.50, work_days=540, calendar_to_work_day=1.18, idle_share=0.18,
                   holes_started_in_typhoon_season="9/31 = 29%"),
    SourceContract(name="Kwun Tong North", holes=34, total_m=1433.65, soil_m=1141.71,
                   rock_m=288.48, work_days=486, calendar_to_work_day=1.36, idle_share=0.36,
                   holes_started_in_typhoon_season="2/28 = 7%"),
]


class FittedModel(BaseModel):
    """The ordinary-least-squares fit, retained **only** as the Method B cross-check.

    Its own diagnostics are the argument against using it as the pricing basis: soil and rock metres
    together explain 13.5% of the variance in hole duration, and adding project identity more than
    doubles that. Site context beats ground conditions, and a per-hole median absolute error of 4.1
    work-days is 38% of the actual duration.
    """

    setup_days_per_hole: float = 4.73
    soil_m_per_day: float = 7.29
    rock_m_per_day: float = 2.58
    r_squared: float = 0.135
    r_squared_with_project_dummies: float = 0.28
    median_absolute_error_days: float = 4.1
    n_holes: int = 89

    def work_days(self, holes: float, soil_m: float, rock_m: float) -> float:
        return (holes * self.setup_days_per_hole
                + soil_m / self.soil_m_per_day
                + rock_m / self.rock_m_per_day)

    def formula(self) -> str:
        return (f"work_days = {self.setup_days_per_hole:g} × holes + soil_m / "
                f"{self.soil_m_per_day:g} + rock_m / {self.rock_m_per_day:g}")


FITTED = FittedModel()


class PerHoleSpread(BaseModel):
    """How wide a single hole's productivity actually is. The reason a point estimate is not enough."""

    p10: float = 1.37
    median: float = 3.40
    p90: float = 5.53

    @property
    def ratio(self) -> float:
        return self.p90 / self.p10 if self.p10 else 0.0


SPREAD = PerHoleSpread()

# Production against hole depth — the finding that killed the depth-decay model.
DEPTH_BANDS = [
    {"band": "under 25 m", "holes": 16, "mean_work_days": 13.6, "m_per_work_day": 1.45},
    {"band": "25 to 35 m", "holes": 29, "mean_work_days": 11.9, "m_per_work_day": 2.53},
    {"band": "35 to 45 m", "holes": 22, "mean_work_days": 11.5, "m_per_work_day": 3.47},
    {"band": "over 45 m", "holes": 22, "mean_work_days": 17.7, "m_per_work_day": 3.23},
]

FINDINGS = [
    "Rock fraction measures mode of working, not hardness. A 20% rock hole is washboring with a "
    "short socket; a 70% rock hole is a coring operation.",
    "Shallow holes are slower per metre, because fixed set-up time dominates. Productivity does not "
    "decay with depth at hole level.",
    "The project that ran entirely inside typhoon season was the fastest of the three. Work-days "
    "already exclude non-working days, so weather moves the calendar, not the production rate.",
    "The Non-working Day sheet is present in all three source files and populated in none of them. "
    "Weather is invisible in this dataset rather than proven absent.",
    "Fitting rock fraction as a regression coefficient returns a negative intercept and rock "
    "drilling faster than soil. Bands are used instead because they degrade gracefully.",
]


def corpus_totals() -> dict:
    """The whole corpus in one row — what the bands are drawn from."""
    holes = sum(c.holes for c in SOURCE_CONTRACTS)
    total_m = sum(c.total_m for c in SOURCE_CONTRACTS)
    soil_m = sum(c.soil_m for c in SOURCE_CONTRACTS)
    rock_m = sum(c.rock_m for c in SOURCE_CONTRACTS)
    work_days = sum(c.work_days for c in SOURCE_CONTRACTS)
    return {
        "holes": holes, "total_m": round(total_m, 2), "soil_m": round(soil_m, 2),
        "rock_m": round(rock_m, 2),
        "rock_fraction": round(rock_m / total_m, 4) if total_m else 0.0,
        "work_days": work_days,
        "blended_rate": round(total_m / work_days, 2) if work_days else 0.0,
    }
