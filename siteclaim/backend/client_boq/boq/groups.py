"""BOQ — hole groups: pricing 91 unlike holes so one rate can honestly cover them.

Bucket: **Deterministic** arithmetic around a **human** decision. The clustering is geometry; the
access class and the rig count are the estimator's, and this module will not invent either.

WHY GROUPS EXIST
----------------
A costing sheet prices *a* situation: one rig, one crew, one set of ground. Bill 2 asks for one rate
covering 2,300 m spread over 91 holes that are not alike — some beside Fanling Highway, some up Saddle
Pass where a rig cannot stand until a platform is built. Averaging by eye is how a bid gets lost.

So the model runs **once per group**, and the bill rate is the blend:

    rate  =  Σ( cost of that material, across every group )  ÷  Σ( metres of that material )

The easy roadside holes and the awkward hillside ones average into the single number the bill wants,
and the arithmetic — not an impression — does the averaging.

THE COUNT THAT CHECKS THE WORK
-------------------------------
The client's bill prices **80 Class A** and **11 Class B** rig moves (items 2.2a and 2.2b), but **no
document says which holes are which.** GI/210 has no class column; the drawing legend carries four
symbols and none denotes a class. So the allocation is the estimator's judgement — and his only
external check is that his counts come back to 80 and 11. :meth:`GroupPlan.reconcile` is that check.

A third class exists in the specification and **not** in the bill: PS 7.01B Class C is access *"only by
helicopter"*, and there is no item for it. A station classed C therefore has nowhere to be priced,
which is not a reason to price it at nothing — see :mod:`client_boq.boq.unbilled`.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from client_boq.estimate import money
from client_boq.boq.allocate import RateBreakdown, RateRecipe, price_item
from client_boq.boq.duration import DrillDuration, simulate
from client_boq.boq.empirical import Band, BandTable, DEFAULT_BANDS
from client_boq.boq.resources import ResourceSheet
from client_boq.boq.schedule import Station, StationSchedule

# PS 7.01B. A is road or manual access; B needs a temporary access platform; C is helicopter only.
CLASS_A = "A"
CLASS_B = "B"
CLASS_C = "C"
CLASSES = (CLASS_A, CLASS_B, CLASS_C)

CLASS_MEANING = {
    CLASS_A: "reachable by road traffic, or by manual labour without a temporary access platform",
    CLASS_B: "needs a temporary access platform",
    CLASS_C: "reachable only by helicopter — and the bill has no item for it",
}

# HOW THE SPREAD GETS THERE, which the CLASS DOES NOT TELL YOU.
# PS 7.01B Class A is "road traffic **or** manual labour", so one class covers both a rig the
# lorry delivers and a rig six people carry up a hillside — and those are not the same money or
# the same machine. The class is what the bill pays against; this is what actually happens, and
# it is the estimator's judgement exactly as the class is. Blank until somebody decides.
TRANSPORT_VEHICLE = "vehicle"     # driven or craned to the hole
TRANSPORT_MANUAL = "manual"       # broken down and carried in — portage labour, a smaller rig
TRANSPORT_AIR = "air"             # lifted in
TRANSPORTS = (TRANSPORT_VEHICLE, TRANSPORT_MANUAL, TRANSPORT_AIR)

TRANSPORT_MEANING = {
    TRANSPORT_VEHICLE: "driven or craned to the hole",
    TRANSPORT_MANUAL: "broken down and carried in by hand — portage labour, and a rig small "
                      "enough to be carried",
    TRANSPORT_AIR: "lifted in — and no bill item covers a lift",
}

#: Transport modes that put a rig on a person's back, so the rig is a portable one and its depth
#: capability is the binding constraint rather than the programme.
TRANSPORT_PORTABLE = (TRANSPORT_MANUAL, TRANSPORT_AIR)


class HoleShape(BaseModel):
    """One hole's measured soil and rock lengths. Measured, never judged."""

    station: str = ""
    soil_m: float = 0.0
    rock_m: float = 0.0


