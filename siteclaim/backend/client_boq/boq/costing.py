"""BOQ — the priced bill. Quantities in, rates out.

Bucket: **Deterministic pricing over a proposed mapping.** The arithmetic is fixed; the mapping — which
bill item takes its quantity from where, and which build-up prices it — is **proposed and confirmed**,
never assumed.

WHY THE MAPPING IS PROPOSED AND NOT HARDCODED
---------------------------------------------
The engine needs four numbers out of the bill: how many holes, and how many metres of soil, rock and
artificial hard material. On ND/2025/04 they are items 2.2, 2.4, 2.5 and 2.6. On the next contract
they will be somewhere else, worded differently, possibly split three ways.

So this module reads the bill's own descriptions and **proposes** a mapping, with the words that made
it think so. A person confirms or corrects it. That is the same rule the rest of the app runs on: if
two good estimators would agree, the app does it; where they might not, the app asks. Nobody would
disagree that *"Drilling … material other than rock, boulder or artificial hard material"* is the soil
item — but they might well disagree on the next contract, and the app cannot tell in advance which
kind of contract it is looking at.

An item that matches nothing is **reported, never dropped**. Silence is the expensive failure here:
General Preambles ¶6 deems an item with no rate covered by the other rates, which is work done for
nothing for the life of the contract.

THE RATE LADDER
---------------
    cost basis  →  × selling factor  →  raw rate  →  rounded  →  RATE TO SUBMIT  →  amount

The rounded figure is a **proposal**. `rate_to_submit` is a separate value the estimator may overwrite
with anything, and the amount follows whatever is actually in it — because the last decision before a
tender goes in is a commercial one, and it is not the app's.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, computed_field

from client_boq.boq import model as boq_model
from client_boq.boq.buildup import Buildup
from client_boq.boq.model import CostingModel
from client_boq.boq.programme import Programme, Quantities
from client_boq.models import BillItem, ClientBill

# The four quantities the production model needs out of the bill.
ROLE_HOLES = "holes"
ROLE_SOIL = "soil_m"
ROLE_ROCK = "rock_m"
ROLE_HARD = "hard_m"
ROLES = (ROLE_HOLES, ROLE_SOIL, ROLE_ROCK, ROLE_HARD)

ROLE_MEANING = {
    ROLE_HOLES: "the number of drillholes — the rig-move item",
    ROLE_SOIL: "metres drilled in material other than rock",
    ROLE_ROCK: "metres drilled in rock",
    ROLE_HARD: "metres in artificial hard material or boulder",
}

# What makes this module think an item fills a role. Patterns, not certainties — every match is shown
# with the words that produced it so a person can see what it read and disagree.
_QUANTITY_PATTERNS: dict[str, list[tuple[str, str]]] = {
    ROLE_HOLES: [(r"moving\s+rigs", "nr")],
    ROLE_SOIL: [(r"material\s+other\s+than\s+rock", "m")],
    ROLE_HARD: [(r"artificial\s+hard\s+material|boulder", "m")],
    ROLE_ROCK: [(r"\brock\b", "m")],
}

# Which build-up basis prices which kind of item. Same rule: a proposal, with its reason.
_BASIS_PATTERNS: list[tuple[str, str, str]] = [
    # (basis key, pattern, why)
    ("soil_drilling", r"material\s+other\s+than\s+rock", "drilling in soil"),
    ("rock_drilling", r"artificial\s+hard\s+material|boulder",
     "obstruction drilling — the template prices it at the rock rate"),
    ("rock_drilling", r"drilling.*\brock\b|\brock\b.*drilling", "drilling in rock"),
    ("setup_move", r"moving\s+rigs", "a rig move — the fixed set-up share"),
    ("mobilise", r"establishment\s+of\s+rigs|mobilis", "bringing the spread to site"),
    ("standing_time", r"standing\s+time", "idle rig time"),
    ("soil_tubes", r"mazier|u76|u100|piston|disturbed\s+sample", "a sample tube"),
    ("core_boxes", r"rock\s+core|core\s+box", "core boxing"),
    ("setting_out", r"setting\s+out|survey", "setting out per location"),
    ("site_team", r"supervision|time-?related|establishment\s+of\s+site", "a time-related item"),
]

# Laboratory items are matched to buy rates by name.
_LAB_PATTERNS: list[tuple[str, str]] = [
    ("lab_moisture", r"moisture\s+content"),
    ("lab_atterberg", r"atterberg"),
    ("lab_psd", r"particle\s+size"),
    ("lab_bulk_density", r"bulk\s+density"),
    ("lab_particle_density", r"particle\s+density|specific\s+gravity"),
    ("lab_ph", r"\bph\b"),
    ("lab_sulphate", r"sulphate"),
    ("lab_chloride", r"chloride"),
    ("lab_organic", r"organic"),
    ("lab_uu", r"\buu\b|unconsolidated\s+undrained"),
    ("lab_cu", r"\bcu\b|consolidated\s+undrained"),
    ("lab_oedometer", r"oedometer"),
    ("lab_point_load", r"point\s+load"),
    ("lab_ucs", r"\bucs\b|uniaxial|compression\s+test"),
    ("lab_modulus", r"elastic\s+modulus"),
    ("lab_joint_shear", r"joint\s+shear"),
]


class QuantityMatch(BaseModel):
    """One proposal that a bill item supplies one of the engine's four quantities."""

    role: str
    full_ref: str = ""
    description: str = ""
    value: float = 0.0
    unit: str = ""
    why: str = ""
    confirmed: bool = False
    # The leaf items summed, when the match is a heading whose children carry the quantities.
    # Listed rather than hidden: "91" is a number somebody has to be able to check.
    contributing: list[str] = Field(default_factory=list)


