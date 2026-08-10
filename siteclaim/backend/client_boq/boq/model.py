"""BOQ — the costing model: everything the engine does, as data you can change.

Bucket: **Human.** Not one number here is derived. This is the object an estimator owns.

THE IDEA
--------
The engine has no opinions of its own. Which production bands exist, which resources stand on site
and what share of each this job carries, which bill item is built from which driver, what the mark-up
chain is and in what order, how a rate is rounded — all of it is **data on this object**, and all of
it is editable.

What is *not* editable is the arithmetic joining them: cost per rig-day is always the sum of its
lines, a rate is always a cost over a divisor, the chain is always a product. That is the trade, and
it is deliberate. A model whose formulas change every time can be neither checked nor defended, and
the whole argument of this product is that a person can check it in three clicks. If you want
arbitrary formulas you already have Excel — and this engine writes you one.

WHERE A MODEL LIVES
-------------------
Copy-on-write, no ceremony:

* the **library** holds the model your company works from
* a **tender** holds nothing until somebody edits it there, meaning *use the library's*
* the first edit on a tender **copies the model onto that tender**, and from then on the tender owns
  it — the library is untouched and no other tender moves

:func:`compare` then derives the ⟨BOOK⟩ / ⟨YOURS⟩ marks by walking the two objects field by field, so
every divergence is visible without storing a single extra row.

THE DEFAULTS
------------
:func:`default_model` reproduces ``GI_Costing_Template.xlsx`` exactly. That is a starting point and a
regression fixture, **not a rule** — every value and every row below can be changed, and the app never
objects.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from client_boq.boq.empirical import DEFAULT_BANDS, FITTED, BandTable

# ---------------------------------------------------------------------------
# How a resource is charged
# ---------------------------------------------------------------------------
# The distinction the template draws and the engine must not blur: one of these scales with the
# number of rigs and the other does not. Merging them prices supervision per rig, which is wrong in
# the direction that loses money on a multi-rig job.
CHARGE_RIG_DAY = "rig_day"              # A — plant, labour, consumables. Scales with rigs.
CHARGE_CONTRACT_DAY = "contract_day"    # B — the SITE team. Manages ONE SITE, not the rigs.
# B2 — the GFT (ground/field technician team). A DIFFERENT resource from the site team, and the
# distinction is the whole of this block: the site team (engineer + foreman + geologist + PM)
# manages a SITE and its count follows the number of sites, not the rig count; the GFT manages
# RIGS at one per `gft_ratio` of them. Charging one resource for both jobs priced site management
# per rig — which over-recovers on a one-rig job and under-recovers on a seven-rig one, in the
# direction nobody notices until the job is finished.
CHARGE_GFT = "gft"                      # B2 — scales with the RIG count, at 1 per gft_ratio rigs
CHARGE_NONE = "none"                    # priced elsewhere; kept on the sheet for visibility
# C — a preliminary standing on site that is billed as its OWN item: the office, a vehicle, the
# telephone, the core store. It prices those Bill 1 lines directly and must never reach
# `cost_per_rig_day` or `cost_per_contract_day`, because a drilling rate built off a day-cost that
# already contains the site office would charge the office twice — once inside every metre drilled
# and again on the line the client asked for it on.
CHARGE_PRELIM = "prelim"

# Every charge class there is, in the order a reader meets them. Declared like `DRIVERS` and for
# the same reason: a class the rest of the app has never heard of renders under a blank heading and
# sums into nothing. Anything that maps over the classes maps over THIS.
CHARGES = (CHARGE_RIG_DAY, CHARGE_CONTRACT_DAY, CHARGE_GFT, CHARGE_PRELIM, CHARGE_NONE)

# Units a bill uses for a resource that runs with time, and how many of them are in a day. The
# bill's own unit column is what separates a time-related preliminary from a one-off — see
# `docs/client_boq/how_an_estimator_works.md` Stage 6 — so this table is the classifier, not a guess.
DAYS_PER_UNIT: dict[str, float] = {
    "day": 1.0, "dy": 1.0,
    "wk": 7.0, "week": 7.0, "nr-wk": 7.0,
    "mth": 30.4375, "month": 30.4375, "nr-mth": 30.4375,   # 365.25 / 12
}


def days_in(unit: str) -> float:
    """Calendar days in one of the bill's time units, or 0.0 if the unit is not a duration."""
    return DAYS_PER_UNIT.get((unit or "").strip().lower(), 0.0)


class SpreadLine(BaseModel):
    """One resource standing on site, and what share of it this job carries.

    ``multiplier`` is the coefficient — a standby factor on plant, a headcount on labour, an
    allocation on a shared person. It is the single most useful column on a costing sheet and the one
    that makes a project manager split across three contracts chargeable without fiction.
    """

    key: str
    label: str
    block: str = "PLANT"                # how it groups on the sheet
    multiplier: float = 1.0
    rate: float = 0.0                   # $ per day
    unit: str = "$/day"
    charge: str = CHARGE_RIG_DAY
    note: str = ""
    #: Regex against a bill item's description, for a resource billed as its own item. Empty on the
    #: rig and site-team lines, which are recovered through drilling rates and never matched to a
    #: bill line directly. Kept on the resource so adding one teaches the app to find it.
    match: str = ""

    def cost_per_day(self) -> float:
        return self.multiplier * self.rate


class PlaceholderRate(BaseModel):
    """A stand-in rate for a line nothing in the model can price, keyed on how it is MEASURED.

    Not an estimate. A line measured in ``m3`` gets the m3 placeholder whether it is a trial pit or
    a soil heap, because the only thing the app actually knows about it is its shape. That is the
    point: it keys on the unit rather than on the wording, so the same short table fills in any bill
    somebody inserts tomorrow instead of only the one it was written against.

    Everything priced this way is marked ``placeholder`` and counted, and the total says so. A
    number nobody chose must never be able to pass as a number somebody did.
    """

    unit: str                        # the bill's unit, lower-cased. "" is the catch-all.
    rate: float = 0.0                # a COST, marked up like any other
    label: str = ""