class HoleGroup(BaseModel):
    """A set of holes one spread works, and the conditions that make it different from the others."""

    label: str = ""
    stations: list[str] = Field(default_factory=list)
    access_class: str = ""                  # the estimator's; blank until he decides
    terrain: str = ""                       # free prose: "roadside", "steep, no vehicle access"

    soil_m: float = 0.0
    rock_m: float = 0.0
    deepest_m: float = 0.0
    holes_past_20m: int = 0
    #: The real shapes, one entry per station, filled by :func:`summarise` from the schedule. The
    #: group's totals are their sum — this is the same measurement, unpooled, and it exists because
    #: a programme over holes is not the same arithmetic as a programme over one long hole.
    shapes: list[HoleShape] = Field(default_factory=list)

    # The estimator's, and nobody else's.
    rigs: int = 1
    soil_output: float = 0.0                # m/day, at any depth
    rock_output: float = 0.0
    #: Efficiency lost per 20 m of depth, DOWN ONE HOLE. Defaults to 0.0 because that is what was
    #: measured: over 205 real drilling-days the rate does not fall with depth (0–20 m 4.42, 20–40 m
    #: 5.32, 40 m+ 3.41 m/day, and the deep-band dip is rock, not depth). Rock fraction is the
    #: driver and the band table already carries it. A non-zero value here is the estimator's
    #: deliberate padding, and it resets at every hole.
    decay: float = 0.0
    #: How the spread reaches these holes. See TRANSPORT_MEANING — the class says what the bill
    #: pays, this says what the work is. Blank until the estimator decides; never inferred.
    transport: str = ""

    # THE THREE COSTS OF GETTING THERE, kept apart because they are paid for differently and two
    # of them are new money the pooled rate never carried.
    access_build_cost: float = 0.0          # a Class B platform; belongs on the rig-move item
    #: Carrying the spread in and out by hand. Lands on the rig-move item OF THIS GROUP'S CLASS:
    #: SMM S02 ¶2.03 measures moves per hole and ¶2.06 splits them by class, and carrying a rig
    #: to a hole is moving it. A Class A group that is actually portaged is the case the bill's
    #: two items cannot see, and this is where that money goes.
    access_labour_cost: float = 0.0
    #: A helicopter lift. NEVER absorbed into a rate by this engine, whatever the class — ¶2.08(h)
    #: puts access *scaffolding* in the moving-rigs coverage and a lift is not scaffolding, and
    #: Class C is not billed at all. It goes to the unbilled gate to be queried, loaded onto a
    #: named item by a person, spread, or accepted as a risk. See :mod:`client_boq.boq.unbilled`.
    access_air_cost: float = 0.0

    badge: str = "user"
    basis: str = ""                         # why he believes it

    # Which of the fields above the estimator actually typed, rather than inherited from the output
    # book. Recorded as an act, not inferred from the value: `decay` defaults to 0.0, so a group
    # that nobody has touched holds the same 0.0 as one where somebody decided drilling does not
    # slow down — and the difference between an inherited number and a chosen one is exactly what
    # the ⟨BOOK⟩/⟨YOURS⟩ chip exists to show. See :mod:`client_boq.boq.outputs`.
    overrides: list[str] = Field(default_factory=list)

    @property
    def hole_count(self) -> int:
        return len(self.stations)

    def ready(self) -> list[str]:
        """What is still missing before this group can be priced. Empty means ready."""
        missing: list[str] = []
        if not self.access_class:
            missing.append("access class")
        if self.soil_m > 0 and self.soil_output <= 0:
            missing.append("soil output (m/day)")
        if self.rock_m > 0 and self.rock_output <= 0:
            missing.append("rock output (m/day)")
        if self.rigs < 1:
            missing.append("at least one rig")
        return missing

    def hole_shapes(self) -> list[HoleShape]:
        """The holes to simulate: the measured ones, or ``hole_count`` even shares of the totals.

        The fallback is not a guess about the ground — the totals are the totals either way — it is
        a statement that the metres are spread over this many holes, which is a fact the group
        already carries in ``stations``. A group with neither shapes nor stations is one hole,
        which is the only thing left to say about it.
        """
        if self.shapes:
            return self.shapes
        holes = max(1, self.hole_count)
        return [HoleShape(station=f"hole {n + 1}", soil_m=self.soil_m / holes,
                          rock_m=self.rock_m / holes) for n in range(holes)]

    def duration(self) -> DrillDuration:
        """The programme for this group: every hole simulated, then shared across the rigs.

        THE SCOPE FIX. This used to call ``simulate(soil_m / rigs, rock_m / rigs, …)`` — one
        continuous hole as deep as the group's whole share. ``simulate`` bands depth *down a hole*,
        so a 600 m group was drilled as if the rig were 600 m below ground by the end: at the old
        default 5% per 20 m that is ``0.95^30 ≈ 21%`` of the surface rate, and the group took 69
        days where it should take 30. The depth was never the group's; it was each hole's.

        So each hole is simulated on its own, decay resetting when the rig moves, and the
        fractional day-counts are summed and divided by the rigs. At ``decay = 0`` — the default —
        this is algebraically identical to the pooled form, because constant rates make the sum of
        ``m_i / output`` the same as ``Σm_i / output``; the two only part company when somebody
        deliberately asks for padding, and then this one is the correct reading of what they asked.

        The ceiling stays at group level rather than per hole: ``total_days`` rounds the critical
        path up once, exactly as before. Rounding every hole up would charge a part-day for each of
        91 of them and is a separate question from this one.
        """
        rigs = max(1, self.rigs)
        result = DrillDuration(soil_m=self.soil_m, rock_m=self.rock_m)
        soil_days = rock_days = 0.0
        day_no = 0

        for shape in self.hole_shapes():
            one = simulate(shape.soil_m, shape.rock_m, soil_output=self.soil_output,
                           rock_output=self.rock_output, decay=self.decay)
            soil_days += one.soil_days
            rock_days += one.rock_days_actual
            result.unfinished = result.unfinished or one.unfinished
            for day in one.days:
                day_no += 1
                result.days.append(day.model_copy(update={"day": day_no}))

        # Shared across the rigs: the metres are the same, the calendar is not.
        result.soil_days = soil_days / rigs
        result.rock_days_actual = rock_days / rigs
        spent = result.soil_days + result.rock_days_actual
        result.total_days = math.ceil(spent) if spent > 0 else 0
        result.rock_days_charged = max(0.0, result.total_days - result.soil_days)
        result.soil_complete_day = math.ceil(result.soil_days) if self.soil_m > 0 else None
        result.rock_complete_day = result.total_days if self.rock_m > 0 else None
        return result

    def rock_fraction(self) -> float:
        total = self.soil_m + self.rock_m
        return self.rock_m / total if total > 0 else 0.0