class QuantityMapping(BaseModel):
    """Where the production model's numbers come from, and what is still unanswered."""

    matches: dict[str, QuantityMatch] = Field(default_factory=dict)
    unmatched_roles: list[str] = Field(default_factory=list)

    def quantities(self) -> Quantities:
        get = lambda role: self.matches[role].value if role in self.matches else 0.0
        return Quantities(holes=get(ROLE_HOLES), soil_m=get(ROLE_SOIL),
                          rock_m=get(ROLE_ROCK), hard_m=get(ROLE_HARD))

    def problems(self) -> list[str]:
        return [f"nothing in the bill was recognised as {ROLE_MEANING[role]} — point it at an item "
                f"or the programme will be derived from an incomplete take-off"
                for role in self.unmatched_roles]


def propose_quantities(bill: ClientBill) -> QuantityMapping:
    """Read the bill and propose where each of the four quantities comes from.

    Order matters: artificial hard material is checked before rock, because *"artificial hard material
    or boulder"* also contains the word rock in most bills and would otherwise be swallowed by it.
    """
    mapping = QuantityMapping()
    taken: set[str] = set()

    for role in (ROLE_HOLES, ROLE_SOIL, ROLE_HARD, ROLE_ROCK):
        for pattern, unit in _QUANTITY_PATTERNS[role]:
            found = _first_match(bill, pattern, unit, skip=taken)
            if found is None:
                continue
            found.role = role
            mapping.matches[role] = found
            taken.update(found.contributing or [found.full_ref])
            break

    mapping.unmatched_roles = [r for r in ROLES if r not in mapping.matches]
    return mapping


