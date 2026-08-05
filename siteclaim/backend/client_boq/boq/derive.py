"""BOQ — derive the bill's own quantities, and compare them with the bill.

Bucket: **Deterministic**. Every rule below is a printed instruction plus arithmetic; none is a
judgement and none is a model's opinion.

WHAT THIS IS FOR — AND IT IS NOT TAKE-OFF
------------------------------------------
The client measured the quantities and we may not change them (GCT 6). This module recomputes them
anyway, from the station schedule and the site's own rules, for one reason: **to find where the bill
and the drawings disagree.**

That is worth more than it sounds. On the reference contract the consultant's own arithmetic is
recoverable and exact:

    standing time      455 h ÷ 91 holes = 5.0 h/hole      (and Bill 3: 45 ÷ 9 = 5.0)
    recording          47 → 2,451 nr-wk · 68 → 3,546 · 115 → 5,996   (instruments × 365 ÷ 7)
    AGMD               47 + 68 = 115                       one per instrument, exactly
    trial pits         21 × 1.5 × 1.5 × 3.0 = 141.75 → 142 m³
    pit samples        21 × 3 = 63, three times over
    inspection pits    91 × 0.5 m³ = 45.5 → 45 m³
    Bill 3 drilling    the exact sum of nine scheduled hole depths, 62 m

Where a derivation lands on the bill, it confirms both the bill and our reading of the drawing. Where
it does not, one of them is wrong — and finding that before the tender box closes is the whole point.
GI/100's Table 1 already gives one: 52 permeability and 30 pressuremeter tests against the bill's 54
and 31.

Nothing here overwrites anything. It reports.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.criteria import SiteCriteria
from client_boq.boq.schedule import StationSchedule
from client_boq.models import ClientBill

# How far a derivation may sit from the bill before it is called a divergence. The consultant rounds
# to whole units, so a metre either way on a 2,300 m item is agreement, not disagreement.
TOLERANCE_ABS = 1.0
TOLERANCE_REL = 0.005


class Derived(BaseModel):
    """One quantity we can compute, and what the bill says about it."""

    full_ref: str = ""              # the bill item this speaks to, where there is one
    label: str = ""
    value: float = 0.0
    unit: str = ""
    rule: str = ""                  # the arithmetic, in words
    source: str = ""                # where the inputs came from
    billed: Optional[float] = None
    agrees: Optional[bool] = None
    note: str = ""

    def compare(self, billed: Optional[float]) -> "Derived":
        self.billed = billed
        if billed is None:
            self.agrees = None
            self.note = "no bill item to compare against"
            return self
        gap = abs(self.value - billed)
        self.agrees = gap <= max(TOLERANCE_ABS, abs(billed) * TOLERANCE_REL)
        if not self.agrees:
            direction = "more than" if self.value > billed else "less than"
            self.note = (f"derived {self.value:,g} {self.unit} is {gap:,g} {direction} the billed "
                         f"{billed:,g}. Either the drawing was misread or the bill diverges from it — "
                         f"worth settling before the rate rests on it")
        return self


class DerivationReport(BaseModel):
    derived: list[Derived] = Field(default_factory=list)

    def divergences(self) -> list[Derived]:
        return [d for d in self.derived if d.agrees is False]

    def confirmations(self) -> list[Derived]:
        return [d for d in self.derived if d.agrees is True]

    def unchecked(self) -> list[Derived]:
        return [d for d in self.derived if d.agrees is None]


def _billed_qty(bill: Optional[ClientBill], full_ref: str) -> Optional[float]:
    if bill is None:
        return None
    item = bill.index().get(full_ref)
    return None if item is None else item.qty


def derive(schedule: StationSchedule, criteria: SiteCriteria, *,
           bill: Optional[ClientBill] = None,
           refs: Optional[dict[str, str]] = None,
           standing_hours_per_hole: float = 5.0) -> DerivationReport:
    """Recompute what can be recomputed, and set it beside the bill.

    ``refs`` maps a derivation name to the bill item it speaks to, because item numbering differs
    between contracts — Bill 2's drilling is ``2.4`` here and something else on the next job.
    """
    refs = refs or {}
    holes = schedule.hole_count()
    pits = len(schedule.trial_pits)
    out: list[Derived] = []

    def add(name: str, label: str, value: float, unit: str, rule: str, source: str) -> None:
        entry = Derived(full_ref=refs.get(name, ""), label=label, value=value, unit=unit,
                        rule=rule, source=source)
        out.append(entry.compare(_billed_qty(bill, refs.get(name, ""))))

    add("soil_m", "Drilling, material other than rock", schedule.soil_m(), "m",
        "Σ tentative length in soil, over every station",
        f"{schedule.source_sheet or 'the station schedule'} · {holes} rows")

    add("rock_m", "Drilling, rock", schedule.rock_m(), "m",
        "Σ expected length in rock, over every station",
        f"{schedule.source_sheet or 'the station schedule'} · {holes} rows")

    add("holes", "Moving rigs", float(holes), "nr",
        "one per borehole, drillhole and probehole shown on the Drawings",
        "SMM S02 ¶2.03")

    add("standing_time", "Standing time for rigs", holes * standing_hours_per_hole, "h",
        f"{holes} holes × {standing_hours_per_hole:g} h",
        "the consultant's own allowance, recovered by division (455 ÷ 91 = 5.0, and 45 ÷ 9 = 5.0)")

    add("standpipes", "Standpipe, installation", float(schedule.standpipes()), "nr",
        "count of stations marked for a standpipe", schedule.source_sheet or "the station schedule")

    add("piezometers", "Piezometer, installation", float(schedule.piezometers()), "nr",
        "count of stations marked for a piezometer", schedule.source_sheet or "the station schedule")

    add("agmd", "Automatic groundwater monitoring device", float(schedule.instruments()), "nr",
        f"{schedule.standpipes()} standpipes + {schedule.piezometers()} piezometers — one device each",
        "GI/100 groundwater monitoring criteria ¶3")

    monitoring = criteria.monitoring
    for name, label, count in (
        ("record_standpipe", "Recording, standpipe", schedule.standpipes()),
        ("record_piezometer", "Recording, piezometer", schedule.piezometers()),
        ("record_agmd", "Recording, AGMD", schedule.instruments()),
    ):
        add(name, label, float(monitoring.instrument_weeks(count)), "nr-wk",
            f"{count} × {monitoring.monitoring_months:g} months, at 365 ÷ 7 weeks",
            "GI/100 groundwater monitoring criteria ¶5, 'at least 12 months'")

    if pits:
        add("trial_pit_volume", "Trial pits", criteria.pits.trial_volume_m3(pits), "m3",
            f"{pits} pits × {criteria.pits.trial_width_m:g} × {criteria.pits.trial_length_m:g} × "
            f"{criteria.pits.trial_depth_m:g} m",
            "GI/100 trial pits ¶1")
        per_pit = criteria.pits.trial_samples_per_pit()
        add("trial_pit_samples", "Samples from trial pits", float(pits * per_pit), "nr",
            f"{pits} pits × {per_pit} samples "
            f"(every {criteria.pits.trial_sample_interval_m:g} m from "
            f"{criteria.pits.trial_sample_start_m:g} m)",
            "GI/100 trial pits ¶2")

    if holes:
        add("inspection_pit_volume", "Inspection pits", criteria.pits.inspection_volume_m3(holes),
            "m3", f"{holes} holes × {criteria.pits.inspection_allowance_m3:g} m³",
            "GI/100 field testing ¶1 — every drillhole starts with an inspection pit")
        mazier = criteria.sampling.count_at_interval(schedule.soil_m(),
                                                     criteria.sampling.mazier_interval_m)
        add("mazier", "Mazier samples", float(mazier), "nr",
            f"{schedule.soil_m():,g} m of soil ÷ {criteria.sampling.mazier_interval_m:g} m",
            "GI/100 field testing ¶2")

    for name, label, drawn in (
        ("permeability", "In-situ permeability test", criteria.tests.permeability),
        ("pressuremeter", "Pressuremeter test", criteria.tests.pressuremeter),
        ("televiewer", "Acoustic televiewer test", criteria.tests.acoustic_televiewer),
    ):
        if drawn:
            add(name, label, float(drawn), "nr", "as tabulated on the drawing",
                f"{criteria.source_sheet or 'the general-notes drawing'} Table 1 (tentative)")

    return DerivationReport(derived=out)