# Deliberately round, deliberately visible. These are the right ORDER of magnitude for a Hong Kong
# ground-investigation bill and nothing more — they exist so a tender reads end to end while the
# real numbers are being found, and every one of them is wrong for your job.
#
# Sized against the QUANTITIES a GI bill actually carries, not picked as round numbers in the
# abstract. The reference tender bills 2,451 ``nr-wk`` of standpipe reading; at a plausible-sounding
# $3,000/week that one line alone comes to HK$7.35M and swamps the whole bill. A stand-in whose
# total drowns out the priced work is worse than a red line, because red is honest and a wrong total
# is not. The per-week and per-month "one of something standing there" rates are therefore small.
_PLACEHOLDER = [
    ("item", 25000.0, "a one-off lump"),
    ("nr", 400.0, "each"),
    ("m", 300.0, "per metre"),
    ("m2", 250.0, "per square metre"),
    ("m3", 400.0, "per cubic metre"),
    ("h", 250.0, "per hour"),
    ("t", 500.0, "per tonne"),
    ("kg", 20.0, "per kilogram"),
    ("mth", 12000.0, "per month — something running for a month"),
    ("wk", 3000.0, "per week — something running for a week"),
    ("nr-wk", 60.0, "ONE of something, standing for ONE week"),
    ("nr-mth", 250.0, "ONE of something, standing for ONE month"),
    ("", 800.0, "anything else"),
]

PLACEHOLDER_NOTE = ("PROVISIONAL — a placeholder for the shape of this line, not an estimate of it. "
                    "Nobody has priced this.")


class LabRate(BaseModel):
    """A laboratory test bought in. Marked up like anything else, never a cost centre of its own."""

    key: str
    label: str
    rate: float = 0.0
    note: str = "Subcontract buy rate. Confirm against current lab quotation."


# ---------------------------------------------------------------------------
# How a bill item is built
# ---------------------------------------------------------------------------
# A small, closed set on purpose. These are the shapes a ground investigation item actually takes;
# which one an item uses is the editable part.
DRIVER_SOIL_DAYS = "soil_days"          # spread cost over the soil-drilling share of the programme
DRIVER_ROCK_DAYS = "rock_days"
DRIVER_SETUP_DAYS = "setup_days"        # the fixed per-hole set-up share
DRIVER_STANDING_DAYS = "standing_days"  # idle time, charged at the spread day-cost
DRIVER_SITE_TEAM = "site_team"          # the per-SITE team, recovered in Bill 1
DRIVER_GFT = "gft"                      # the per-RIG-GROUP technician team, recovered in Bill 1
DRIVER_FIXED = "fixed"                  # a one-off: mobilisation
DRIVER_PER_HOLE = "per_hole"            # a rate applied once per hole: setting out
DRIVER_MATERIAL = "material"            # a derived quantity times a unit cost
DRIVERS = (DRIVER_SOIL_DAYS, DRIVER_ROCK_DAYS, DRIVER_SETUP_DAYS, DRIVER_STANDING_DAYS,
           DRIVER_SITE_TEAM, DRIVER_GFT, DRIVER_FIXED, DRIVER_PER_HOLE, DRIVER_MATERIAL)

DIVISOR_SOIL_M = "soil_m"
DIVISOR_ROCK_M = "rock_m"               # rock + artificial hard material
DIVISOR_HOLES = "holes"
DIVISOR_STANDING_H = "standing_hours"
DIVISOR_CONTRACT_MONTHS = "contract_months"
DIVISOR_QTY = "qty"                     # the driver's own quantity — a material's own count
DIVISOR_NONE = "none"                   # a lump: the amount is the rate
DIVISORS = (DIVISOR_SOIL_M, DIVISOR_ROCK_M, DIVISOR_HOLES, DIVISOR_STANDING_H,
            DIVISOR_CONTRACT_MONTHS, DIVISOR_QTY, DIVISOR_NONE)

# Which derived material quantity a DRIVER_MATERIAL row consumes.
MATERIAL_TUBES = "soil_tubes"
MATERIAL_BOXES = "core_boxes"
MATERIAL_GROUT = "grout_litres"


class FixedComponent(BaseModel):
    """One part of a one-off cost: a rate and how many of it. Mobilisation is two of these.

    Held as a list so a third can be added — a barge, a night-work escort — without a code change.
    """

    label: str = ""
    rate_key: str = ""
    qty_key: str = ""


class ItemBasis(BaseModel):
    """One row of the build-up: a cost driver, a divisor, and what it produces a rate per."""

    key: str
    label: str
    driver: str = DRIVER_SOIL_DAYS
    divisor: str = DIVISOR_SOIL_M
    material: str = ""                  # for DRIVER_MATERIAL
    unit_cost_key: str = ""             # which model input supplies the unit cost
    components: list[FixedComponent] = Field(default_factory=list)   # for DRIVER_FIXED
    note: str = ""


# ---------------------------------------------------------------------------
# The mark-up chain
# ---------------------------------------------------------------------------
# Two kinds, because they are genuinely different arithmetic and the difference is money:
#   a loading adds to cost           →  factor = 1 + v
#   a margin is taken on the selling price →  factor = 1 / (1 - v)
# Ten percent as a loading is x1.10. Ten percent as a margin is x1.111. Confusing them under-recovers.
MARKUP_LOADING = "loading"
MARKUP_ON_SELLING = "on_selling"
MARKUP_KINDS = (MARKUP_LOADING, MARKUP_ON_SELLING)