def _first_match(bill: ClientBill, pattern: str, unit: str,
                 skip: set[str]) -> Optional[QuantityMatch]:
    """The first item whose description matches, **summing a parent's children**.

    The reference bill needs this and it is not an edge case. Item 2.2 reads *"Moving rigs"* and
    carries no quantity at all: the numbers are on 2.2a *"in Class A of site"* (80) and 2.2b *"in
    Class B of site"* (11), whose own descriptions never mention a rig. Matching only leaf items
    finds nothing; matching the parent finds a row with no quantity. Ninety-one holes is 80 + 11,
    which is exactly the sum an estimator does in their head, so the code does it and says so.
    """
    rx = re.compile(pattern, re.I)
    for item in bill.items:
        if item.pre_priced or item.full_ref in skip:
            continue
        if not rx.search(item.full_description()):
            continue

        if item.is_parent:
            # `item_ref` is the reader's own record of the parent — a sub-item of 2.2 has
            # item_ref="2.2", sub_ref="a", full_ref="2.2a". Use that rather than a string prefix:
            # "2.2".startswith matching also swallows 2.20, 2.21, 2.22 … which on the reference
            # bill turned 91 holes into 528 without anything looking wrong.
            children = [c for c in bill.items
                        if not c.is_parent and not c.pre_priced
                        and c.sub_ref and c.item_ref == item.full_ref
                        and c.qty is not None
                        and (not unit or c.unit == unit)]
            if not children:
                continue
            total = sum(c.qty or 0.0 for c in children)
            refs = [c.full_ref for c in children]
            return QuantityMatch(
                role="", full_ref=item.full_ref, description=item.description,
                value=total, unit=children[0].unit, contributing=refs,
                why=(f"“{item.description}” is a heading with no quantity of its own, so this is "
                     f"{' + '.join(f'{c.full_ref} ({c.qty:g})' for c in children)} = {total:g}"))

        if unit and item.unit != unit:
            continue
        if item.qty is None:
            continue
        return QuantityMatch(
            role="", full_ref=item.full_ref, description=item.description,
            value=item.qty, unit=item.unit,
            why=f"its description matches “{pattern}” and it is measured in {item.unit}")
    return None


class ItemMapping(BaseModel):
    """How one bill item gets its cost basis."""

    full_ref: str
    description: str = ""
    unit: str = ""
    qty: Optional[float] = None
    basis_key: str = ""             # a build-up row
    lab_key: str = ""               # or a laboratory buy rate
    prelim_key: str = ""            # or a preliminaries resource standing on site
    why: str = ""
    confirmed: bool = False

    @property
    def mapped(self) -> bool:
        return bool(self.basis_key or self.lab_key or self.prelim_key)


# How a line behaves over time. Stage 6 of `docs/client_boq/how_an_estimator_works.md`: preliminaries
# are split by behaviour, not by what they are, and the bill's own unit column is what says which.
# Two estimators reading `28 mth` both call it time-related, so this is clerical and the app does it.
BEHAVIOUR_FIXED = "fixed"       # billed as `item` — set-up, taking over, dismantling
BEHAVIOUR_TIME = "time"         # billed in months or weeks — it runs for the length of the job
BEHAVIOUR_MEASURED = "measured"  # a quantity of work: nr, m, m3

BEHAVIOUR_MEANING = {
    BEHAVIOUR_FIXED: "a one-off — billed as an item, so it takes a lump sum",
    BEHAVIOUR_TIME: "runs with time — its cost is a rate times how long it stands",
    BEHAVIOUR_MEASURED: "a measured quantity — its cost is a rate times the amount",
}


def behaviour_of(item) -> str:
    """Fixed, time-related or measured, from the unit the client chose to bill it in."""
    if boq_model.days_in(item.unit):
        return BEHAVIOUR_TIME
    if item.lump or (item.unit or "").strip().lower() == "item":
        return BEHAVIOUR_FIXED
    return BEHAVIOUR_MEASURED


def _money(value: float) -> str:
    return f"HK${value:,.0f}" if abs(value) >= 100 else f"HK${value:,.2f}"


