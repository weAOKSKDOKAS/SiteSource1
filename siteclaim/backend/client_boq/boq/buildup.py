"""BOQ — the spread's daily cost, and the cost of each kind of bill item.

Bucket: **Deterministic**. Sheets 03 and 04 of the reference template: what a day on site costs, and
how that cost reaches a rate per metre, per hole, per hour and per month.

THE SEPARATION THAT MUST NOT BLUR
---------------------------------
Two day-costs, and they behave differently:

* **A — cost per rig-day.** Plant (held for the whole spread duration, hence a standby factor),
  labour, consumables. **Scales with the number of rigs.**
* **B — cost per contract-day.** The site engineer, foreman, geologist and project manager.
  **Does not.** The site team manages a SITE: one team per site (times a coefficient), running for
  the contract period however much drilling is happening. Add a rig and this does not move.
* **B2 — cost per GFT-day.** The ground/field technician team, which manages RIGS at one per
  ``gft_ratio`` of them. This is the resource the 6:1 rule is about, and it is *not* the site team —
  an earlier version had one resource doing both jobs, which multiplied site management by the rig
  count and over-priced supervision on every multi-rig job.

Merge A and B and supervision gets priced per rig, which over-recovers on a one-rig job and
under-recovers on a three-rig one. Merge B and B2 and site management scales with plant. B and B2
are both recovered in Bill 1's time-related items and never inside a drilling rate — which is why
they leave this module as **monthly** figures.

HOW A DAY BECOMES A RATE
------------------------
The band gave a total; the split-rate model gave a shape; :attr:`Programme.allocation` reconciled
them. So each drilling item takes its share of the programme, multiplies by the rig-day cost, and
divides by its own quantity:

    soil rate = (soil work-days × allocation × cost per rig-day) ÷ soil metres

Every other row is the same three steps with a different driver and a different divisor, and both are
the estimator's to change.

THE MARK-UP CHAIN
-----------------
Applied in the order the model lists, and the two kinds are not interchangeable:

    a loading adds to cost                  factor = 1 + v      10% → ×1.100
    a margin is taken on the selling price  factor = 1/(1 − v)  10% → ×1.111

Ten percent is not ten percent. Treating a margin as a loading under-recovers on every rate in the
bill, which is the sort of error that is invisible until the job is finished.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.model import (
    CHARGE_CONTRACT_DAY,
    CHARGE_RIG_DAY,
    DIVISOR_CLASS_HOLES,
    DIVISOR_CONTRACT_MONTHS,
    DIVISOR_HOLES,
    DIVISOR_NONE,
    DIVISOR_QTY,
    DIVISOR_ROCK_M,
    DIVISOR_SOIL_M,
    DIVISOR_STANDING_H,
    DRIVER_FIXED,
    DRIVER_MATERIAL,
    DRIVER_PER_HOLE,
    DRIVER_ROCK_DAYS,
    DRIVER_SETUP_DAYS,
    DRIVER_GFT,
    DRIVER_SITE_TEAM,
    DRIVER_SOIL_DAYS,
    DRIVER_STANDING_DAYS,
    MATERIAL_BOXES,
    MATERIAL_GROUT,
    MATERIAL_TUBES,
    CostingModel,
    ItemBasis,
    class_variants,
)
from client_boq.boq.programme import Programme


class SpreadRow(BaseModel):
    """One line of the daily cost sheet, as it is read."""

    key: str
    label: str
    block: str
    multiplier: float
    rate: float
    cost_per_day: float
    charge: str
    note: str = ""


class Spread(BaseModel):
    """What a day on site costs, split the two ways that matter."""

    rows: list[SpreadRow] = Field(default_factory=list)
    cost_per_rig_day: float = 0.0
    cost_per_contract_day: float = 0.0      # ONE site team, per day
    cost_per_gft_day: float = 0.0           # ONE GFT, per day

    # TWO SUPERVISION RESOURCES, COUNTED DIFFERENTLY. The site team manages a SITE — its count is
    # sites x a coefficient and does not move when a rig is added. The GFT manages RIGS, at one per
    # `gft_ratio`. A previous version had one resource doing both jobs, which multiplied site
    # management by the rig count.
    site_count: float = 1.0
    site_team_per_site: float = 1.0
    site_teams: float = 0.0                 # fractional on purpose: a coefficient, like any allocation
    gft_ratio: float = 6.0
    gfts_required: int = 0

    rig_cost_programme: float = 0.0         # P50
    rig_cost_programme_p90: float = 0.0     # the exposure if productivity lands slow
    site_team_cost_programme: float = 0.0
    gft_cost_programme: float = 0.0

    def by_block(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for row in self.rows:
            out[row.block] = out.get(row.block, 0.0) + row.cost_per_day
        return out


def build_spread(programme: Programme, model: CostingModel) -> Spread:
    """Sheet 03 — the daily cost of one drilling spread, and what it comes to over the programme."""
    rows = [
        SpreadRow(key=line.key, label=line.label, block=line.block, multiplier=line.multiplier,
                  rate=line.rate, cost_per_day=line.cost_per_day(), charge=line.charge,
                  note=line.note)
        for line in model.spread
    ]
    # THE SITE TEAM IS PER SITE. Not per rig, and not rounded up: `site_team_per_site` is a
    # coefficient exactly like the geologist's 0.5 — half a team means a team shared with another
    # contract, which is a real and chargeable arrangement, and rounding it up would invent a
    # second team nobody employs.
    sites = model.value("site_count", 1.0)
    per_site = model.value("site_team_per_site", 1.0)
    site_teams = sites * per_site

    # THE GFT IS PER RIG-GROUP. Counted off the UNROUNDED rig count, as the template counted
    # supervision: 6.1 rigs genuinely needs a second GFT, and rounding the rigs first would hide it.
    gft_ratio = model.value("gft_ratio", 6.0) or 6.0
    gfts = math.ceil(programme.rigs_exact / gft_ratio) if programme.rigs_exact > 0 else 0

    spread = Spread(
        rows=rows,
        cost_per_rig_day=model.cost_per_rig_day(),
        cost_per_contract_day=model.cost_per_contract_day(),
        cost_per_gft_day=model.cost_per_gft_day(),
        site_count=sites, site_team_per_site=per_site, site_teams=site_teams,
        gft_ratio=gft_ratio, gfts_required=gfts,
    )
    spread.rig_cost_programme = spread.cost_per_rig_day * programme.work_days
    spread.rig_cost_programme_p90 = spread.cost_per_rig_day * programme.work_days_p90
    spread.site_team_cost_programme = (
        spread.cost_per_contract_day * site_teams * programme.work_days_available_per_rig)
    spread.gft_cost_programme = (
        spread.cost_per_gft_day * gfts * programme.work_days_available_per_rig)
    return spread


class BuildupRow(BaseModel):
    """One item basis: how many of the driver, what that costs, and the rate it produces."""

    key: str
    label: str
    driver: str
    quantity: float = 0.0           # days, or a material count
    unit_cost: Optional[float] = None
    total_cost: float = 0.0
    divisor: float = 0.0
    divisor_name: str = ""
    cost_per_unit: Optional[float] = None
    derivation: str = ""
    note: str = ""
    problem: str = ""


class Buildup(BaseModel):
    """Sheet 04 — every item basis, the direct total, and the chain that turns cost into price."""

    rows: list[BuildupRow] = Field(default_factory=list)
    total_direct_cost: float = 0.0
    markup_steps: list[dict] = Field(default_factory=list)
    selling_factor: float = 1.0
    problems: list[str] = Field(default_factory=list)

    def index(self) -> dict[str, BuildupRow]:
        return {row.key: row for row in self.rows}

    def cost_per_unit(self, key: str) -> Optional[float]:
        row = self.index().get(key)
        return row.cost_per_unit if row else None


class AccessCost(BaseModel):
    """What it costs to get the spread to a class of site, kept in its two named parts.

    They are separate because they are justified by different clauses and only one of them is
    Class B's by construction. A merged number would price correctly and explain nothing, and on
    this contract the explanation is what survives into a rate build-up somebody has to defend.
    """

    #: A temporary access platform. SMM S02 ¶2.08(h) puts access scaffolding in the moving-rigs
    #: item coverage, so it belongs in the Class B move rate and nowhere else.
    platform: float = 0.0
    #: Carrying the spread in and out by hand. ¶2.03 measures moves per hole and ¶2.06 splits them
    #: by class — carrying a rig to a hole is moving it — so this belongs to WHATEVER class the
    #: group is, including Class A. PS 7.01B reads Class A as "road traffic or manual labour", so
    #: the bill pays one rate for a rig the lorry delivered and a rig six people carried. This
    #: line is the only place that difference can be priced.
    portage: float = 0.0

    @property
    def total(self) -> float:
        return self.platform + self.portage


def build(programme: Programme, model: CostingModel,
          spread: Optional[Spread] = None, *,
          active_keys: Optional[set[str]] = None,
          class_counts: Optional[dict[str, float]] = None,
          platform_cost_b: float = 0.0,
          access_cost_by_class: Optional[dict[str, AccessCost]] = None) -> Buildup:
    """Sheet 04 — allocate the spread and the materials to each kind of bill item.

    ``active_keys`` is the set of basis keys the bill's items actually claim (after any human
    overrides). When it names a per-class variant of a set-up/move row, that row is EVALUATED AS
    ITS TWO CLASS VARIANTS instead of as one pool — both of them, because the split is a
    partition: the class an estimator did not point an item at still holds real work-days, and
    an unclaimed class row flags on conservation rather than vanishing. With no variant claimed
    (the default), nothing here changes: one pooled row, exactly as before.

    ``class_counts`` are the BILLED per-class hole counts ({"A": 80, "B": 11} on the reference
    contract) — the bill's own numbers, because the divisor must match the claiming item's
    quantity for conservation to balance.

    ``access_cost_by_class`` is what getting there costs, per class — a platform and/or portage,
    see :class:`AccessCost`. ``platform_cost_b`` is the older single-figure form of the same thing
    and still works: absent the map, it is read as a Class B platform, which is exactly what it
    was. Either way the money is ignored while the split is inactive, because folding it into the
    pooled row would price Class A moves as if they too needed platforms.

    A helicopter lift is deliberately absent from both. ¶2.08(h) covers scaffolding, not a lift,
    and Class C is not billed at all — so air money has no item to be absorbed into and belongs at
    the unbilled gate, where a person queries it, loads it onto a named item, spreads it, or
    accepts it as a risk.
    """
    spread = spread or build_spread(programme, model)
    result = Buildup()
    active = set(active_keys or ())
    access = (access_cost_by_class if access_cost_by_class is not None
              else {"B": AccessCost(platform=platform_cost_b)})

    for basis in model.basis_rows:
        variants = class_variants(basis)
        if variants and any(v.key in active for v in variants):
            for variant in variants:
                result.rows.append(_row(variant, programme, model, spread,
                                        class_counts=class_counts,
                                        access=access.get(variant.site_class)))
            continue
        result.rows.append(_row(basis, programme, model, spread))

    result.total_direct_cost = sum(r.total_cost for r in result.rows)
    result.problems = [r.problem for r in result.rows if r.problem]

    factor = 1.0
    for step in model.markup:
        try:
            step_factor = step.factor(model.inputs)
        except ValueError as bad:
            result.problems.append(str(bad))
            continue
        factor *= step_factor
        result.markup_steps.append({
            "key": step.key, "label": step.label, "kind": step.kind,
            "rate": step.rate(model.inputs), "factor": step_factor,
        })
    result.selling_factor = factor
    return result


def _row(basis: ItemBasis, programme: Programme, model: CostingModel,
         spread: Spread, *, class_counts: Optional[dict[str, float]] = None,
         access: Optional[AccessCost] = None) -> BuildupRow:
    rig_day = spread.cost_per_rig_day
    quantities = programme.quantities
    row = BuildupRow(key=basis.key, label=basis.label, driver=basis.driver, note=basis.note)

    if basis.driver in (DRIVER_SOIL_DAYS, DRIVER_ROCK_DAYS, DRIVER_SETUP_DAYS):
        kind = {DRIVER_SOIL_DAYS: "soil", DRIVER_ROCK_DAYS: "rock",
                DRIVER_SETUP_DAYS: "setup"}[basis.driver]
        row.quantity = programme.scaled_days(kind)
        if basis.site_class:
            # A PARTITION of the set-up days, never an addition: the two class rows' quantities
            # sum to exactly what the pooled row held, by the class share of the hole count.
            counts = class_counts or {}
            denominator = quantities.holes or sum(counts.values())
            share = (counts.get(basis.site_class, 0.0) / denominator) if denominator else 0.0
            row.quantity *= share
        row.unit_cost = rig_day
        row.total_cost = row.quantity * rig_day
        row.derivation = (f"{row.quantity:,.1f} work-days × {rig_day:,.2f} per rig-day "
                          f"(the split scaled by {programme.allocation:.4f} so it sums to the "
                          f"banded total)")
        if basis.site_class:
            counts = class_counts or {}
            row.derivation = (
                f"the Class {basis.site_class} share — {counts.get(basis.site_class, 0.0):g} of "
                f"{quantities.holes or sum(counts.values()):g} holes — of the set-up days: "
                + row.derivation)
        if basis.site_class and access and access.total:
            row.total_cost += access.total
            if access.platform:
                row.derivation += (
                    f" + {access.platform:,.2f} platform builds, typed on the Site groups. They "
                    f"land HERE because SMM S02 ¶2.08(h) puts access scaffolding in the "
                    f"moving-rigs item coverage and ¶2.03 measures moves per hole — a Class A "
                    f"move must not carry a platform it does not need.")
            if access.portage:
                row.derivation += (
                    f" + {access.portage:,.2f} to carry the spread in and out by hand, typed on "
                    f"the Site groups. ¶2.03 measures moves per hole and ¶2.06 splits them by "
                    f"class, and carrying a rig to a hole is moving it. PS 7.01B reads Class A "
                    f"as road traffic OR manual labour, so the bill pays one rate either way — "
                    f"this line is where the difference is actually priced.")

    elif basis.driver == DRIVER_STANDING_DAYS:
        hours_per_day = model.value("hours_per_day", 8.0) or 8.0
        row.quantity = programme.standing_hours / hours_per_day
        row.unit_cost = rig_day
        row.total_cost = row.quantity * rig_day
        row.derivation = (f"{programme.standing_hours:,.0f} idle hours ÷ {hours_per_day:g} "
                          f"= {row.quantity:,.1f} days × {rig_day:,.2f} per rig-day")

    elif basis.driver == DRIVER_SITE_TEAM:
        row.quantity = spread.site_teams * programme.work_days_available_per_rig
        row.unit_cost = spread.cost_per_contract_day
        row.total_cost = spread.site_team_cost_programme
        row.derivation = (f"{spread.site_count:g} site(s) × {spread.site_team_per_site:g} team(s) "
                          f"per site = {spread.site_teams:g} × "
                          f"{programme.work_days_available_per_rig:,.0f} contract-days × "
                          f"{spread.cost_per_contract_day:,.2f} per day. The site team manages a "
                          f"SITE — it does not move with the rig count. Recovered in Bill 1, "
                          f"never inside a drilling rate.")

    elif basis.driver == DRIVER_GFT:
        row.quantity = spread.gfts_required * programme.work_days_available_per_rig
        row.unit_cost = spread.cost_per_gft_day
        row.total_cost = spread.gft_cost_programme
        row.derivation = (f"ceil({programme.rigs_exact:.2f} rigs ÷ {spread.gft_ratio:g}) = "
                          f"{spread.gfts_required} GFT(s) × "
                          f"{programme.work_days_available_per_rig:,.0f} contract-days × "
                          f"{spread.cost_per_gft_day:,.2f} per day. The GFT manages RIGS — a "
                          f"different resource from the site team.")
        if spread.gfts_required and spread.cost_per_gft_day <= 0:
            # Loud, because unlike a preliminary this is recovered through a build-up rather than
            # matched to a bill line: a zero here would be supervision of the rigs, free.
            row.problem = (f"{spread.gfts_required} GFT(s) are required and the GFT has no rate, "
                           f"so supervising the rigs prices at nothing. Enter the GFT day-rate in "
                           f"the rate library and every estimate picks it up.")

    elif basis.driver == DRIVER_FIXED:
        parts = []
        for component in basis.components:
            rate = model.value(component.rate_key)
            qty = model.value(component.qty_key, 1.0)
            row.total_cost += rate * qty
            parts.append(f"{component.label or component.rate_key} {rate:,.0f} × {qty:g}")
        row.quantity = 1.0
        row.derivation = " + ".join(parts)
        if not basis.components:
            row.problem = (f"{basis.label!r} is a fixed cost with no components, so it prices at "
                           f"nothing. Add what it is made of, or remove the row.")

    elif basis.driver == DRIVER_PER_HOLE:
        row.unit_cost = model.value(basis.unit_cost_key)
        row.quantity = quantities.holes
        row.total_cost = row.unit_cost * quantities.holes
        row.derivation = f"{row.unit_cost:,.0f} per location × {quantities.holes:g} holes"

    elif basis.driver == DRIVER_MATERIAL:
        row.quantity = {
            MATERIAL_TUBES: float(programme.mazier_samples),
            MATERIAL_BOXES: float(programme.core_boxes),
            MATERIAL_GROUT: programme.grout_litres,
        }.get(basis.material, 0.0)
        row.unit_cost = model.value(basis.unit_cost_key)
        row.total_cost = row.quantity * row.unit_cost
        row.derivation = f"{row.quantity:,.0f} × {row.unit_cost:,.2f}"
        if not basis.material:
            row.problem = (f"{basis.label!r} is a material row but names no derived quantity, so "
                           f"there is nothing to multiply.")

    else:
        row.problem = f"{basis.label!r} uses driver {basis.driver!r}, which the engine does not know."
        return row

    row.divisor, row.divisor_name = _divisor(basis, programme, model, row.quantity,
                                             class_counts=class_counts)
    if basis.divisor == DIVISOR_NONE:
        # A lump: the amount is the rate (SMM Corr. 1/2007 Part III ¶3).
        row.cost_per_unit = row.total_cost
    elif row.divisor:
        row.cost_per_unit = row.total_cost / row.divisor
    else:
        row.cost_per_unit = None
        row.problem = (f"{basis.label!r} divides by {row.divisor_name}, which is zero here — no "
                       f"rate can be formed, so it is left unpriced rather than guessed.")
    return row


def _divisor(basis: ItemBasis, programme: Programme, model: CostingModel,
             own_qty: float, *, class_counts: Optional[dict[str, float]] = None) -> tuple[float, str]:
    quantities = programme.quantities
    counts = class_counts or {}
    return {
        DIVISOR_SOIL_M: (quantities.soil_m, "soil metres"),
        DIVISOR_ROCK_M: (quantities.rock_and_hard_m, "rock and hard-material metres"),
        DIVISOR_HOLES: (quantities.holes, "holes"),
        DIVISOR_STANDING_H: (programme.standing_hours, "standing hours"),
        DIVISOR_CONTRACT_MONTHS: (model.value("contract_period_months"), "contract months"),
        DIVISOR_QTY: (own_qty, "its own quantity"),
        DIVISOR_NONE: (1.0, "nothing — it is a lump"),
        # The billed hole count of THIS row's class — the bill's own number, so the divisor
        # matches the claiming item's quantity and conservation balances by construction. Zero
        # (class unknown to the bill) falls to the zero-divisor refusal: unpriced, never guessed.
        DIVISOR_CLASS_HOLES: (counts.get(basis.site_class, 0.0),
                              f"Class {basis.site_class or '?'} holes"),
    }.get(basis.divisor, (0.0, basis.divisor))