class MarkupStep(BaseModel):
    """One step of the chain. ``components`` are input keys, summed before the factor is formed."""

    key: str
    label: str
    kind: str = MARKUP_LOADING
    components: list[str] = Field(default_factory=list)

    def rate(self, inputs: dict[str, float]) -> float:
        return sum(float(inputs.get(name, 0.0)) for name in self.components)

    def factor(self, inputs: dict[str, float]) -> float:
        value = self.rate(inputs)
        if self.kind == MARKUP_ON_SELLING:
            if value >= 1.0:
                raise ValueError(
                    f"{self.label}: a margin of {value:.0%} taken on the selling price is not a "
                    f"number — at 100% the price is infinite. Use a loading, or a margin below 1.")
            return 1.0 / (1.0 - value)
        return 1.0 + value


class RoundingStep(BaseModel):
    """One rung of the rounding ladder: at or above ``threshold``, round to ``decimals`` places.

    Negative decimals round left of the point, as Excel's ROUND does — ``-2`` is the nearest hundred.
    """

    threshold: float = 0.0
    decimals: int = 0


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------
class MethodSettings(BaseModel):
    """Which production method prices the job, and when the two disagreeing means stop.

    Method A is the banded lookup; Method B is the split-rate fit. B is a **cross-check**: the
    template's own words are *"If A and B diverge, do not price."*
    """

    basis: str = "banded"                       # "banded" | "split"
    divergent_threshold: float = 0.25           # above this, do not price
    marginal_threshold: float = 0.15            # above this, worth a second look
    depth_departure_threshold: float = 0.30     # band extrapolation warning