def summarise(group: HoleGroup, schedule: StationSchedule) -> HoleGroup:
    """Fill a group's measured facts from the schedule. The judgement fields are left alone."""
    index = schedule.index()
    picked = [index[name] for name in group.stations if name in index]
    return group.model_copy(update={
        "soil_m": round(sum(s.soil_m for s in picked), 3),
        "rock_m": round(sum(s.rock_m for s in picked), 3),
        "deepest_m": max((s.total_m for s in picked), default=0.0),
        "holes_past_20m": sum(1 for s in picked if s.total_m > 20.0),
        # The unpooled measurement, so the programme can be run over holes rather than over one
        # imaginary hole as deep as the group. Same numbers, kept in the shape they were measured.
        "shapes": [HoleShape(station=s.station, soil_m=s.soil_m, rock_m=s.rock_m) for s in picked],
    })


class BandCalibration(BaseModel):
    """What the as-built band table expects of this group, beside what the group's own outputs give.

    THE BAND TABLE IS THE PRODUCTION DRIVER, and this is where it reaches the group path. Before
    this, a group's speed came from two flat norms (soil 20 m/day, rock 10) plus a depth-decay
    curve, and its rock fraction — the one thing the corpus says predicts production — changed
    nothing. Now the group's own rock fraction selects a band, and the band's all-in rate says how
    many work-days a group of this shape has historically taken.

    It is a CHECK, not an override: the band rate is all-in and blended (metres ÷ work-days,
    per-hole set-up included) while the group's outputs are per-material drilling rates with set-up
    outside them, so substituting one for the other would quietly move set-up into the drilling
    rate. Set-up is therefore added explicitly here, at the model's own ``setup_days_per_hole``, so
    the two sides are on the same definition before they are compared.
    """

    rock_fraction: float = 0.0
    band_label: str = ""
    band_rate: float = 0.0                  # m per work-day, all-in
    band_holes: int = 0                     # the n behind it
    indicative_only: bool = False
    expected_work_days: float = 0.0         # what the band says a group this shape takes
    simulated_work_days: float = 0.0        # drilling days from the outputs, plus set-up
    divergence: Optional[float] = None      # simulated ÷ expected − 1
    note: str = ""
    problems: list[str] = Field(default_factory=list)


