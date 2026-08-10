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

    Confirmed a second way, at day level, which is the reading that settles it: 205 individual
    drilling-days banded by the depth the rig was at when the day was worked come out 4.42 /
    **5.32** / 3.41 m per day for 0–20 m / 20–40 m / 40 m+. The middle band is 20% FASTER than the
    surface. Per hole, over the 21 holes with five or more drilling days, the depth-to-log-rate
    correlation averages **+0.11** and is positive in 13 of them. The 40 m+ dip is rock: across all
    95 holes ``corr(rate, rock %) = −0.428`` against ``corr(rate, depth) = +0.196``, and holding
    rock constant leaves depth with a *positive* coefficient. Banding on rock AND decaying on depth
    would count the same effect twice. See :data:`DAILY_RATE_BY_DEPTH` and :data:`RATE_DRIVERS`.

**The band table is a divisor, so its rates must be pooled.** A second measurement of the same four
bands over all 95 holes reads higher throughout (:data:`AS_BUILT_BANDS`). It is recorded, not
substituted: ``metres / rate`` has to come back to a real day count, and only the days-weighted
basis does. :func:`reconciliation` shows the arithmetic on the corpus itself.

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

# ---------------------------------------------------------------------------
# A SECOND MEASUREMENT OF THE SAME BANDS — recorded, NOT substituted
# ---------------------------------------------------------------------------
# A later pass over the same corpus reported the overall rate in each band across all 95 holes.
# Same boundaries, same corpus, higher numbers throughout — and the reason is a definition, not new
# ground. `RECONCILIATION` below shows the arithmetic. The short version:
#
#   * the corpus really drilled 3,490.84 m in 1,260 work-days: a POOLED rate of 2.77 m/work-day;
#   * `DEFAULT_BANDS` weighted by n comes to 2.91, which turns those metres back into 1,201 days —
#     4.7% under what was worked;
#   * this table weighted by n comes to 3.69, which turns them into 947 days — 24.9% under.
#
# A band rate in this engine is a DIVISOR: `metres / rate` has to reproduce a real day count. A mean
# of per-hole rates cannot, because it weights a slow hole and a fast hole equally while the days
# do not — the pooled figure is dragged down by exactly the holes that took longest. So the two are
# on different definitions, `DEFAULT_BANDS` is the one that belongs in a duration calculation, and
# these figures are kept beside it as evidence a person can weigh rather than swapped in for it.
#
# Both tables reach the assumptions register, each with its source, and the estimator chooses.
AS_BUILT_BANDS = BandTable(bands=[
    Band(label="under 15% rock", lower=0.00, rate=4.22, holes=12),
    Band(label="15% to 35% rock", lower=0.15, rate=4.32, holes=37),
    Band(label="35% to 60% rock", lower=0.35, rate=3.85, holes=23),
    Band(label="over 60% rock", lower=0.60, rate=2.23, holes=23),
])

AS_BUILT_SOURCE = ("95 holes across Lok Ma Chau (YL/2018/02), Water Service Reservoirs "
                   "(ND/2021/03) and Kwun Tong North — overall rate by rock fraction")


def weighted_rate(table: BandTable) -> float:
    """The table's n-weighted mean rate. What it implies if you priced the whole corpus with it."""
    holes = sum(b.holes for b in table.bands)
    return sum(b.rate * b.holes for b in table.bands) / holes if holes else 0.0


def reconciliation() -> dict:
    """The two tables against what the corpus actually worked. Computed, never typed.

    This is the answer to "should the defaults be replaced?" and it is recomputed from the corpus
    every time it is asked, so it cannot go stale against a table somebody edits.
    """
    totals = corpus_totals()
    metres, worked = totals["total_m"], totals["work_days"]
    rows = []
    for name, table, source in (
            ("current default", DEFAULT_BANDS, "Roadmap default, calibrated on 89 holes"),
            ("as-built measurement", AS_BUILT_BANDS, AS_BUILT_SOURCE)):
        rate = weighted_rate(table)
        implied = metres / rate if rate else 0.0
        rows.append({
            "name": name, "source": source, "holes": sum(b.holes for b in table.bands),
            "weighted_rate": round(rate, 3), "implied_work_days": round(implied, 0),
            "error_against_actual": round(implied / worked - 1.0, 4) if worked else None,
            "bands": [{"label": b.label, "lower": b.lower, "rate": b.rate, "holes": b.holes}
                      for b in table.sorted_bands()],
        })
    return {
        "corpus_metres": metres, "corpus_work_days": worked,
        "pooled_rate": round(metres / worked, 3) if worked else 0.0,
        "tables": rows,
        "verdict": (
            "The two tables are not on the same definition. A band rate is used here as a divisor — "
            "`metres / rate` must come back to a real day count — and only the pooled, "
            "days-weighted basis does that. The as-built figures read as a mean of per-hole rates, "
            "which weights a slow hole the same as a fast one and therefore overstates production "
            "by about a third. The defaults stand; the measurement is recorded beside them so the "
            "estimator can weigh it, and either table can be edited on this tender."),
    }


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

# The same finding read a second way, and the one that settles it: 205 individual drilling-days
# from 30 holes' daily logs in the Water Reservoirs records, banded by how deep the rig was WHEN
# THE DAY WAS WORKED. Hole-level rates (above) can be argued away as set-up dominating a short
# hole; these cannot — they are the same hole, deeper.
DAILY_RATE_BY_DEPTH = [
    {"band": "0 to 20 m", "m_per_day": 4.42},
    {"band": "20 to 40 m", "m_per_day": 5.32},      # 20% FASTER than the first band, not slower
    {"band": "over 40 m", "m_per_day": 3.41},       # rock-socket drilling in a 74%-rock project
]

# Per-hole, over the 21 holes with five or more drilling days: the correlation between depth and
# log-rate. Positive means faster as it gets deeper.
DEPTH_RATE_CORRELATION = {
    "holes": 21, "mean": 0.11, "positive": 13,
    "note": "flat to slightly faster within a hole; never a consistent slowdown",
}

# What actually predicts the rate, across all 95 holes. This is the argument for banding on rock
# fraction rather than decaying on depth — and for not doing both, which double-counts.
RATE_DRIVERS = {
    "rock_fraction": -0.428,
    "depth": 0.196,
    "note": ("Holding rock constant, the regression's depth coefficient is POSITIVE. The 40 m+ "
             "slowdown in DAILY_RATE_BY_DEPTH is a rock effect wearing a depth costume: the deep "
             "records come from a 74%-rock project."),
    "drilling_days_measured": 205,
}

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