class CostingModel(BaseModel):
    """Everything the engine does. One object, all of it editable."""

    name: str = "GI drilling"
    note: str = ""

    # Sheet 01 scalars, keyed so a screen and the workbook writer can both walk them.
    inputs: dict[str, float] = Field(default_factory=dict)

    bands: BandTable = Field(default_factory=lambda: DEFAULT_BANDS.model_copy(deep=True))
    method: MethodSettings = Field(default_factory=MethodSettings)
    spread: list[SpreadLine] = Field(default_factory=list)
    laboratory: list[LabRate] = Field(default_factory=list)
    basis_rows: list[ItemBasis] = Field(default_factory=list)
    markup: list[MarkupStep] = Field(default_factory=list)
    #: Stand-ins for lines nothing else can price, so a bill reads end to end while the real
    #: numbers are being found. Every one is marked and counted.
    #:
    #: Defaults to the standard table rather than to nothing, so a model SAVED BEFORE this existed
    #: gains it on load instead of silently losing the feature — measured on the live ND/2025/04
    #: tender, whose own model was written an hour earlier and came back with no stand-ins at all.
    #: "I want none" is said with `use_placeholders`, which is a switch somebody set on purpose,
    #: not with an empty list, which is indistinguishable from a field that was never written.
    placeholders: list[PlaceholderRate] = Field(
        default_factory=lambda: [PlaceholderRate(unit=unit, rate=rate, label=label)
                                 for unit, rate, label in _PLACEHOLDER])
    #: Turn the stand-ins off to see the bill as it honestly stands — every unpriced line red,
    #: nothing invented. The choice is the estimator's, so it lives in the model like everything
    #: else rather than being a constant somebody has to find in the code.
    use_placeholders: bool = True
    rounding: list[RoundingStep] = Field(default_factory=list)

    # ------------------------------------------------------------------ access
    def value(self, key: str, default: float = 0.0) -> float:
        return float(self.inputs.get(key, default))

    def retired(self) -> list[tuple[str, float, str]]:
        """Inputs this model still carries that nothing reads any more. ``(key, value, why)``.

        Not repaired here — see ``RETIRED_INPUTS``. Reporting one is the whole job: the value is
        already inert, and deleting it would be an edit of somebody's model that they never made.
        """
        return [(key, float(self.inputs[key]), why)
                for key, why in RETIRED_INPUTS.items() if key in self.inputs]

    def spread_index(self) -> dict[str, SpreadLine]:
        return {line.key: line for line in self.spread}

    def lab_index(self) -> dict[str, LabRate]:
        return {row.key: row for row in self.laboratory}

    def basis_index(self) -> dict[str, ItemBasis]:
        return {row.key: row for row in self.basis_rows}

    def placeholder_for(self, item_unit: str) -> Optional[PlaceholderRate]:
        """The stand-in for a line measured this way, or the catch-all, or nothing.

        Nothing when the table is empty or the stand-ins are switched off — an absent placeholder
        must leave the line red rather than quietly priced at zero, which would look identical to a
        decision and cost the job under General Preambles ¶6.
        """
        if not self.use_placeholders or not self.placeholders:
            return None
        wanted = (item_unit or "").strip().lower()
        by_unit = {row.unit.strip().lower(): row for row in self.placeholders}
        return by_unit.get(wanted) or by_unit.get("")

    def prelims(self) -> list[SpreadLine]:
        """The resources billed as their own items — the office, the car, the store."""
        return [row for row in self.spread if row.charge == CHARGE_PRELIM]

    def prelim_index(self) -> dict[str, SpreadLine]:
        return {row.key: row for row in self.prelims()}

    def prelim_rate_for(self, resource: SpreadLine, item_unit: str) -> Optional[float]:
        """What one of the BILL's units costs, from a resource priced in its own unit.

        On a preliminaries line ``rate`` is per the resource's OWN unit — ``$/month`` means a
        month — unlike the rig and site-team lines, where it is per day. That is why this converts
        through ``unit`` rather than through :meth:`SpreadLine.cost_per_day`, which would read a
        monthly figure as a daily one and price the site office at a thirtieth of its cost.

        ``$/month`` against ``28 mth`` is a month. ``$/week`` against ``122 nr-wk`` is a week — the
        ``nr-`` prefix counts how many are running, and the quantity already carries that, so it
        does not enter the rate. A count against a count is one each.

        ``None`` when the two cannot be reconciled — a ``$/month`` office against an item measured
        in ``m3`` is a mapping mistake, and inventing a conversion would bury it.
        """
        per_own_unit = resource.multiplier * resource.rate
        resource_days = days_in((resource.unit or "").removeprefix("$/"))
        item_days = days_in(item_unit)
        if resource_days and item_days:
            return per_own_unit * item_days / resource_days
        if not resource_days and not item_days:
            return per_own_unit                 # a count against a count: one each
        return None

    def cost_per_rig_day(self) -> float:
        """A — plant, labour and consumables, coefficients applied. Scales with the rig count."""
        return sum(l.cost_per_day() for l in self.spread if l.charge == CHARGE_RIG_DAY)

    def cost_per_contract_day(self) -> float:
        """B — ONE site team, per day. Its COUNT follows the number of sites, never the rigs."""
        return sum(l.cost_per_day() for l in self.spread if l.charge == CHARGE_CONTRACT_DAY)

    def cost_per_gft_day(self) -> float:
        """B2 — ONE GFT, per day. Its COUNT follows the rig count, at 1 per ``gft_ratio`` rigs."""
        return sum(l.cost_per_day() for l in self.spread if l.charge == CHARGE_GFT)

    def selling_factor(self) -> float:
        """The chain, multiplied out in the order the model lists it."""
        factor = 1.0
        for step in self.markup:
            factor *= step.factor(self.inputs)
        return factor

    def round_rate(self, value: float) -> float:
        """Apply the ladder — the highest threshold the value clears wins."""
        if value is None:
            return value
        chosen = None
        for step in sorted(self.rounding, key=lambda s: s.threshold):
            if value >= step.threshold:
                chosen = step
        if chosen is None:
            return round(value, 2)
        return round(value, chosen.decimals)

    # ------------------------------------------------------------------ checks
    def problems(self) -> list[str]:
        """What would stop this model pricing. Empty means it will run.

        Reported rather than corrected. A model somebody edited into an unusable state is a thing
        they did on purpose and can undo; a model the app silently repaired is a number nobody can
        account for.
        """
        out = list(self.bands.problems())
        if not self.spread:
            out.append("the spread has no resources, so a day on site costs nothing")
        elif self.cost_per_rig_day() <= 0:
            out.append("no resource is charged per rig-day, so drilling costs nothing")
        if not self.basis_rows:
            out.append("no item bases are defined, so no bill item can be built up")
        for row in self.basis_rows:
            if row.driver not in DRIVERS:
                out.append(f"{row.label!r} uses driver {row.driver!r}, which is not one of "
                           f"{', '.join(DRIVERS)}")
            if row.divisor not in DIVISORS:
                out.append(f"{row.label!r} divides by {row.divisor!r}, which is not one of "
                           f"{', '.join(DIVISORS)}")
        for step in self.markup:
            if step.kind not in MARKUP_KINDS:
                out.append(f"mark-up step {step.label!r} is {step.kind!r}; it must be "
                           f"{' or '.join(MARKUP_KINDS)}")
            elif step.kind == MARKUP_ON_SELLING and step.rate(self.inputs) >= 1.0:
                out.append(f"{step.label!r} takes {step.rate(self.inputs):.0%} on the selling price, "
                           f"which has no finite answer")
        # A KEY THAT RESOLVES TO NOTHING PRICES AT ZERO, SILENTLY. `value()` defaults an absent
        # input to 0.0 — the right behaviour for an optional knob, and exactly the wrong one for a
        # typo: a mark-up component misspelt by one letter took the whole risk loading out of the
        # selling factor (probed: ×1.278 instead of ×1.342) and nothing anywhere said so. The same
        # read prices a material or a mobilisation component at $0. So every key a step or a basis
        # row NAMES has to actually exist; a missing one is a configuration fault to report, never
        # a zero to substitute.
        for step in self.markup:
            for name in step.components:
                if name not in self.inputs:
                    out.append(f"mark-up step {step.label!r} reads input {name!r}, which does not "
                               f"exist — it would silently contribute 0% to the chain")
        for row in self.basis_rows:
            if row.unit_cost_key and row.unit_cost_key not in self.inputs:
                out.append(f"{row.label!r} takes its unit cost from input {row.unit_cost_key!r}, "
                           f"which does not exist — it would silently price at $0")
            for component in row.components:
                if component.rate_key and component.rate_key not in self.inputs:
                    out.append(f"{row.label!r} component {component.label or component.rate_key!r} "
                               f"reads rate input {component.rate_key!r}, which does not exist — "
                               f"it would silently price at $0")
                if component.qty_key and component.qty_key not in self.inputs:
                    out.append(f"{row.label!r} component {component.label or component.qty_key!r} "
                               f"reads quantity input {component.qty_key!r}, which does not exist")
        return out

    def usable(self) -> bool:
        return not self.problems()


# ---------------------------------------------------------------------------
# Comparing a tender's model against the library's
# ---------------------------------------------------------------------------
SOURCE_BOOK = "book"
SOURCE_YOURS = "yours"


