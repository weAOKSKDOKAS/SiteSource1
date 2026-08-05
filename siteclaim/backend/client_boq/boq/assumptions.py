"""BOQ — the assumptions register: every belief behind the rates, and who signed it off.

Bucket: **Generated list, human verdict.** The rows are assembled from the model actually pricing the
job; the Status column is a person's and nothing else may write it.

WHY IT IS GENERATED RATHER THAN TYPED
-------------------------------------
A register somebody maintains by hand goes stale the first time the model changes, and a stale
register is worse than none — it is a page of confirmations against numbers nobody is using any more.
So the rows come from the model in force. Change the bands, drop a mark-up step, re-point a driver,
and what you are asked to confirm changes with it.

WHAT IS DERIVED AND WHAT IS JUDGEMENT
-------------------------------------
Six of these cannot be typed at all — rock fraction, the band selected, its sample size, the depth
check, the convergence between the two methods, the rig count. They are read from the bill or worked
out from it, and the register shows them so a reviewer can see what the model concluded, not so
anybody can adjust it.

The rest are judgements, and four are marked **low confidence** deliberately: the residual site
factor (anything above 1.00 needs a named reason), the supervision allocations (if this contract runs
alone they both go to 1.00 and the rates rise materially), the laboratory buy rates (they need current
written quotations), and item coverage (resolving it in full needs the SMM and its corrigenda).

THE GATE
--------
`COUNTBLANK` on the Status column, exactly as the reference workbook has it. It **warns and does not
block** — the sweep is the app's only hard stop — but the workbook prints ``NOT CLEARED`` until every
row has a verdict, so a model nobody has reviewed cannot be mistaken for one that has been.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.buildup import Buildup, Spread
from client_boq.boq.model import CostingModel
from client_boq.boq.programme import Programme

# What a reviewer may say. Blank is the fifth state and the one that matters: not yet looked at.
STATUS_ACCEPTED = "Accepted"
STATUS_REVISED = "Revised"
STATUS_REJECTED = "Rejected"
STATUSES = (STATUS_ACCEPTED, STATUS_REVISED, STATUS_REJECTED)

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"

SOURCE_BQ = "BQ"
SOURCE_DERIVED = "Derived"
SOURCE_EMPIRICAL = "As-built data"
SOURCE_JUDGEMENT = "Judgement"
SOURCE_COMMERCIAL = "Commercial"
SOURCE_CONTRACT = "Contract"
SOURCE_QUOTATION = "Quotation"


class Assumption(BaseModel):
    """One belief the rates rest on."""

    key: str
    label: str
    value: str = ""
    basis: str = ""
    source: str = SOURCE_JUDGEMENT
    confidence: str = CONFIDENCE_MEDIUM
    derived: bool = False           # cannot be typed — read from the bill or worked out from it

    status: str = ""                # a person's, or blank
    reviewed_by: str = ""
    reviewed_at: Optional[str] = None
    comment: str = ""

    @property
    def outstanding(self) -> bool:
        return not self.status


class Register(BaseModel):
    """The whole register, and whether it has been worked through."""

    rows: list[Assumption] = Field(default_factory=list)

    def outstanding(self) -> list[Assumption]:
        return [row for row in self.rows if row.outstanding]

    def cleared(self) -> bool:
        return not self.outstanding()

    def gate(self) -> str:
        """What the workbook prints. The reference template's own words."""
        return "CLEARED" if self.cleared() else "NOT CLEARED"

    def summary(self) -> str:
        left = len(self.outstanding())
        return (f"{len(self.rows)} assumptions · all reviewed" if not left
                else f"{len(self.rows)} assumptions · {left} not yet reviewed")

    def low_confidence(self) -> list[Assumption]:
        return [row for row in self.rows if row.confidence == CONFIDENCE_LOW]


