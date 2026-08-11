"""INGEST — which drawing carries the take-off. Deterministic; no model, no network.

Bucket: **Deterministic.** Pure functions of PDF bytes and filenames.

THE CHEAPEST QUESTION IN THE PRODUCT, AND IT TURNED OUT TO BE FREE
------------------------------------------------------------------
The plan was a batched vision call over width-capped thumbnails of all 35 sheets — about $0.16 and
one round trip — to answer "which of these is the schedule". Measured on the real pack, that call is
unnecessary: the issuer ships a **drawing register** (`DRG/60740338-GI-COVER.pdf`) and it is the one
document in the whole drawing set with a real text layer::

    GI-COVER      2,582 chars   <- the register: every drawing number against its title
    GI-210           28 chars   <- "Tender Drawing", the date, the checker's initials
    GI-310           28 chars
    every other      28-57 chars

So the triage is: read the register's text, keep the titles ending ``- COORDINATE``, and drop the
ones titled ``WORKING AREA`` — those are the site boundary, not the holes. Zero tokens, milliseconds.

**THERE ARE TWO SCHEDULE SHEETS, AND THAT IS THE POINT OF DOING THIS PROPERLY.**

    GI/210   PROPOSED SITE INVESTIGATION - COORDINATE                  the engineering boreholes
    GI/310   PROPOSED SITE INVESTIGATION PLAN (ENVIRONMENTAL) - COORDINATE   the environmental ones

Bills 3 and 5 are the environmental-borehole bills. A reader that finds GI/210, stops, and reports
success has silently under-read the tender — and every check downstream would agree with it, because
they all measure what was read against what was read. Finding *both* is a property of the register
lookup and cannot be a property of a reader that was told which sheet to open.

WHEN THERE IS NO REGISTER
-------------------------
Not every issuer ships one, so this degrades rather than fails, on the same ladder
:func:`client_boq.ingest.pdfops.plan_draft` uses: the register if there is one, otherwise the
filenames, otherwise nothing found and a sentence saying so. A tier that found nothing is reported
as a tier that found nothing — never as a pack with no schedule in it.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

#: A drawing number as the register prints it: `60740338/GI/210`, `GI/210`, `GI-210`.
_DRAWING = re.compile(r"\b(?:\d{6,9}[/\-])?GI[/\-](\d{3}[A-Z]?)\b", re.I)

#: What a schedule sheet's title ends with on this issuer's register. The tables that carry a row
#: per station are the COORDINATE sheets; the layout plans that draw the same stations on a map are
#: not, and neither is anything else.
COORDINATE = "coordinate"

#: The trap inside the same suffix. `WORKING AREA OF GROUND INVESTIGATION - COORDINATE` is the site
#: boundary — a polygon, not a station list — and it ends in exactly the same word. Excluding it is
#: the whole difference between reading two sheets and reading four.
NOT_A_SCHEDULE = ("working area",)

#: Which sheets these are, once found. Kept because a hole's provenance is how somebody checks it,
#: and because the two sheets do not carry the same columns (see `schedule_read`).
KIND_ENGINEERING = "engineering"
KIND_ENVIRONMENTAL = "environmental"

TIER_REGISTER = "register"
TIER_FILENAME = "filename"
TIER_NONE = "none"


class SheetEntry(BaseModel):
    """One drawing, as the register names it."""

    number: str = ""            # "GI/210"
    title: str = ""             # "PROPOSED SITE INVESTIGATION - COORDINATE"
    filename: str = ""          # the file it was matched to, when one was found

    def is_schedule(self) -> bool:
        low = self.title.strip().lower()
        if not low.endswith(COORDINATE):
            return False
        return not any(bad in low for bad in NOT_A_SCHEDULE)

    def kind(self) -> str:
        return (KIND_ENVIRONMENTAL if "environmental" in self.title.lower()
                else KIND_ENGINEERING)


class SheetPlan(BaseModel):
    """Which sheets to read, how that was decided, and what was passed over."""

    sheets: list[SheetEntry] = Field(default_factory=list)
    tier: str = TIER_NONE
    reason: str = ""
    #: Register entries that end in COORDINATE but are not station schedules, named rather than
    #: dropped: a sheet excluded by a rule is a sheet somebody may need to see the rule for.
    excluded: list[str] = Field(default_factory=list)
    #: Every drawing the register lists, so "35 sheets, 2 of them schedules" can be said out loud.
    total_drawings: int = 0

    def found(self) -> bool:
        return bool(self.sheets)

    def headline(self) -> str:
        if not self.sheets:
            return (f"No station-schedule drawing was identified. {self.reason} Nothing has been "
                    f"read — this is not a pack with no schedule in it, it is a pack whose "
                    f"schedule was not found.")
        named = ", ".join(f"{s.number} ({s.kind()})" for s in self.sheets)
        tail = (f" {len(self.excluded)} other coordinate sheet(s) were passed over: "
                f"{', '.join(self.excluded)}." if self.excluded else "")
        return (f"{len(self.sheets)} station-schedule sheet(s) identified from "
                f"{self.total_drawings or 'the'} drawing(s): {named}. {self.reason}{tail}")


def parse_register(text: str) -> list[SheetEntry]:
    """The drawing register's text layer → one entry per drawing. Pure.

    Deliberately forgiving about layout. A register is a two-column table flattened by the text
    extractor, so a number and its title may share a line or sit on consecutive ones; both are
    handled, and a number with no title still becomes an entry — a drawing that exists and whose
    title could not be read is a fact, and dropping it would make the count wrong.
    """
    entries: list[SheetEntry] = []
    pending: Optional[SheetEntry] = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _DRAWING.search(line)
        if match:
            if pending is not None:
                entries.append(pending)
            number = f"GI/{match.group(1).upper()}"
            title = _DRAWING.sub("", line).strip(" -–—\t|.")
            pending = SheetEntry(number=number, title=title)
            continue
        if pending is not None and not pending.title:
            pending.title = line.strip(" -–—\t|.")
    if pending is not None:
        entries.append(pending)
    # First mention wins, like every other reader in this module: a register that lists a drawing
    # twice is listing one drawing.
    seen: set[str] = set()
    unique: list[SheetEntry] = []
    for entry in entries:
        if entry.number not in seen:
            seen.add(entry.number)
            unique.append(entry)
    return unique


def match_files(entries: list[SheetEntry], filenames: list[str]) -> list[SheetEntry]:
    """Attach each register entry to the file that carries it, by drawing number in the name."""
    by_number: dict[str, str] = {}
    for name in filenames or []:
        found = _DRAWING.search(name.replace("\\", "/"))
        if found:
            by_number.setdefault(f"GI/{found.group(1).upper()}", name)
    return [entry.model_copy(update={"filename": by_number.get(entry.number, "")})
            for entry in entries]


def plan_from_register(register_text: str, filenames: list[str]) -> SheetPlan:
    """Tier 1: the register says which sheets are schedules. Free, exact, and it finds BOTH."""
    entries = match_files(parse_register(register_text), filenames)
    if not entries:
        return SheetPlan(tier=TIER_NONE,
                         reason="the drawing register carried no readable drawing numbers.")
    schedules = [e for e in entries if e.is_schedule()]
    excluded = [f"{e.number} — {e.title}" for e in entries
                if e.title.strip().lower().endswith(COORDINATE) and not e.is_schedule()]
    return SheetPlan(
        sheets=schedules, tier=TIER_REGISTER, excluded=excluded, total_drawings=len(entries),
        reason=("Read from the drawing register's own text, which lists every drawing against its "
                "title — no sheet was opened to decide this and no model was asked."))


def plan_from_filenames(filenames: list[str]) -> SheetPlan:
    """Tier 2: no register, so the filenames are all there is.

    Weaker on purpose, and it says so: a filename carries a number and not a title, so this cannot
    tell the station schedule from the working-area sheet that shares its suffix. It offers the
    candidates and leaves the choice with a person.
    """
    numbered = [SheetEntry(number=f"GI/{m.group(1).upper()}", filename=name)
                for name in filenames or []
                if (m := _DRAWING.search(name.replace("\\", "/")))]
    if not numbered:
        return SheetPlan(tier=TIER_NONE,
                         reason="no file in the drawing folder carries a GI drawing number.")
    return SheetPlan(
        sheets=numbered, tier=TIER_FILENAME, total_drawings=len(numbered),
        reason=("There is no drawing register in this pack, so these are every GI-numbered sheet "
                "rather than the schedules specifically — a filename carries a number and not a "
                "title, so nothing here can tell a station schedule from a working-area plan. "
                "Pick the one to read."))


def plan(register_text: str = "", filenames: Optional[list[str]] = None) -> SheetPlan:
    """The ladder: the register, then the filenames, then an honest nothing.

    Degraded success, never a raise — the same shape `pdfops.plan_draft` uses for the split, and
    for the same reason: a pack this cannot read is a pack somebody has to look at, not a crash.
    """
    names = list(filenames or [])
    if (register_text or "").strip():
        from_register = plan_from_register(register_text, names)
        if from_register.found():
            return from_register
    if names:
        return plan_from_filenames(names)
    return SheetPlan(tier=TIER_NONE, reason="no drawings were supplied.")