def band_calibration(group: HoleGroup, *, bands: Optional[BandTable] = None,
                     setup_days_per_hole: float = 0.0) -> BandCalibration:
    """Select the band from the group's OWN rock fraction and compare it with the group's outputs.

    Both sides are stated per rig-set, not per calendar: the band was measured on rigs, and dividing
    either side by the rig count would cancel out of the comparison anyway.
    """
    table = bands or DEFAULT_BANDS
    metres = group.soil_m + group.rock_m
    out = BandCalibration(rock_fraction=group.rock_fraction())
    if metres <= 0:
        out.problems.append("the group has no metres, so there is nothing to calibrate")
        return out

    band: Optional[Band] = table.select(out.rock_fraction)
    if band is None or band.rate <= 0:
        lowest = table.sorted_bands()[0].lower if table.bands else 0.0
        out.problems.append(
            f"{out.rock_fraction:.0%} rock falls below the lowest band ({lowest:.0%}), so the "
            f"as-built corpus has nothing to say about a group this shape — the outputs stand "
            f"alone and nothing is checking them")
        return out

    out.band_label, out.band_rate, out.band_holes = band.label, band.rate, band.holes
    out.indicative_only = band.indicative_only
    out.expected_work_days = metres / band.rate

    drilling = group.duration()
    rigs = max(1, group.rigs)
    setup = len(group.hole_shapes()) * setup_days_per_hole / rigs
    out.simulated_work_days = drilling.soil_days + drilling.rock_days_actual + setup
    if out.expected_work_days > 0:
        # The band is measured per rig-set; the simulation was divided by the rigs, so put it back.
        out.divergence = (out.simulated_work_days * rigs) / out.expected_work_days - 1.0
        out.note = (
            f"{out.rock_fraction:.0%} rock selects {band.label!r} at {band.rate:g} m/work-day "
            f"(n={band.holes}). {metres:,.0f} m at that rate is {out.expected_work_days:,.1f} "
            f"work-days; these outputs give {out.simulated_work_days * rigs:,.1f} including "
            f"{len(group.hole_shapes()) * setup_days_per_hole:,.1f} days of set-up "
            f"({out.divergence:+.0%}).")
    if out.indicative_only:
        out.problems.append(band.confidence())
    return out