def build(programme: Programme, model: CostingModel, buildup: Buildup, spread: Spread,
          *, verdicts: Optional[dict[str, dict]] = None,
          billed_standing_hours: Optional[float] = None) -> Register:
    """Assemble the register from the model in force, then apply whatever verdicts are recorded."""
    rows: list[Assumption] = []
    band = programme.band

    # --- what the bill and the model concluded, which nobody types ------------
    rows.append(Assumption(
        key="rock_fraction", label="Rock fraction of the works",
        value=f"{programme.rock_fraction:.1%}", derived=True,
        source=SOURCE_BQ, confidence=CONFIDENCE_HIGH,
        basis="Derived from the bill's own soil, rock and hard-material split. Not typed. This is "
              "the primary production driver, because rock fraction measures mode of working — "
              "washboring with a short socket against a coring operation."))

    if band is not None:
        rows.append(Assumption(
            key="band", label="Production band selected", value=band.label, derived=True,
            source=SOURCE_EMPIRICAL, confidence=CONFIDENCE_HIGH,
            basis="A banded lookup, not a regression coefficient. Bands are all-in blended rates "
                  "from as-built holes, including per-hole set-up."))
        rows.append(Assumption(
            key="band_rate", label="Band base production rate",
            value=f"{band.rate:g} m/work-day", derived=True,
            source=SOURCE_EMPIRICAL, confidence=CONFIDENCE_MEDIUM,
            basis="Confidence follows the sample size behind the band."))
        rows.append(Assumption(
            key="band_n", label="Band sample size", value=f"{band.holes} holes", derived=True,
            source=SOURCE_EMPIRICAL,
            confidence=CONFIDENCE_LOW if band.indicative_only else CONFIDENCE_MEDIUM,
            basis=band.confidence()))

    for check in programme.checks:
        if check.key == "depth":
            rows.append(Assumption(
                key="depth_check", label="Depth extrapolation check",
                value=f"{check.value:+.1%}" if check.value is not None else "", derived=True,
                source=SOURCE_DERIVED, confidence=CONFIDENCE_HIGH, basis=check.message))
        elif check.key == "convergence":
            rows.append(Assumption(
                key="convergence", label="Method A against Method B",
                value=f"{check.value:+.1%}" if check.value is not None else "", derived=True,
                source=SOURCE_DERIVED, confidence=CONFIDENCE_HIGH, basis=check.message))

    rows.append(Assumption(
        key="rigs", label="Number of rigs required", value=f"{programme.rigs_required}",
        derived=True, source=SOURCE_DERIVED, confidence=CONFIDENCE_HIGH,
        basis=f"Derived, not assumed: {programme.work_days:,.0f} work-days over "
              f"{programme.work_days_available_per_rig:,.0f} available per rig "
              f"({programme.rigs_exact:.2f}, rounded up)."))

    rows.append(Assumption(
        key="site_teams", label="Site teams required", value=f"{spread.site_teams_required}",
        derived=True, source=SOURCE_DERIVED, confidence=CONFIDENCE_HIGH,
        basis=f"One team supervises {spread.site_team_supervises:g} rigs. The team runs for the "
              f"contract period regardless of how much drilling is happening, and is recovered in "
              f"Bill 1 rather than inside a drilling rate."))

    # --- the judgements ------------------------------------------------------
    residual = model.value("residual_site_factor", 1.0)
    rows.append(Assumption(
        key="residual_site_factor", label="Residual site factor", value=f"{residual:g}x",
        source=SOURCE_JUDGEMENT, confidence=CONFIDENCE_LOW,
        basis="What is left after the rock-fraction band. 1.00 means the band explains the site. "
              "Any value above 1.00 needs a named reason written in the comment."))

    rows.append(Assumption(
        key="calendar_ratio", label="Calendar to work-day ratio",
        value=f"{model.value('calendar_to_work_day'):g}x",
        source=SOURCE_EMPIRICAL, confidence=CONFIDENCE_HIGH,
        basis="Observed 1.18 / 1.18 / 1.36. Weather sits here, not in the production rate — the "
              "project that ran entirely inside typhoon season was the fastest of the three."))

    standing_basis = ("Observed idle as a share of work-days: 19%, 18%, 36%. Drives the standing "
                      "time rate.")
    if billed_standing_hours:
        ratio = (programme.standing_hours / billed_standing_hours) if billed_standing_hours else 0
        standing_basis += (f" The model derives {programme.standing_hours:,.0f} hours against the "
                           f"{billed_standing_hours:,.0f} the client billed — {ratio:.1f}x.")
    rows.append(Assumption(
        key="standing_allowance", label="Standing / idle allowance",
        value=f"{model.value('standing_allowance'):.0%}",
        source=SOURCE_EMPIRICAL, confidence=CONFIDENCE_MEDIUM, basis=standing_basis))

    rows.append(Assumption(
        key="plant_standby", label="Plant standby factor",
        value=_first_multiplier(model, "PLANT"),
        source=SOURCE_JUDGEMENT, confidence=CONFIDENCE_MEDIUM,
        basis="Plant is held on site for the full spread duration, including non-drilling days."))

    rows.append(Assumption(
        key="supervision_allocation", label="Supervision allocation",
        value=_allocations(model),
        source=SOURCE_JUDGEMENT, confidence=CONFIDENCE_LOW,
        basis="Shared across concurrent contracts. If this contract runs alone, every allocation "
              "goes to 1.00 and the rates rise materially."))

    rows.append(Assumption(
        key="laboratory", label="Laboratory buy rates",
        value=f"{len(model.laboratory)} subcontract rates",
        source=SOURCE_QUOTATION, confidence=CONFIDENCE_LOW,
        basis="Subcontract rates. Must be replaced with current written quotations before "
              "submission."))

    # --- the commercial chain, one row per step it actually has ---------------
    for step in buildup.markup_steps:
        rows.append(Assumption(
            key=f"markup_{step['key']}", label=step["label"],
            value=f"{step['rate']:.0%} → ×{step['factor']:.4f}",
            source=SOURCE_COMMERCIAL, confidence=CONFIDENCE_HIGH,
            basis=("Taken on the selling price, not added to cost — 10% is ×1.111, not ×1.100."
                   if step["kind"] == "on_selling" else "A loading added to cost.")))

    rows.append(Assumption(
        key="nec_fee", label="NEC fee percentage", value=f"{model.value('nec_fee'):.0%}",
        source=SOURCE_CONTRACT, confidence=CONFIDENCE_HIGH,
        basis="Contract Data Part Two. Applies to compensation-event Defined Cost, not to the BQ "
              "rates."))

    # --- the standing caveats ------------------------------------------------
    rows.append(Assumption(
        key="quantities_given", label="Quantities taken as given", value="As per the bill",
        source=SOURCE_BQ, confidence=CONFIDENCE_HIGH,
        basis="No remeasurement or take-off performed. The quantities are the Employer's and are "
              "accepted as stated."))

    rows.append(Assumption(
        key="employer_rates", label="Employer-fixed rates excluded",
        value="pre-priced items", source=SOURCE_CONTRACT, confidence=CONFIDENCE_HIGH,
        basis="Items the client has already priced are carried through untouched — altering one "
              "only gets it reinstated."))

    rows.append(Assumption(
        key="item_coverage", label="Item coverage not fully resolved", value="Partial",
        source=SOURCE_CONTRACT, confidence=CONFIDENCE_LOW,
        basis="Full item coverage needs the Standard Method of Measurement and its corrigenda. "
              "Rates cover the described work plus the General Preamble categories only."))

    register = Register(rows=rows)
    _apply(register, verdicts or {})
    return register


def _apply(register: Register, verdicts: dict[str, dict]) -> None:
    """Lay recorded verdicts over the generated rows. A verdict for a row the model no longer has
    simply stops being read — which is the point of regenerating rather than storing them."""
    for row in register.rows:
        mark = verdicts.get(row.key)
        if not mark:
            continue
        status = mark.get("status", "")
        row.status = status if status in STATUSES else ""
        row.reviewed_by = mark.get("reviewed_by", "")
        row.reviewed_at = mark.get("reviewed_at")
        row.comment = mark.get("comment", "")


def _first_multiplier(model: CostingModel, block: str) -> str:
    for line in model.spread:
        if line.block == block:
            return f"{line.multiplier:g}x"
    return "—"


def _allocations(model: CostingModel) -> str:
    shared = [f"{l.label} {l.multiplier:g}" for l in model.spread
              if l.block == "SITE TEAM" and l.multiplier != 1.0]
    return " · ".join(shared) if shared else "all at 1.00"