def propose_pricing(bill: ClientBill, model: CostingModel) -> list[ItemMapping]:
    """Propose a cost basis for every priceable item. Unmatched items come back named, not dropped."""
    lab = model.lab_index()
    out: list[ItemMapping] = []

    # A sub-item's meaning is in its PARENT. `2.2 Moving rigs` carries no quantity; the money is on
    # `2.2a "in Class A of site"` and `2.2b "in Class B of site"`, and `heading_path` stops at the
    # section heading — it does not include the parent item's own words. So matching on the
    # sub-item's text alone looked for "moving rigs" in "in Class A of site" and found nothing, and
    # the entire rig-move item — 91 moves on the reference tender, plus 9 more in Bill 3 — priced at
    # zero while every one of them was a real day's work. The quantity mapper already knew to look
    # up the tree (`_first_match` sums the children of 2.2); this side did not.
    parents = {item.full_ref: item.description for item in bill.items if item.is_parent}

    for item in bill.items:
        if item.is_parent:
            continue
        mapping = ItemMapping(full_ref=item.full_ref, description=item.description,
                              unit=item.unit, qty=item.qty)
        if item.pre_priced:
            mapping.why = ("the client priced this one — under the Pay for Safety Scheme it is not "
                           "yours to touch, and altering it only gets it reinstated")
            out.append(mapping)
            continue

        # The parent's words go in FRONT of the sub-item's, so "Moving rigs / in Class A of site"
        # reads the way the bill means it. Prepended rather than substituted: the sub-item still
        # says which class of site, and a pattern that keys on that keeps working.
        parent_text = parents.get(item.item_ref, "") if item.sub_ref else ""
        text = f"{parent_text} / {item.full_description()}" if parent_text else item.full_description()
        for key, pattern in _LAB_PATTERNS:
            if key in lab and re.search(pattern, text, re.I):
                mapping.lab_key = key
                mapping.why = f"a laboratory test — matched “{pattern}” to the {lab[key].label} rate"
                break

        if not mapping.mapped:
            for key, pattern, why in _BASIS_PATTERNS:
                if key in model.basis_index() and re.search(pattern, text, re.I):
                    mapping.basis_key = key
                    mapping.why = why
                    break

        # A preliminary standing on site — the office, the car, the store. Checked last, because a
        # drilling basis or a lab rate is a more specific answer than "a resource is standing here".
        if not mapping.mapped:
            for resource in model.prelims():
                if resource.match and re.search(resource.match, text, re.I):
                    mapping.prelim_key = resource.key
                    mapping.why = (f"a preliminary — matched “{resource.match}” to "
                                   f"{resource.label}, which is charged at {resource.unit}")
                    break

        if not mapping.mapped:
            mapping.why = ("nothing in the model recognised this item, so it has no cost basis. "
                           "Point it at one — an item left without a rate is deemed covered by the "
                           "other rates, which is work done for nothing for the life of the "
                           "contract (General Preambles ¶6).")
        out.append(mapping)
    return out


class PricedRow(BaseModel):
    """One row of the deliverable, in the order it is read across the sheet."""

    full_ref: str
    description: str = ""
    qty: Optional[float] = None
    unit: str = ""
    lump: bool = False
    pre_priced: bool = False

    cost_basis: Optional[float] = None      # $ per unit, before mark-up
    direct_cost: Optional[float] = None
    selling_factor: float = 1.0
    rate_raw: Optional[float] = None
    rate_rounded: Optional[float] = None
    rate_to_submit: Optional[float] = None  # the estimator's, defaulting to the rounded proposal
    amount: Optional[float] = None

    basis_key: str = ""
    lab_key: str = ""
    prelim_key: str = ""
    #: How many of the resource's own units are in one of this item's — a $/month office against a
    #: line billed in weeks is 0.23. Carried so the workbook can write the conversion as a formula
    #: against the resource cell instead of baking the converted number in.
    prelim_days: float = 1.0
    source: str = ""                        # built | lab | client | prelim | typed | unpriced
    #: How this line behaves over time, from the bill's own unit — fixed | time | measured. Stage 6
    #: of `how_an_estimator_works.md`: preliminaries are split by behaviour, not by what they are,
    #: and the unit column is what says which. Clerical, so the app does it.
    behaviour: str = ""
    #: The arithmetic behind a proposed rate, in words. A rate that cannot show its working is not
    #: auditable, and this is the screen's whole claim on an estimator's trust.
    working: str = ""
    note: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overridden(self) -> bool:
        """Whether the estimator typed over the proposal. Computed so it survives ``model_dump`` —
        the screen has to be able to show that a rate is somebody's rather than the app's."""
        return (self.rate_to_submit is not None and self.rate_rounded is not None
                and abs(self.rate_to_submit - self.rate_rounded) > 1e-9)


