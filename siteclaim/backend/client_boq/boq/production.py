"""BOQ — the production assumption: how a given quantity is assumed to split, and how fast it goes.

Bucket: **Deterministic** expansion of a **human** judgement. The arithmetic here is exact; the
numbers it operates on are somebody's opinion about ground nobody has drilled yet, and the module is
built so that distinction stays visible.

WHY THIS LAYER EXISTS
---------------------
The bill says ``2,300 m`` of drilling in material other than rock. One line, one rate. It does not
say which holes those metres come from — and the cost per metre is not one number, because the
Method of Measurement itself slices the work four ways:

    material      SMM S02 2.12 Group IV   rock / boulder and artificial hard material / other
    hole size     SMM S02 2.12 Group III  "Drilling size H or N"
    depth stage   SMM S02 2.12 Group V    "In first stage of drillhole not exceeding 20m in length",
                                          "In second stage ... exceeding 20m but not exceeding 40m
                                          and so on in stages of 20m", measured (2.11A) "from the
                                          existing ground level"
    class of site SMM S02 2.06 Group II   "For moving rigs in different Classes of site"

The client's quantity surveyor worked all of that out hole by hole from the drawings and then
**summed**. Pricing runs it backwards: how many holes, how deep, what share is likely rock, which
class of site — from the 33 drawings (every borehole a numbered station with coordinates) and the
borehole logs of 14 past investigations disclosed in the Site Information.

The rate is then a weighted average over that assumed mix. **The mix is the estimate.** Assume a
fifth of the metres are hard going where it proves to be two fifths, and the rate is wrong for all
2,300 of them — and under NEC Main Option B, which remeasures, wrong for the whole contract.

Before this, the app asked for "1,920 hours" and recorded nothing about where that came from.

THIS IS NOT TAKE-OFF
--------------------
Take-off derives the quantity. The client derived it, we may not change it (GCT 6: "Any unauthorised
alteration ... may cause the tender to be disqualified"), and locked decision 1 keeps it out of this
product. What is modelled here is the *distribution* of a quantity we were handed. The total never
moves; only its shape. Which is why ``expand`` refuses a mix that does not add up rather than
scaling it to fit — a mix that disagrees with the bill is a mistake, and normalising it would hide
the mistake behind a perfectly plausible rate.
"""

from __future__ import annotations

from client_boq.estimate import money
from client_boq.models import BillItem, ItemAssumption, ResourceLine, ScheduleItem

# How much a mix may disagree with the bill's quantity before it is refused. Tight, because both
# sides are the estimator's own arithmetic — this catches a typo, not a rounding difference.
TOLERANCE = 0.005


class AssumptionMismatch(ValueError):
    """The condition mix does not add up to the quantity the client gave.

    Raised rather than absorbed. The whole value of this layer is that the shares are a
    reconciliation of a fixed total; silently scaling them would produce a rate that looks right and
    is not, with nothing on screen to say so.
    """


def shifts_for(assumption: ItemAssumption) -> list[tuple[str, float]]:
    """(condition label, shifts) for each condition. ``shifts = qty ÷ output``.

    A condition with no output rate contributes no shifts and is reported by
    :func:`unpriced_conditions` — never silently treated as instantaneous.
    """
    return [(c.label, money(c.qty / c.output) if c.output > 0 else 0.0)
            for c in assumption.conditions]


def unpriced_conditions(assumption: ItemAssumption) -> list[str]:
    """Conditions carrying work but no output rate — they would price at nothing."""
    return [c.label for c in assumption.conditions if c.qty and c.output <= 0]


def check(assumption: ItemAssumption, item: BillItem) -> None:
    """Raise :class:`AssumptionMismatch` unless the mix reconciles to the item's quantity."""
    if item.lump or item.qty is None:
        # A lump item has no quantity to split; its build-up is simply its amount (SMM Corrigendum
        # 1/2007 Part III 3: the amount inserted "shall be deemed to be the rate").
        return
    total = assumption.total_qty()
    if abs(total - item.qty) > TOLERANCE:
        raise AssumptionMismatch(
            f"item {item.full_ref}: the conditions total {total:,.3f} {item.unit} against the "
            f"{item.qty:,.3f} {item.unit} in the bill. The client's quantity is fixed and cannot be "
            f"altered, so a mix that does not reconcile is an error in the mix — it is not scaled "
            f"to fit, because a rate derived from a silently corrected mix looks exactly like one "
            f"that is right."
        )


def expand(assumption: ItemAssumption, item: BillItem) -> ScheduleItem:
    """Turn a condition mix into the resource lines the existing cost engine already prices.

    One crew line and one plant line per condition, so the trace stays legible: an estimator reading
    the build-up sees "soil, 0-20m, Class A — 150 shifts" rather than a single collapsed figure they
    cannot argue with. ``estimate/s03_cost_buildup.build_cost`` then resolves each ``resource_ref``
    against the rate book exactly as it does for a hand-typed schedule; nothing downstream needs to
    know an assumption was involved.
    """
    check(assumption, item)
    lines: list[ResourceLine] = []

    for condition in assumption.conditions:
        shifts = money(condition.qty / condition.output) if condition.output > 0 else 0.0
        if condition.crew_ref:
            lines.append(ResourceLine(
                description=f"{condition.label} — crew, {shifts:,.2f} shifts "
                            f"({condition.qty:,.0f} {item.unit} at {condition.output:g} per shift)",
                resource_ref=condition.crew_ref,
                qty=money(shifts * condition.shift_hours), unit="h",
            ))
        if condition.plant_ref:
            lines.append(ResourceLine(
                description=f"{condition.label} — plant, {shifts:,.2f} shifts",
                resource_ref=condition.plant_ref, qty=shifts, unit="shift",
            ))

    return ScheduleItem(
        item_id=item.full_ref, description=item.full_description(), category="direct",
        unit=item.unit, lines=lines,
    )


def weighted_output(assumption: ItemAssumption) -> float:
    """The blended output the mix implies — total quantity ÷ total shifts.

    A readout, for the screen and for arguing with. It is the single number an estimator can sanity
    check against experience: if the mix implies 11.4 m a shift and nothing on this site has ever
    beaten 9, the mix is wrong before any rate is looked up.
    """
    total_shifts = sum(shifts for _, shifts in shifts_for(assumption))
    if total_shifts <= 0:
        return 0.0
    return money(assumption.total_qty() / total_shifts)
