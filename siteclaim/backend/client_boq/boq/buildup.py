"""BOQ — the spread's daily cost, and the cost of each kind of bill item.

Bucket: **Deterministic**. Sheets 03 and 04 of the reference template: what a day on site costs, and
how that cost reaches a rate per metre, per hole, per hour and per month.

THE SEPARATION THAT MUST NOT BLUR
---------------------------------
Two day-costs, and they behave differently:

* **A — cost per rig-day.** Plant (held for the whole spread duration, hence a standby factor),
  labour, consumables. **Scales with the number of rigs.**
* **B — cost per contract-day.** The site engineer, foreman, geologist and project manager.
  **Does not.** One site team supervises several rigs, and it runs for the contract period however
  much drilling is happening.

Merge them and supervision gets priced per rig, which over-recovers on a one-rig job and
under-recovers on a three-rig one. B is recovered in Bill 1's time-related items and never inside a
drilling rate — which is why it leaves this module as a **monthly** figure.

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
    DRIVER_SITE_TEAM,
    DRIVER_SOIL_DAYS,
    DRIVER_STANDING_DAYS,
    MATERIAL_BOXES,
    MATERIAL_GROUT,
    MATERIAL_TUBES,
    CostingModel,
    ItemBasis,
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
    cost_per_contract_day: float = 0.0
    # The fallback mirrors the stated 6:1 rule (see model.DEFAULT_INPUTS) — a spread built
    # without a model input in reach must not resurrect the template's old 3:1.
    site_team_supervises: float = 6.0
    site_teams_required: int = 0

    rig_cost_programme: float = 0.0         # P50
    rig_cost_programme_p90: float = 0.0     # the exposure if productivity lands slow
    site_team_cost_programme: float = 0.0

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
    supervises = model.value("site_team_supervises_rigs", 6.0) or 6.0
    # Teams follow the UNROUNDED rig count, as the template does: 1.56 rigs still needs one team,
    # and rounding the rigs first would occasionally buy a second team nobody needs.
    teams = math.ceil(programme.rigs_exact / supervises) if programme.rigs_exact > 0 else 0

    spread = Spread(
        rows=rows,
        cost_per_rig_day=model.cost_per_rig_day(),
        cost_per_contract_day=model.cost_per_contract_day(),
        site_team_supervises=supervises,
        site_teams_required=teams,
    )
    spread.rig_cost_programme = spread.cost_per_rig_day * programme.work_days
    spread.rig_cost_programme_p90 = spread.cost_per_rig_day * programme.work_days_p90
    spread.site_team_cost_programme = (
        spread.cost_per_contract_day * teams * programme.work_days_available_per_rig)
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


def build(programme: Programme, model: CostingModel,
          spread: Optional[Spread] = None) -> Buildup:
    """Sheet 04 — allocate the spread and the materials to each kind of bill item."""
    spread = spread or build_spread(programme, model)
    result = Buildup()

    for basis in model.basis_rows:
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
         spread: Spread) -> BuildupRow:
    rig_day = spread.cost_per_rig_day
    quantities = programme.quantities
    row = BuildupRow(key=basis.key, label=basis.label, driver=basis.driver, note=basis.note)

    if basis.driver in (DRIVER_SOIL_DAYS, DRIVER_ROCK_DAYS, DRIVER_SETUP_DAYS):
        kind = {DRIVER_SOIL_DAYS: "soil", DRIVER_ROCK_DAYS: "rock",
                DRIVER_SETUP_DAYS: "setup"}[basis.driver]
        row.quantity = programme.scaled_days(kind)
        row.unit_cost = rig_day
        row.total_cost = row.quantity * rig_day
        row.derivation = (f"{row.quantity:,.1f} work-days × {rig_day:,.2f} per rig-day "
                          f"(the split scaled by {programme.allocation:.4f} so it sums to the "
                          f"banded total)")

    elif basis.driver == DRIVER_STANDING_DAYS:
        hours_per_day = model.value("hours_per_day", 8.0) or 8.0
        row.quantity = programme.standing_hours / hours_per_day
        row.unit_cost = rig_day
        row.total_cost = row.quantity * rig_day
        row.derivation = (f"{programme.standing_hours:,.0f} idle hours ÷ {hours_per_day:g} "
                          f"= {row.quantity:,.1f} days × {rig_day:,.2f} per rig-day")

    elif basis.driver == DRIVER_SITE_TEAM:
        row.quantity = spread.site_teams_required * programme.work_days_available_per_rig
        row.unit_cost = spread.cost_per_contract_day
        row.total_cost = spread.site_team_cost_programme
        row.derivation = (f"{spread.site_teams_required} team(s) × "
                          f"{programme.work_days_available_per_rig:,.0f} contract-days × "
                          f"{spread.cost_per_contract_day:,.2f} per day. Recovered in Bill 1, "
                          f"never inside a drilling rate.")

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

    row.divisor, row.divisor_name = _divisor(basis, programme, model, row.quantity)
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
             own_qty: float) -> tuple[float, str]:
    quantities = programme.quantities
    return {
        DIVISOR_SOIL_M: (quantities.soil_m, "soil metres"),
        DIVISOR_ROCK_M: (quantities.rock_and_hard_m, "rock and hard-material metres"),
        DIVISOR_HOLES: (quantities.holes, "holes"),
        DIVISOR_STANDING_H: (programme.standing_hours, "standing hours"),
        DIVISOR_CONTRACT_MONTHS: (model.value("contract_period_months"), "contract months"),
        DIVISOR_QTY: (own_qty, "its own quantity"),
        DIVISOR_NONE: (1.0, "nothing — it is a lump"),
    }.get(basis.divisor, (0.0, basis.divisor))