def compare(library: CostingModel, tender: Optional[CostingModel]) -> dict[str, str]:
    """Which parts of the effective model this tender has changed.

    Returns dotted paths to ``book`` or ``yours`` — ``inputs.margin``, ``bands``, ``spread.rig``.
    Derived by walking the two objects rather than stored, so it can never drift out of step with
    what is actually being priced.
    """
    if tender is None:
        return {}
    marks: dict[str, str] = {}

    for key in sorted({*library.inputs, *tender.inputs}):
        same = library.inputs.get(key) == tender.inputs.get(key)
        marks[f"inputs.{key}"] = SOURCE_BOOK if same else SOURCE_YOURS

    for field in ("bands", "method", "markup", "rounding", "laboratory", "basis_rows"):
        marks[field] = (SOURCE_BOOK if _same(getattr(library, field), getattr(tender, field))
                        else SOURCE_YOURS)

    lib_spread, ten_spread = library.spread_index(), tender.spread_index()
    for key in sorted({*lib_spread, *ten_spread}):
        marks[f"spread.{key}"] = (SOURCE_BOOK if _same(lib_spread.get(key), ten_spread.get(key))
                                  else SOURCE_YOURS)
    return marks


def _same(a: Any, b: Any) -> bool:
    dump = lambda v: [x.model_dump() for x in v] if isinstance(v, list) else (
        v.model_dump() if isinstance(v, BaseModel) else v)
    return dump(a) == dump(b)


def effective(library: CostingModel, tender: Optional[CostingModel]) -> CostingModel:
    """The model actually pricing this tender. Copy-on-write: the tender's if it has one."""
    return tender if tender is not None else library


# ---------------------------------------------------------------------------
# What each input IS — declared once, read by the workbook AND by the screen
# ---------------------------------------------------------------------------
# `inputs` is a bare `dict[str, float]`, which is right for the engine and useless for a human: a
# key and a number say nothing about what the number means, what it is measured in, or whether 0.1
# is ten percent or a tenth of a metre. The workbook already knew all of that — it was written into
# the writer as literal argument lists, where nothing else could reach it. So a screen that lets
# somebody edit the model would have needed a SECOND copy of the same knowledge, and the two would
# have drifted the first time an input was added.
#
# Declared here instead, and read by both. `test_the_costing_model_is_editable.py` fails if an
# input exists with no spec or a spec names an input that does not exist, so a new knob cannot be
# added invisibly.
INPUT_BLOCKS: tuple[str, ...] = (
    "CONTRACT",
    "PRODUCTIVITY",
    "SPLIT-RATE CROSS-CHECK  (Method B — not the pricing basis)",
    "COMMERCIAL",
    "ORGANISATION",
    "MATERIALS",
    "MOBILISATION",
)


class InputSpec(BaseModel):
    """What one scalar input is, in the terms a person needs to edit it."""

    key: str
    label: str
    block: str
    unit: str = ""
    note: str = ""
    #: Held as a fraction, said out loud as a percentage. The screen and the sheet both format it;
    #: nothing converts it, because the stored value never changes.
    percent: bool = False
    #: The template's highlight — the handful that move the answer most.
    key_assumption: bool = False


def _spec(key, label, block, unit="", note="", percent=False, key_assumption=False) -> InputSpec:
    return InputSpec(key=key, label=label, block=block, unit=unit, note=note, percent=percent,
                     key_assumption=key_assumption)


_CONTRACT, _PRODUCTIVITY = INPUT_BLOCKS[0], INPUT_BLOCKS[1]
_METHOD_B, _COMMERCIAL = INPUT_BLOCKS[2], INPUT_BLOCKS[3]
_ORGANISATION, _MATERIALS, _MOBILISATION = INPUT_BLOCKS[4], INPUT_BLOCKS[5], INPUT_BLOCKS[6]

INPUT_SPECS: tuple[InputSpec, ...] = (
    _spec("contract_period_months", "Contract period", _CONTRACT, "month"),
    _spec("working_days_per_month", "Working days per month", _CONTRACT, "day",
          "6-day week, HK civils norm."),

    _spec("residual_site_factor", "Residual site factor", _PRODUCTIVITY, "x",
          "What is left AFTER the rock-fraction band. 1.00 means the band explains the site. "
          "Raise it only for a named reason, recorded on the assumptions register.",
          key_assumption=True),
    _spec("calendar_to_work_day", "Calendar : work-day ratio", _PRODUCTIVITY, "x",
          "Observed 1.18 / 1.18 / 1.36. Weather lands here — it costs programme, not production."),
    _spec("standing_allowance", "Standing / idle allowance", _PRODUCTIVITY, "of work-days",
          "Observed 18%–36%. Drives the standing time item.", percent=True, key_assumption=True),
    _spec("p90_multiplier", "Productivity band — P90 multiplier", _PRODUCTIVITY, "x"),
    _spec("p10_multiplier", "Productivity band — P10 multiplier", _PRODUCTIVITY, "x"),
    _spec("hours_per_day", "Hours per working day", _PRODUCTIVITY, "h"),

    _spec("setup_days_per_hole", "Fixed set-up time per hole", _METHOD_B, "work-day",
          "Regression intercept. Used only for the cross-check."),
    _spec("soil_m_per_day", "Soil production rate", _METHOD_B, "m/work-day"),
    _spec("rock_m_per_day", "Rock production rate", _METHOD_B, "m/work-day"),

    _spec("margin", "Direct margin", _COMMERCIAL, "",
          "Taken on the selling price, not added to cost — 10% is x1.111, not x1.100.",
          percent=True, key_assumption=True),
    _spec("overhead_local", "Local overhead", _COMMERCIAL, "",
          "Site + local office establishment.", percent=True),
    _spec("overhead_regional", "Regional overhead", _COMMERCIAL, "", percent=True),
    _spec("overhead_international", "International overhead", _COMMERCIAL, "", percent=True),
    _spec("nec_fee", "NEC fee percentage", _COMMERCIAL, "",
          "Applies to compensation-event Defined Cost, NOT to the BQ rates.", percent=True),
    _spec("risk_loading", "Risk / contingency loading", _COMMERCIAL, "",
          "Priced-in allowance for the productivity spread. See the P90 column.", percent=True),

    _spec("site_count", "Number of sites", _ORGANISATION, "nr",
          "The site team is carried per site, not per rig."),
    _spec("site_team_per_site", "Site teams per site", _ORGANISATION, "nr",
          "A coefficient: 1.0 dedicated, 0.5 shared with another contract. Deliberately NOT "
          "rounded up — rounding invents a team nobody employs."),
    _spec("gft_ratio", "One GFT supervises", _ORGANISATION, "rigs",
          "The GFT manages RIGS, at one per this many. A different resource from the site team, "
          "which manages a site and does not move with the rig count.", key_assumption=True),

    _spec("mazier_interval_m", "Mazier sample interval", _MATERIALS, "m"),
    _spec("mazier_sample_length_m", "Mazier sample length", _MATERIALS, "m"),
    _spec("soil_tube_cost", "Soil tube — unit cost", _MATERIALS, "$/nr"),
    _spec("core_box_cost", "Wooden core box — unit cost", _MATERIALS, "$/nr"),
    _spec("soil_box_capacity_m", "Soil box capacity", _MATERIALS, "m/box"),
    _spec("rock_box_capacity_m", "Rock box capacity", _MATERIALS, "m/box"),
    _spec("grout_hole_diameter_m", "Grout hole diameter", _MATERIALS, "m"),
    _spec("grout_cost_per_litre", "Cement grout — unit cost", _MATERIALS, "$/L"),

    _spec("crane_lorry_rate", "Crane lorry", _MOBILISATION, "$/day"),
    _spec("crane_lorry_days", "Crane lorry days", _MOBILISATION, "day"),
    _spec("truck_rate", "Truck (equipment)", _MOBILISATION, "$/day"),
    _spec("truck_days", "Truck days", _MOBILISATION, "day"),
    _spec("survey_per_location", "Surveying / setting out", _MOBILISATION, "$/location"),
)