class PricedBQ(BaseModel):
    """The deliverable: every item, its rate, and what is not priced."""

    set_id: str = ""
    rev: int = 0
    rows: list[PricedRow] = Field(default_factory=list)
    total: float = 0.0
    unpriced: list[str] = Field(default_factory=list)
    #: Lines standing on a placeholder. While this is non-empty the total is PROVISIONAL, and
    #: everything that prints it has to say so — a number nobody chose must never be able to pass
    #: as one somebody did.
    placeholders: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def provisional(self) -> bool:
        return bool(self.placeholders)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def placeholder_total(self) -> float:
        """How much of the total nobody chose.

        The single most important number on a provisional bill, and the one a percentage cannot
        replace: a flat per-unit stand-in on a line measured in thousands produces an amount that
        swamps everything real in the bill, and without this you cannot see it happening. Read it
        beside ``total`` — the difference is the part that has actually been priced.
        """
        placed = set(self.placeholders)
        return sum(r.amount or 0.0 for r in self.rows if r.full_ref in placed)

    def index(self) -> dict[str, PricedRow]:
        return {row.full_ref: row for row in self.rows}


def price(bill: ClientBill, model: CostingModel, programme: Programme, buildup: Buildup,
          mappings: Optional[list[ItemMapping]] = None,
          submitted: Optional[dict[str, float]] = None) -> PricedBQ:
    """Price the bill. ``submitted`` carries any rate the estimator typed over the proposal."""
    mappings = mappings if mappings is not None else propose_pricing(bill, model)
    by_ref = {m.full_ref: m for m in mappings}
    overrides = submitted or {}
    lab = model.lab_index()
    prelims = model.prelim_index()
    factor = buildup.selling_factor

    result = PricedBQ(set_id=bill.set_id, rev=bill.rev, problems=list(buildup.problems))

    for item in bill.items:
        if item.is_parent:
            continue
        mapping = by_ref.get(item.full_ref, ItemMapping(full_ref=item.full_ref))
        row = PricedRow(full_ref=item.full_ref, description=item.description, qty=item.qty,
                        unit=item.unit, lump=item.lump, pre_priced=item.pre_priced,
                        basis_key=mapping.basis_key, lab_key=mapping.lab_key,
                        prelim_key=mapping.prelim_key, behaviour=behaviour_of(item),
                        selling_factor=factor)

        if item.pre_priced:
            # Carried through untouched: GCT App C 2.2(vi) reinstates an altered Employer rate.
            row.source = "client"
            row.rate_to_submit = item.client_rate
            row.amount = (item.client_amount if item.client_amount is not None
                          else _extend(item, item.client_rate))
            row.note = "priced by the client — not yours to touch"
            result.rows.append(row)
            continue

        if mapping.lab_key and mapping.lab_key in lab:
            row.cost_basis = lab[mapping.lab_key].rate
            row.source = "lab"
        elif mapping.basis_key:
            row.cost_basis = buildup.cost_per_unit(mapping.basis_key)
            row.source = "built"
        elif mapping.prelim_key and mapping.prelim_key in prelims:
            resource = prelims[mapping.prelim_key]
            per_unit = model.prelim_rate_for(resource, item.unit)

            if per_unit is None and row.behaviour == BEHAVIOUR_FIXED:
                # "Taking over" and "Dismantling" ARE the site office — its one-off ends, billed as
                # `item`. A monthly rate cannot produce a lump, and guessing a number of months
                # would be inventing the estimator's judgement. Name the resource and ask.
                #
                # Tested BEFORE the missing-rate branch on purpose: on a line the resource can
                # never price, "enter the rate and every line using it prices itself" is untrue,
                # and sending somebody off to find a number that will not help is worse than
                # saying plainly that this one takes a lump.
                row.note = (f"the one-off end of {resource.label}, billed as an item — "
                            f"a {resource.unit} rate cannot give a lump, so this is your number. "
                            f"Note SMM S01 ¶1.01A: item lines are paid in monthly instalments "
                            f"at rates the Project Manager sets, so it cannot be front-loaded.")
            elif per_unit is None:
                row.note = (f"{resource.label} is charged at {resource.unit} and this item is "
                            f"measured in {item.unit!r} — those cannot be reconciled, so no "
                            f"rate was proposed. Point it at a different resource, or price it.")
            elif resource.rate <= 0:
                # The resource exists and nobody has said what it costs them. Naming the resource
                # is far more use than "no cost basis": it turns a hundred unknowns into one number
                # to go and find, and it is the same number for every line that uses it.
                row.note = (f"{resource.label} has no rate yet. Enter what it costs you "
                            f"({resource.unit}) and every line using it prices itself.")
            else:
                row.cost_basis = per_unit
                row.source = "prelim"
                own = boq_model.days_in((resource.unit or "").removeprefix("$/"))
                mine = boq_model.days_in(item.unit)
                row.prelim_days = round(mine / own, 6) if (own and mine) else 1.0
                row.working = (
                    f"{resource.label} at {_money(resource.multiplier * resource.rate)}"
                    f"{resource.unit.removeprefix('$')} = {_money(per_unit)} per {item.unit}"
                    + (f" × {item.qty:,.0f} {item.unit}" if item.qty else ""))

        if row.cost_basis is None:
            # A rate typed by hand is a SELLING rate: the estimator has already made the commercial
            # judgement, so it is not marked up again. Before this the function returned here, which
            # meant a line with no derived cost silently discarded whatever anyone entered — the app
            # named 102 decisions and threw away every answer.
            typed = overrides.get(item.full_ref)
            if typed is not None:
                row.source = "typed"
                row.rate_to_submit = typed
                row.amount = _extend(item, typed)
                row.note = row.note or "priced by hand — no model basis, so this is your number"
                result.rows.append(row)
                continue

            # Last resort: a stand-in for the SHAPE of the line, so a bill reads end to end while
            # the real numbers are being found. Checked after a typed rate, never before — a
            # placeholder that could overwrite somebody's decision would be the worst bug in here.
            stand_in = model.placeholder_for(item.unit)
            if stand_in is not None:
                row.cost_basis = stand_in.rate
                row.source = "placeholder"
                # The reason this line could not be priced is worth MORE than the placeholder, so
                # it is kept and the warning goes in front of it rather than replacing it.
                row.note = f"{boq_model.PLACEHOLDER_NOTE} {row.note}".strip()
                row.working = (f"stand-in for a line measured in {item.unit or 'no unit'} "
                               f"({stand_in.label}) — replace it")
                result.placeholders.append(item.full_ref)
            else:
                row.source = "unpriced"
                row.note = row.note or (
                    "no cost basis. General Preambles ¶6 deems an item against which no rate is "
                    "entered covered by the other rates — it becomes work done for nothing, for "
                    "the life of the contract.")
                result.unpriced.append(item.full_ref)
                result.rows.append(row)
                continue

        row.direct_cost = (row.cost_basis if item.qty is None else item.qty * row.cost_basis)
        row.rate_raw = row.cost_basis * factor
        row.rate_rounded = model.round_rate(row.rate_raw)
        row.rate_to_submit = overrides.get(item.full_ref, row.rate_rounded)
        row.amount = _extend(item, row.rate_to_submit)
        result.rows.append(row)

    result.total = sum(r.amount or 0.0 for r in result.rows)
    if result.placeholders:
        result.problems.append(
            f"{len(result.placeholders)} item(s) are standing on a placeholder, so this total is "
            f"PROVISIONAL. A placeholder is a stand-in for the shape of a line, not an estimate of "
            f"it — replace each one before this goes anywhere near a tender.")
    if result.unpriced:
        result.problems.append(
            f"{len(result.unpriced)} item(s) have no cost basis: {', '.join(result.unpriced[:6])}"
            f"{'…' if len(result.unpriced) > 6 else ''}")
    return result


def _extend(item: BillItem, rate: Optional[float]) -> Optional[float]:
    """Quantity times rate — except for a lump item, where the amount **is** the rate.

    SMM Corrigendum 1/2007 Part III ¶3: for an "item" the amount inserted by the tenderer is deemed
    to be the rate, and the rate column prints a dash.
    """
    if rate is None:
        return None
    if item.lump or item.qty is None:
        return rate
    return item.qty * rate