def cluster(schedule: StationSchedule, *, radius_m: float = 250.0) -> list[HoleGroup]:
    """Propose groups by proximity — stations within ``radius_m`` of one already in a group join it.

    Single-link clustering on the coordinates the schedule already carries. It is a **proposal**: it
    knows nothing about terrain, roads or access, and the estimator regroups freely. Stations without
    coordinates fall into one group of their own rather than being dropped.
    """
    located = [s for s in schedule.stations if s.easting is not None and s.northing is not None]
    unlocated = [s for s in schedule.stations if s not in located]

    remaining = list(located)
    clusters: list[list[Station]] = []
    while remaining:
        seed = remaining.pop(0)
        blob = [seed]
        grew = True
        while grew:
            grew = False
            for candidate in list(remaining):
                if any(math.dist((candidate.easting, candidate.northing), (m.easting, m.northing))
                       <= radius_m for m in blob):
                    blob.append(candidate)
                    remaining.remove(candidate)
                    grew = True
        clusters.append(blob)

    clusters.sort(key=len, reverse=True)
    groups = [
        summarise(HoleGroup(label=f"Group {n}", stations=[s.station for s in blob],
                            basis=f"proposed by proximity, within {radius_m:g} m"), schedule)
        for n, blob in enumerate(clusters, start=1)
    ]
    if unlocated:
        groups.append(summarise(
            HoleGroup(label="Unlocated", stations=[s.station for s in unlocated],
                      basis="no coordinates on the schedule; grouped by hand"), schedule))
    return groups


class GroupPlan(BaseModel):
    """Every group, and the check against what the client billed."""

    groups: list[HoleGroup] = Field(default_factory=list)
    billed_class_counts: dict[str, int] = Field(default_factory=dict)   # {"A": 80, "B": 11}
    #: How many holes the take-off actually holds. ``None`` when no schedule has been read — and
    #: that is a different fact from zero, which is why it is Optional and not defaulted to 0.
    #:
    #: WITHOUT IT ``unassigned()`` COUNTS THE WRONG POPULATION. It sums holes that are IN a group
    #: and have no class, so a hole in no group contributes nothing — and a tender with 91 stations
    #: read off the drawing and not one group made reports **0 unassigned**, which reads as "every
    #: hole has been classed". `router.py`'s settle gate names this exact shape ("ABSENCE IS NOT
    #: CLEARANCE") for the case where no schedule exists at all; this is the same error one step in,
    #: where the schedule exists and the grouping has not started.
    total_holes: Optional[int] = None

    def counts(self) -> dict[str, int]:
        out = {name: 0 for name in CLASSES}
        for group in self.groups:
            if group.access_class in out:
                out[group.access_class] += group.hole_count
        return out

    def unassigned(self) -> int:
        """Holes with no class of site. Over the WHOLE take-off when it is known.

        Falls back to the grouped-only count when ``total_holes`` is not supplied, because that is
        genuinely all this object can see — the caller that knows the take-off passes it.
        """
        if self.total_holes is None:
            return sum(g.hole_count for g in self.groups if g.access_class not in CLASSES)
        classed = sum(g.hole_count for g in self.groups if g.access_class in CLASSES)
        return max(0, self.total_holes - classed)

    def reconcile(self) -> list[str]:
        """Where the estimator's classification disagrees with the bill's counts. Empty means agreed.

        The client never says which holes, only how many — so this is the one external check on a
        judgement he otherwise makes alone. Which is why an empty ``billed_class_counts`` is not
        silence but its own problem: with nothing to check against, "agreed" is a claim about a
        comparison that never ran.
        """
        problems: list[str] = []
        if self.unassigned():
            problems.append(f"{self.unassigned()} station(s) have no access class yet")
        if not self.billed_class_counts:
            problems.append(
                "the bill's rig-move items have not been identified, so there is nothing to check "
                "this classification against — the client's counts are the only external check "
                "there is on it")
        for name, billed in sorted(self.billed_class_counts.items()):
            mine = self.counts().get(name, 0)
            if mine != billed:
                problems.append(
                    f"Class {name}: you have {mine} against the {billed} the client billed "
                    f"({'over' if mine > billed else 'under'} by {abs(mine - billed)})")
        stray = self.counts().get(CLASS_C, 0)
        if stray and CLASS_C not in self.billed_class_counts:
            problems.append(
                f"{stray} station(s) classed C — {CLASS_MEANING[CLASS_C]}. There is no bill item, so "
                f"this has to be queried, loaded onto the rig-move item, or accepted as a risk")
        return problems

    def not_ready(self) -> dict[str, list[str]]:
        return {g.label: g.ready() for g in self.groups if g.ready()}

    def reach(self, portable_rig_max_depth_m: float = 0.0) -> list[str]:
        """Holes a carried-in rig cannot reach the bottom of. Empty means nothing to say.

        THIS IS NOT A SLOWER PROGRAMME, IT IS THE WRONG MACHINE. Every other constraint in this
        module is about how long the work takes; a depth capability is about whether the work is
        possible with the spread you said you were sending. A rig broken down into man-carriable
        loads is a smaller rig, and if the schedule says 60 m and it reaches 30, no production
        rate, no rig count and no programme fixes it — the hole needs a platform and a bigger
        machine, a different access route, or a query.

        The limit is not defaulted. A firm's rig fleet is not something this engine can know, and
        a plausible-looking number here would decide a real question on a value nobody chose. So
        zero means unset, and the LAST branch says so out loud rather than returning an empty list
        that reads exactly like "checked, and fine".
        """
        carried = [g for g in self.groups if g.transport in TRANSPORT_PORTABLE]
        if not carried:
            return []
        if portable_rig_max_depth_m <= 0:
            return [f"{len(carried)} group(s) are reached by hand or by air and no depth limit is "
                    f"set for a carried-in rig, so nothing has been checked. Set "
                    f"'Deepest a carried-in rig will drill' on the costing model — until then a "
                    f"hole scheduled deeper than the rig reaches will price as ordinary work"]
        problems: list[str] = []
        for group in carried:
            over = [s for s in group.shapes
                    if (s.soil_m + s.rock_m) > portable_rig_max_depth_m]
            if not over:
                continue
            deepest = max(s.soil_m + s.rock_m for s in over)
            names = ", ".join(s.station for s in over[:6]) + (" …" if len(over) > 6 else "")
            problems.append(
                f"{group.label}: {len(over)} hole(s) go deeper than the {portable_rig_max_depth_m:g} m "
                f"a carried-in rig reaches — deepest {deepest:g} m ({names}). "
                f"{TRANSPORT_MEANING.get(group.transport, group.transport)}, so this is the wrong "
                f"machine for those holes, not a slower one")
        return problems