INPUT_SPEC_INDEX: dict[str, InputSpec] = {spec.key: spec for spec in INPUT_SPECS}


def specs_in(block: str) -> list[InputSpec]:
    """Every input declared under one block, in declaration order."""
    return [spec for spec in INPUT_SPECS if spec.block == block]


# ---------------------------------------------------------------------------
# Inputs that no longer control anything
# ---------------------------------------------------------------------------
# A tender model saved before a split or a rename keeps whatever keys it was saved with. Deleting
# the key on load would be a silent edit of somebody's model; leaving it unmentioned would let them
# keep tuning a number that stopped being read. So: nothing reads these — a stale value cannot move
# a single figure, which is the whole of "harmless" — and the register carries a row per stale key
# saying what replaced it. The row starts blank like every other, so the register reads NOT CLEARED
# until a person has actually looked at it.
RETIRED_INPUTS: dict[str, str] = {
    "site_team_supervises_rigs": (
        "It scaled the SITE team by ceil(rigs / this), which treated the site team and the GFT as "
        "one resource. They are two: the site team manages a site (`site_count` x "
        "`site_team_per_site`, independent of rigs) and the GFT manages rigs (`gft_ratio`, "
        "default 6). Nothing reads this key any more, so the value here changes nothing — set "
        "`gft_ratio` if you meant the 6:1 supervision rule."),
}


# ---------------------------------------------------------------------------
# The defaults — GI_Costing_Template.xlsx, reproduced
# ---------------------------------------------------------------------------
DEFAULT_INPUTS: dict[str, float] = {
    # CONTRACT
    "contract_period_months": 20.0,
    "working_days_per_month": 26.0,
    # PRODUCTIVITY
    "residual_site_factor": 1.0,
    "calendar_to_work_day": 1.18,
    "standing_allowance": 0.22,
    "p90_multiplier": 1.55,
    "p10_multiplier": 0.62,
    # SPLIT-RATE CROSS-CHECK
    #
    # These are the regression's coefficients rounded to two significant figures, which is how the
    # template carries them on 01 Inputs and therefore what it computes with. The unrounded fit
    # (4.73 / 7.29 / 2.58) is recorded in `empirical.FITTED` as the honest statement of what was
    # measured — but a cross-check whose numbers do not match the sheet it cross-checks is worse
    # than useless, so the sheet's values are the defaults.
    "setup_days_per_hole": 4.7,
    "soil_m_per_day": 7.3,
    "rock_m_per_day": 2.6,
    # COMMERCIAL
    "margin": 0.10,
    "overhead_local": 0.07,
    "overhead_regional": 0.05,
    "overhead_international": 0.03,
    "nec_fee": 0.10,
    "risk_loading": 0.05,
    # MATERIALS
    "mazier_interval_m": 2.0,
    "mazier_sample_length_m": 0.5,
    "soil_tube_cost": 100.0,
    "core_box_cost": 150.0,
    "soil_box_capacity_m": 30.0,
    "rock_box_capacity_m": 4.0,
    "grout_hole_diameter_m": 0.08,
    "grout_cost_per_litre": 30.0,
    # MOBILISATION
    "crane_lorry_rate": 5000.0,
    "crane_lorry_days": 2.0,
    "truck_rate": 1500.0,
    "truck_days": 2.0,
    "survey_per_location": 1000.0,
    # ORGANISATION — two DIFFERENT supervision resources, and the difference is the point.
    #
    # The open question a previous version left on the register ("is the site team the same
    # resource as a GFT?") is ANSWERED: they are not. The site team (engineer + foreman +
    # geologist + PM) manages a SITE, so its count follows the number of sites and does not move
    # when a rig is added. The GFT manages RIGS, at one per `gft_ratio` of them. Every number here
    # is an ordinary input — several of them are assumptions, so all of them are adjustable.
    "site_count": 1.0,              # how many sites this contract runs on
    "site_team_per_site": 1.0,      # teams per site — a coefficient, so 0.5 = shared with another job
    "gft_ratio": 6.0,               # rigs per GFT — the stated rule
    "hours_per_day": 8.0,
}

