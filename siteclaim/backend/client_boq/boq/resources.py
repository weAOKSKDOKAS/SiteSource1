"""BOQ — the resource sheet: what the job consumes, and what that costs.

Bucket: **Deterministic**. Every number here is either the estimator's (a rate, a coefficient, an
output) or arithmetic over them. Nothing is proposed and nothing is guessed.

Modelled line for line on a working estimator's costing sheet, because a build-up that does not look
like the one he already trusts is a build-up he will not read. Three mechanisms carry the weight:

**Duration drivers.** Quantities are not typed. Labour, the project manager, the geologist and
consumables are on site for the drilling days ``n``; the rig, the equipment, the site engineer and the
foreman are there for ``n + mobilisation`` — four extra days to bring the spread in, set it up and take
it away again. Change the ground and every quantity moves with it.

**Coefficients.** The share of a resource this job actually consumes. A project manager split across
three jobs is ``0.33``; two workers on one rig is ``2``; water barriers that will see five more jobs are
``0.2``. This is how shared plant and shared people get charged honestly to one bill.

**Geometry.** Materials are computed, not estimated: a sample tube every 2 m of soil, a box per 30 m of
compressed soil or 4 m of rock, grout as ``π r² × depth``. These follow from the specification's own
sampling rules (GI/100), so they change when the schedule changes.

ROUNDING
--------
``money()`` is applied to **money** — a line total, a class subtotal, a selling figure. It is never
applied to a **quantity**: 663.5043684381643 litres of grout is a volume, and rounding it before it
meets a price throws away cents for no benefit. Rates computed from this sheet round once, at the end,
in :mod:`client_boq.boq.allocate`.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from client_boq.estimate import money
from client_boq.boq.duration import DrillDuration

# Resource classes, in the order an estimator reads them.
CLASS_PLANT = "plant"
CLASS_EQUIPMENT = "equipment"
CLASS_LABOUR = "labour"
CLASS_SUPERVISION = "supervision"
CLASS_SUBCONTRACT = "subcontract"
CLASS_MATERIAL = "material"
CLASS_CONSUMABLE = "consumable"
CLASS_OTHER = "other"
CLASS_TRANSPORT = "transport"
CLASS_ORDER = (CLASS_PLANT, CLASS_EQUIPMENT, CLASS_LABOUR, CLASS_SUPERVISION, CLASS_SUBCONTRACT,
               CLASS_MATERIAL, CLASS_CONSUMABLE, CLASS_OTHER, CLASS_TRANSPORT)

# Duration drivers.
DRIVER_FIXED = "fixed"          # the quantity is typed
DRIVER_DRILLING = "n"           # the drilling days
DRIVER_ON_SITE = "n_plus_mob"   # drilling days + mobilisation: plant and staff arrive early, leave late

DEFAULT_MOB_DAYS = 4.0          # 1 day in, 1 to set up, 1 to dismantle, 1 out
DEFAULT_MARKUP_PCT = 33.0


class MaterialGeometry(BaseModel):
    """The physical rules that turn metres drilled into things bought.

    Defaults are the reference contract's, from GI/100: *"MAZIER samples … shall be taken at 2.0m
    intervals"*, samples of 0.5 m into a liner, and a hole gross diameter of 80 mm for grouting.
    """

    sample_interval_m: float = 2.0     # a Mazier every 2 m of soil (GI/100 field sampling ¶2)
    sample_length_m: float = 0.5       # how much of each 2 m goes into a liner rather than a box
    soil_box_capacity_m: float = 30.0  # compressed soil per wooden box
    rock_box_capacity_m: float = 4.0   # rock core per wooden box; soil and rock never share one
    hole_diameter_m: float = 0.08      # for the grout volume

    def soil_tubes(self, soil_m: float) -> int:
        """One liner per sampling interval, rounded up — you cannot buy 29.5 tubes."""
        if self.sample_interval_m <= 0:
            return 0
        return math.ceil(soil_m / self.sample_interval_m)

    def soil_into_tubes_m(self, soil_m: float) -> float:
        return self.soil_tubes(soil_m) * self.sample_length_m

    def soil_into_boxes_m(self, soil_m: float) -> float:
        return max(0.0, soil_m - self.soil_into_tubes_m(soil_m))

    def soil_boxes(self, soil_m: float) -> int:
        if self.soil_box_capacity_m <= 0:
            return 0
        return math.ceil(self.soil_into_boxes_m(soil_m) / self.soil_box_capacity_m)

    def rock_boxes(self, rock_m: float) -> int:
        if self.rock_box_capacity_m <= 0:
            return 0
        return math.ceil(rock_m / self.rock_box_capacity_m)

    def total_boxes(self, soil_m: float, rock_m: float) -> int:
        # Rounded up separately, because soil and rock core do not share a box.
        return self.soil_boxes(soil_m) + self.rock_boxes(rock_m)

    def grout_litres(self, total_m: float) -> float:
        """π r² × depth, in litres. Backfilling a hole is a cylinder of cement-bentonite grout."""
        radius = self.hole_diameter_m / 2.0
        return math.pi * radius * radius * total_m * 1000.0


class SheetLine(BaseModel):
    """One line of the resource sheet: ``rate × quantity × coefficient``.

    ``coefficient`` is the share of the resource this job consumes — the single most useful column on
    the sheet, and the one that makes a shared project manager chargeable without fiction.
    """

    key: str = ""                       # stable handle a rate recipe refers to
    label: str = ""
    resource_class: str = CLASS_PLANT
    coefficient: float = 1.0
    qty: float = 0.0                    # used when driver is DRIVER_FIXED, or filled by a driver
    driver: str = DRIVER_FIXED
    unit: str = ""
    rate: float = 0.0                   # per unit
    note: str = ""                      # the estimator's reasoning, shown on the sheet
    derivation: str = ""                # for a computed quantity, how it was computed

    def resolved_qty(self, duration: Optional[DrillDuration] = None,
                     mob_days: float = DEFAULT_MOB_DAYS) -> float:
        if self.driver == DRIVER_FIXED or duration is None:
            return self.qty
        if self.driver == DRIVER_DRILLING:
            return float(duration.total_days)
        if self.driver == DRIVER_ON_SITE:
            return float(duration.total_days) + mob_days
        raise ValueError(f"unknown duration driver {self.driver!r}")

    def unit_cost(self) -> float:
        """One unit of this resource, with its coefficient applied. What a rate recipe multiplies."""
        return self.rate * self.coefficient

    def total(self, duration: Optional[DrillDuration] = None,
              mob_days: float = DEFAULT_MOB_DAYS) -> float:
        return money(self.rate * self.resolved_qty(duration, mob_days) * self.coefficient)


class ResourceSheet(BaseModel):
    """The whole build-up for one hole group, and the totals a rate is drawn from."""

    label: str = ""
    lines: list[SheetLine] = Field(default_factory=list)
    duration: Optional[DrillDuration] = None
    mob_days: float = DEFAULT_MOB_DAYS
    markup_pct: float = DEFAULT_MARKUP_PCT

    def index(self) -> dict[str, SheetLine]:
        return {line.key: line for line in self.lines if line.key}

    def line(self, key: str) -> SheetLine:
        found = self.index().get(key)
        if found is None:
            raise KeyError(f"no resource line {key!r} on sheet {self.label!r}")
        return found

    @property
    def markup(self) -> float:
        return 1.0 + self.markup_pct / 100.0

    def qty_of(self, key: str) -> float:
        return self.line(key).resolved_qty(self.duration, self.mob_days)

    def total_of(self, key: str) -> float:
        return self.line(key).total(self.duration, self.mob_days)

    def selling_of(self, key: str) -> float:
        return money(self.total_of(key) * self.markup)

    def by_class(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for line in self.lines:
            out[line.resource_class] = money(
                out.get(line.resource_class, 0.0) + line.total(self.duration, self.mob_days))
        return {name: out[name] for name in CLASS_ORDER if name in out}

    def total(self) -> float:
        return money(sum(self.by_class().values()))

    def selling(self) -> float:
        return money(self.total() * self.markup)

    def daily_cost(self, keys: list[str]) -> float:
        """One day of the named resources, coefficients applied.

        The number a drilling rate is built on: what it costs to have this spread standing on site for
        one day. Deliberately not rounded — it is multiplied by a fractional day count before it ever
        becomes money.
        """
        return sum(self.line(key).unit_cost() for key in keys)


def material_lines(geometry: MaterialGeometry, soil_m: float, rock_m: float, *,
                   box_rate: float, tube_rate: float, grout_rate: float) -> list[SheetLine]:
    """The material lines, computed from the schedule rather than estimated.

    Each carries its own derivation so the sheet can show *why* it is twenty boxes and not eighteen.
    """
    tubes = geometry.soil_tubes(soil_m)
    boxes = geometry.total_boxes(soil_m, rock_m)
    grout = geometry.grout_litres(soil_m + rock_m)
    return [
        SheetLine(
            key="wooden_box", label="Wooden box", resource_class=CLASS_MATERIAL,
            qty=boxes, unit="nr", rate=box_rate,
            derivation=(f"soil ROUNDUP(({soil_m:g} − {geometry.soil_into_tubes_m(soil_m):g}) / "
                        f"{geometry.soil_box_capacity_m:g}) = {geometry.soil_boxes(soil_m)}  +  "
                        f"rock ROUNDUP({rock_m:g} / {geometry.rock_box_capacity_m:g}) = "
                        f"{geometry.rock_boxes(rock_m)}"),
            note="Soil and rock core cannot share a box, so each is rounded up separately.",
        ),
        SheetLine(
            key="soil_tube", label="Soil tube", resource_class=CLASS_MATERIAL,
            qty=tubes, unit="nr", rate=tube_rate,
            derivation=f"ROUNDUP({soil_m:g} / {geometry.sample_interval_m:g}) = {tubes}",
            note=f"A liner every {geometry.sample_interval_m:g} m of soil drilled.",
        ),
        SheetLine(
            key="cement_grout", label="Cement grout", resource_class=CLASS_MATERIAL,
            qty=grout, unit="L", rate=grout_rate,
            derivation=(f"π × ({geometry.hole_diameter_m:g}/2)² × {soil_m + rock_m:g} m × 1000 "
                        f"= {grout:.4f} L"),
            note="Backfilling the hole: a cylinder of grout over the whole drilled depth.",
        ),
    ]
