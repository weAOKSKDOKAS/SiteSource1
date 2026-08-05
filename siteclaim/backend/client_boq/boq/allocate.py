"""BOQ — turning a resource sheet into a rate for a bill item.

Bucket: **Deterministic**. The recipes — *which* resources feed *which* item — are the estimator's
declaration of how he intends to recover his cost. This module only evaluates them.

THE SHAPE OF A RATE
-------------------
Every rate in the reference workbook has the same three parts, and once you see it the rest is
bookkeeping:

    rate  =  ( Σ terms )  ×  days  ×  markup  ÷  divisor

* **terms** — each is ``rate × coefficient × units`` of one resource line. ``units`` is either stated
  (two days of the crane lorry for a mobilisation) or taken from the line itself (all sixteen water
  barriers).
* **days** — for a mobilisation, none: the terms already say "two days". For drilling, the day count
  for *that material* out of the duration model.
* **divisor** — what turns a cost into a rate. Metres drilled, tubes used, holes moved between. ``1``
  for a lump item, where the amount *is* the rate.

Worked, on the reference figures:

    Mobilise on Land   ( Σ terms 35,601.20 ) × 1.33 ÷ 1        =  47,349.60
    Drilling, soil     ( 12,986.60/day ) × 3.1108 d × 1.33 ÷ 60 m  =     895.51 / m
    Drilling, rock     ( 12,986.60/day ) × 7.8892 d × 1.33 ÷ 72 m  =   1,892.55 / m
    Mazier samples     ( 30 tubes × 100 ) × 1.33 ÷ 30 tubes    =     133.00 / nr

BLENDING ACROSS GROUPS
----------------------
Bill 2 asks for **one** rate covering 2,300 m spread over 91 holes that are not alike — some beside a
highway, some up Saddle Pass. So the model runs once per hole group and the bill rate is the blend:

    rate  =  Σ( cost of that material, across every group )  ÷  Σ( metres of that material )

Which is the honest answer to "one rate, 91 different holes": price each group properly, then let the
arithmetic average them. A single group is simply the degenerate case, and must reproduce the
workbook exactly — that is the regression test for this whole design.

ROUNDING
--------
Once, at the end. Intermediate values stay full precision, because the rate is the thing that gets
written in the box and everything before it is working. ``amount = qty × rounded rate`` afterwards,
because that is the extension the tender examiner recomputes (GCT App C 2.2(i)).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.estimate import money
from client_boq.boq.resources import ResourceSheet

# Which day count a recipe multiplies by.
DAYS_NONE = ""            # the terms already carry their own units
DAYS_SOIL = "soil"
DAYS_ROCK = "rock"
DAYS_TOTAL = "total"


class RecipeTerm(BaseModel):
    """One resource, and how much of it this item carries."""

    key: str = ""
    units: Optional[float] = None   # None → use the line's own quantity
    label: str = ""                 # for the trace; defaults to the line's label

    def value(self, sheet: ResourceSheet) -> float:
        line = sheet.line(self.key)
        units = sheet.qty_of(self.key) if self.units is None else self.units
        return line.unit_cost() * units


class RateRecipe(BaseModel):
    """How one bill item recovers its cost.

    ``divisor_key`` names a resource quantity to divide by (tubes, boxes) when the divisor is not a
    bill quantity; otherwise ``divisor`` is used directly.
    """

    full_ref: str = ""
    label: str = ""
    terms: list[RecipeTerm] = Field(default_factory=list)
    days: str = DAYS_NONE
    divisor: float = 1.0
    divisor_key: str = ""           # take the divisor from a sheet line's quantity instead
    divisor_label: str = ""
    lump: bool = False              # an "item": the amount IS the rate (SMM Corr. 1/2007 Part III ¶3)
    apply_markup: bool = True

    def day_count(self, sheet: ResourceSheet) -> float:
        if self.days == DAYS_NONE:
            return 1.0
        if sheet.duration is None:
            raise ValueError(f"recipe {self.full_ref!r} needs {self.days!r} days but the sheet has "
                             f"no duration model")
        if self.days == DAYS_TOTAL:
            return float(sheet.duration.total_days)
        return sheet.duration.days_for(self.days)

    def divisor_value(self, sheet: ResourceSheet) -> float:
        return sheet.qty_of(self.divisor_key) if self.divisor_key else self.divisor

    def cost(self, sheet: ResourceSheet) -> float:
        """Unrounded cost this item carries from this sheet, before any divisor.

        Deliberately the only arithmetic on this class: :func:`price_item` is the single evaluator, so
        there is never a second implementation of a rate that could drift from the first.
        """
        base = sum(term.value(sheet) for term in self.terms) * self.day_count(sheet)
        return base * sheet.markup if self.apply_markup else base


class RateBreakdown(BaseModel):
    """A rate, with everything needed to show how it was reached.

    The point of the ``groups`` list: on a blended rate the estimator's first question is *which group
    is carrying this*, and the answer has to be on screen without another query.
    """

    full_ref: str = ""
    label: str = ""
    rate: Optional[float] = None
    cost: float = 0.0
    divisor: float = 0.0
    divisor_label: str = ""
    lump: bool = False
    markup_pct: float = 0.0
    groups: list[dict] = Field(default_factory=list)   # {group, cost, divisor, days}
    terms: list[dict] = Field(default_factory=list)    # {label, key, units, unit_cost, value}
    formula: str = ""


def price_item(recipe: RateRecipe, sheets: list[ResourceSheet], *,
               divisors: Optional[dict[str, float]] = None) -> RateBreakdown:
    """Evaluate one recipe across one or more hole groups, and blend.

    ``divisors`` optionally gives the divisor per group label — the metres *that group* contributes.
    Without it every group is evaluated on the recipe's own divisor, which is right for a single group
    and wrong for several, so the blend asks for it explicitly rather than guessing.
    """
    per_group: list[dict] = []
    total_cost = 0.0
    total_divisor = 0.0

    for sheet in sheets:
        cost = recipe.cost(sheet)
        if recipe.lump:
            divisor = 1.0
        elif divisors is not None and sheet.label in divisors:
            divisor = divisors[sheet.label]
        else:
            divisor = recipe.divisor_value(sheet)
        total_cost += cost
        total_divisor += divisor
        per_group.append({
            "group": sheet.label,
            "cost": money(cost),
            "divisor": divisor,
            "days": recipe.day_count(sheet),
        })

    breakdown = RateBreakdown(
        full_ref=recipe.full_ref, label=recipe.label, cost=money(total_cost),
        divisor=total_divisor, divisor_label=recipe.divisor_label, lump=recipe.lump,
        markup_pct=sheets[0].markup_pct if sheets else 0.0,
        groups=per_group if len(sheets) > 1 else [],
    )

    if sheets:
        first = sheets[0]
        breakdown.terms = [{
            "label": term.label or first.line(term.key).label,
            "key": term.key,
            "units": first.qty_of(term.key) if term.units is None else term.units,
            "unit_cost": money(first.line(term.key).unit_cost()),
            "value": money(term.value(first)),
        } for term in recipe.terms]

    if recipe.lump:
        breakdown.rate = money(total_cost)
        breakdown.formula = f"cost {money(total_cost):,.2f} (lump item — the amount is the rate)"
    elif total_divisor:
        breakdown.rate = money(total_cost / total_divisor)
        label = recipe.divisor_label or recipe.divisor_key or "unit"
        breakdown.formula = (f"{money(total_cost):,.2f} ÷ {total_divisor:,g} {label} "
                             f"= {breakdown.rate:,.2f}")
    else:
        # No rate rather than a crash: one item that cannot form a divisor must not stop the other
        # twenty-six from pricing. It leaves as an unpriced item, which the guards then flag loudly —
        # General Preambles ¶6 makes an unpriced item free work, so it will not stay quiet for long.
        label = recipe.divisor_label or recipe.divisor_key or "divisor"
        breakdown.rate = None
        breakdown.formula = (f"cost {money(total_cost):,.2f}, but the {label} is zero — no rate can be "
                             f"formed. Left unpriced rather than guessed.")

    return breakdown