_PLANT = [
    ("drill_rig", "Drill rig", 500.0), ("pump", "Water + hydraulic pump", 200.0),
    ("sed_tanks", "Sedimentation tanks", 100.0), ("toolbox", "Toolbox", 50.0),
    ("drill_tools", "Drilling tools / rods", 300.0), ("casing", "Casing", 100.0),
    ("core_racks", "Core racks", 20.0), ("diesel_tank", "Diesel tank", 50.0),
    ("bentonite_storage", "Bentonite storage", 50.0), ("general_storage", "General storage", 50.0),
]

# PRELIMINARIES — (key, label, what the rate is per, the words that find it in a bill).
#
# Drawn from the Bill 1 lines of the reference tender that no drilling basis can reach: the office,
# a car, the telephone, the core store, the environmental measures. `match` is a regex against the
# item description, kept HERE with the resource rather than in the pricing code, so adding a
# resource and teaching the app to find it are one edit instead of two.
_PRELIM = [
    # One resource, not two. The reference bill splits the office across a "provision" line, a
    # "servicing" line and a "taking over" line, and it is tempting to give each its own resource —
    # but they are all the same office, and three blanks for one cost is how a number gets entered
    # twice. The monthly rate IS the servicing cost; the `item` lines take a lump, because a
    # monthly rate cannot produce a one-off.
    ("prelim_office", "Site accommodation", "$/month",
     r"temporary accommodation|site office|office accommodation"),
    ("prelim_vehicle", "Site vehicle", "$/week", r"private car|site vehicle|\bvehicle\b"),
    ("prelim_store", "Core and sample store", "$/week", r"core and sample store|core store"),
    ("prelim_telephone", "24-hour telephone line", "$/month", r"telephone line|24-hour telephone"),
    ("prelim_environmental", "Environmental management measures", "$/month",
     r"environmental management|environmental measures"),
    ("prelim_trip_tickets", "Trip-ticket / site management plan", "$/month",
     r"trip ticket|site management plan"),
    ("prelim_waste_sorting", "On-site sorting of C&D material", "$/month",
     r"sorting of c&d|c&d material|construction and demolition material"),
    ("prelim_comms", "Site communication network", "$/month", r"communication network"),
    ("prelim_prints", "Photographic prints", "$/nr", r"\bsize print\b|photographic print"),
]

_LAB = [
    ("lab_moisture", "Moisture content", 65.0), ("lab_atterberg", "Atterberg limits", 695.0),
    ("lab_psd", "Particle size distribution", 295.0), ("lab_bulk_density", "Bulk density", 86.0),
    ("lab_particle_density", "Particle density / specific gravity", 100.0),
    ("lab_ph", "pH value", 150.0), ("lab_sulphate", "Sulphate content", 390.0),
    ("lab_chloride", "Chloride content", 345.0), ("lab_organic", "Organic content", 250.0),
    ("lab_uu", "UU triaxial (single stage, 76mm)", 650.0),
    ("lab_cu", "CU triaxial (single stage, 76mm)", 1450.0),
    ("lab_oedometer", "Oedometer", 1800.0), ("lab_point_load", "Point load", 163.0),
    ("lab_ucs", "UCS rock compression", 1240.0),
    ("lab_modulus", "Rock elastic modulus", 1600.0),
    ("lab_joint_shear", "Rock joint shear", 2200.0),
]

STANDBY_FACTOR = 1.23


