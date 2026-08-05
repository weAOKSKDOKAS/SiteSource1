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

    # The estimator's, and nobody else's.
    rigs: int = 1
    soil_output: float = 0.0                # m/day before decay
    rock_output: float = 0.0
    decay: float = 0.05
    access_build_cost: float = 0.0          # a Class B platform; belongs on the rig-move item

    badge: str = "user"
    basis: str = ""                         # why he believes it

    # Which of the fields above the estimator actually typed, rather than inherited from the output
    # book. Recorded as an act, not inferred from the value: `decay` defaults to 0.05, so a group
    # that nobody has touched holds the same 0.05 as one where somebody decided on 0.05 — and the
    # difference between an inherited number and a chosen one is exactly what the ⟨BOOK⟩/⟨YOURS⟩
    # chip exists to show. See :mod:`client_boq.boq.outputs`.
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

    def duration(self) -> DrillDuration:
        """The programme for this group. More rigs, proportionally fewer days on the critical path."""
        rigs = max(1, self.rigs)
        return simulate(self.soil_m / rigs, self.rock_m / rigs,
                        soil_output=self.soil_output, rock_output=self.rock_output, decay=self.decay)


def summarise(group: HoleGroup, schedule: StationSchedule) -> HoleGroup:
    """Fill a group's measured facts from the schedule. The judgement fields are left alone."""
    index = schedule.index()
    picked = [index[name] for name in group.stations if name in index]
    return group.model_copy(update={
        "soil_m": round(sum(s.soil_m for s in picked), 3),
        "rock_m": round(sum(s.rock_m for s in picked), 3),
        "deepest_m": max((s.total_m for s in picked), default=0.0),
        "holes_past_20m": sum(1 for s in picked if s.total_m > 20.0),
    })


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

    def counts(self) -> dict[str, int]:
        out = {name: 0 for name in CLASSES}
        for group in self.groups:
            if group.access_class in out:
                out[group.access_class] += group.hole_count
        return out

    def unassigned(self) -> int:
        return sum(g.hole_count for g in self.groups if g.access_class not in CLASSES)

    def reconcile(self) -> list[str]:
        """Where the estimator's classification disagrees with the bill's counts. Empty means agreed.

        The client never says which holes, only how many — so this is the one external check on a
        judgement he otherwise makes alone.
        """
        problems: list[str] = []
        if self.unassigned():
            problems.append(f"{self.unassigned()} station(s) have no access class yet")
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