def blend(recipe: RateRecipe, sheets: list[ResourceSheet],
          divisors: dict[str, float]) -> RateBreakdown:
    """Evaluate one recipe over several groups and blend to a single rate.

    ``divisors`` gives the metres (or count) each group contributes, keyed by group label. It is
    required rather than inferred: guessing which group carries which share of a bill quantity is
    precisely the kind of silent assumption this package exists to avoid.
    """
    missing = [sheet.label for sheet in sheets if sheet.label not in divisors]
    if missing and not recipe.lump:
        raise KeyError(
            f"recipe {recipe.full_ref!r}: no divisor given for group(s) {', '.join(missing)}. "
            f"The share each group carries is a decision, not something to infer.")
    return price_item(recipe, sheets, divisors=divisors)


def group_divisors(groups: list[HoleGroup], material: str) -> dict[str, float]:
    """Metres of one material per group — the natural divisor for a drilling rate."""
    if material not in {"soil", "rock"}:
        raise ValueError(f"unknown material {material!r}")
    return {g.label: (g.soil_m if material == "soil" else g.rock_m) for g in groups}


def access_build_total(plan: GroupPlan) -> float:
    """What the platforms cost in total.

    It belongs on the rig-move item, not on drilling: the measurement rules put access scaffolding in
    the item coverage for moving rigs (SMM S02 ¶2.08(h)), and moves are measured per hole (¶2.03).
    """
    return money(sum(g.access_build_cost for g in plan.groups))