def default_model() -> CostingModel:
    """The template's model, exactly. A starting point, never a rule."""
    spread = [
        SpreadLine(key=key, label=label, block="PLANT", multiplier=STANDBY_FACTOR, rate=rate,
                   charge=CHARGE_RIG_DAY,
                   note="Standby factor applied — plant is held for the whole spread duration, "
                        "including non-drilling days.")
        for key, label, rate in _PLANT
    ] + [
        SpreadLine(key="driller", label="Driller", block="LABOUR", multiplier=1.0, rate=2000.0,
                   charge=CHARGE_RIG_DAY),
        SpreadLine(key="general_workers", label="General workers", block="LABOUR", multiplier=2.0,
                   rate=1500.0, charge=CHARGE_RIG_DAY, note="Two on the rig."),
        SpreadLine(key="fuel", label="Fuel", block="CONSUMABLES", multiplier=1.0, rate=600.0,
                   charge=CHARGE_RIG_DAY, note="40 L/day at $12/L."),
        SpreadLine(key="small_consumables", label="Small consumables", block="CONSUMABLES",
                   multiplier=1.0, rate=200.0, charge=CHARGE_RIG_DAY, note="Water, bits, grease."),

        SpreadLine(key="site_engineer", label="Site engineer", block="SITE TEAM", multiplier=1.0,
                   rate=2000.0, charge=CHARGE_CONTRACT_DAY),
        SpreadLine(key="foreman", label="Foreman", block="SITE TEAM", multiplier=1.0, rate=2000.0,
                   charge=CHARGE_CONTRACT_DAY),
        SpreadLine(key="geologist", label="Geologist", block="SITE TEAM", multiplier=0.5,
                   rate=2500.0, charge=CHARGE_CONTRACT_DAY,
                   note="Allocation below 1 means shared across concurrent contracts."),
        SpreadLine(key="project_manager", label="Project manager", block="SITE TEAM",
                   multiplier=0.33, rate=3000.0, charge=CHARGE_CONTRACT_DAY,
                   note="Split across three concurrent contracts. If this one runs alone the "
                        "allocation goes to 1.00 and the rate rises materially."),

        # THE GFT — a different resource from the site team above, on its own charge class because
        # its COUNT follows the rigs rather than the sites. Rated at ZERO on purpose, the same rule
        # the preliminaries follow: this is a number that is genuinely yours, and a plausible
        # invented figure would price a tender without anybody deciding anything. It is reported
        # loudly in three places until it is entered — the build-up row, the priced bill's
        # problems, and the assumptions register — because unlike a preliminary it is recovered
        # through a build-up rather than matched to a bill line, so a zero here would otherwise be
        # silently free.
        SpreadLine(key="gft", label="Ground/field technician team (GFT)", block="GFT",
                   multiplier=1.0, rate=0.0, charge=CHARGE_GFT,
                   note="Your cost per GFT-day — not yet entered. One GFT supervises `gft_ratio` "
                        "rigs (stated rule: 6). Nothing using this prices until it is entered."),

        # PRELIMINARIES — the resources the client bills as their own items rather than expecting
        # inside a drilling rate. Rated at ZERO on purpose: these are the numbers that are genuinely
        # yours, nobody else in the market has them, and a plausible invented figure here would be
        # worse than a blank because it would price a tender without anyone deciding anything.
        # Fill them once and every Bill 1 line that uses them prices itself.
        *[SpreadLine(key=key, label=label, block="PRELIMINARIES", multiplier=1.0, rate=0.0,
                     unit=unit, charge=CHARGE_PRELIM, match=match,
                     note="Your cost — not yet entered. Nothing using this can be priced until it is.")
          for key, label, unit, match in _PRELIM],
    ]

    basis_rows = [
        ItemBasis(key="soil_drilling", label="Soil drilling", driver=DRIVER_SOIL_DAYS,
                  divisor=DIVISOR_SOIL_M,
                  note="Soil work-days x spread day-cost, divided by soil metres."),
        ItemBasis(key="rock_drilling", label="Rock drilling", driver=DRIVER_ROCK_DAYS,
                  divisor=DIVISOR_ROCK_M,
                  note="Rock work-days x spread day-cost, divided by rock metres."),
        ItemBasis(key="setup_move", label="Set-up / move per hole", driver=DRIVER_SETUP_DAYS,
                  divisor=DIVISOR_HOLES,
                  note="Fixed work-days x spread day-cost, divided by the number of holes."),
        ItemBasis(key="standing_time", label="Standing time", driver=DRIVER_STANDING_DAYS,
                  divisor=DIVISOR_STANDING_H,
                  note="Idle days x spread day-cost, divided by standing hours."),
        ItemBasis(key="site_team", label="Site team — whole contract", driver=DRIVER_SITE_TEAM,
                  divisor=DIVISOR_CONTRACT_MONTHS,
                  note="One team per site (site_count x site_team_per_site). Recovered in Bill 1 "
                       "time-related items, never inside a drilling rate."),
        ItemBasis(key="gft", label="GFT — whole contract", driver=DRIVER_GFT,
                  divisor=DIVISOR_CONTRACT_MONTHS,
                  note="ceil(rigs / gft_ratio) technician teams. A different resource from the "
                       "site team: this one follows the RIGS."),
        ItemBasis(key="mobilise", label="Mobilise on land", driver=DRIVER_FIXED,
                  divisor=DIVISOR_NONE, note="Crane lorry + truck, in and out.",
                  components=[
                      FixedComponent(label="Crane lorry", rate_key="crane_lorry_rate",
                                     qty_key="crane_lorry_days"),
                      FixedComponent(label="Truck (equipment)", rate_key="truck_rate",
                                     qty_key="truck_days"),
                  ]),
        ItemBasis(key="setting_out", label="Setting out / survey", driver=DRIVER_PER_HOLE,
                  divisor=DIVISOR_HOLES, unit_cost_key="survey_per_location",
                  note="Per location."),
        ItemBasis(key="soil_tubes", label="Soil sample tubes", driver=DRIVER_MATERIAL,
                  divisor=DIVISOR_QTY, material=MATERIAL_TUBES, unit_cost_key="soil_tube_cost",
                  note="One tube per mazier sample."),
        ItemBasis(key="core_boxes", label="Core boxes", driver=DRIVER_MATERIAL,
                  divisor=DIVISOR_QTY, material=MATERIAL_BOXES, unit_cost_key="core_box_cost",
                  note="Soil boxes + rock boxes, each rounded up separately."),
        ItemBasis(key="backfill_grout", label="Backfill grout", driver=DRIVER_MATERIAL,
                  divisor=DIVISOR_HOLES, material=MATERIAL_GROUT,
                  unit_cost_key="grout_cost_per_litre",
                  note="Grout volume x unit cost, divided by the number of holes."),
    ]

    return CostingModel(
        name="GI drilling",
        note="Seeded from GI_Costing_Template.xlsx. Change anything — an edit made on a tender "
             "stays on that tender.",
        inputs=dict(DEFAULT_INPUTS),
        bands=DEFAULT_BANDS.model_copy(deep=True),
        method=MethodSettings(),
        spread=spread,
        laboratory=[LabRate(key=key, label=label, rate=rate) for key, label, rate in _LAB],
        placeholders=[PlaceholderRate(unit=unit, rate=rate, label=label)
                      for unit, rate, label in _PLACEHOLDER],
        basis_rows=basis_rows,
        markup=[
            MarkupStep(key="overhead", label="Overhead loading", kind=MARKUP_LOADING,
                       components=["overhead_local", "overhead_regional",
                                   "overhead_international"]),
            MarkupStep(key="risk", label="Risk loading", kind=MARKUP_LOADING,
                       components=["risk_loading"]),
            MarkupStep(key="margin", label="Margin", kind=MARKUP_ON_SELLING,
                       components=["margin"]),
        ],
        rounding=[
            RoundingStep(threshold=0.0, decimals=0),
            RoundingStep(threshold=100.0, decimals=-1),
            RoundingStep(threshold=1000.0, decimals=-2),
        ],
    )
