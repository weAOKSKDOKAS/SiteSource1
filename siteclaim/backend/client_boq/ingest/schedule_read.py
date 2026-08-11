"""INGEST — the station schedule, read off the drawing. **AI proposes; arithmetic decides.**

Bucket: **AI**, with a deterministic mapper in front of it and two independent arithmetic checks
behind it. What comes out is a PROPOSAL — never a confirmed take-off, and never a fact.

WHAT THE SHEETS ACTUALLY ARE, MEASURED
--------------------------------------
A3 landscape, 1191×842 pt, flattened raster: 48 images and **28 characters of text**, which is the
title-block stamp ("Tender Drawing", the date, the checker's initials). Zero station names appear in
the text layer of any drawing in the pack. So this is a picture, and reading it is a vision call.

Rendered at 1,568 px — the API's own downscale ceiling — the table is legible cell by cell: station
names, six-figure coordinates, levels to two decimals, and the tick marks. **So one call reads one
sheet.** The row-band slicing that would have made this ten times more expensive is not needed, and
`pdfops.render_page`'s 1,400 px cap is already the right size.

THE TWO SHEETS DO NOT CARRY THE SAME COLUMNS, AND THAT IS THE TRAP
------------------------------------------------------------------
`GI/210` — PROPOSED BOREHOLE DETAILS SCHEDULE, plus a trial-pit table beside it::

    STATION · type · EASTING · NORTHING · APPROXIMATE GROUND LEVEL (mPD) ·
    TENTATIVE ROCKHEAD LEVEL (mPD) · TENTATIVE BOREHOLE LENGTH (m) · MAX. BORING LENGTH (m) ·
    TENTATIVE LENGTH IN SOIL (m) · EXPECTED LENGTH IN ROCK/CORESTONE/BOULDER ABOVE ROCKHEAD (m) ·
    EXPECTED LENGTH IN ROCK (m) · STANDPIPE ✓ · PIEZOMETER ✓

`GI/310` — PROPOSED SITE INVESTIGATION (ENVIRONMENTAL) DETAILS SCHEDULE::

    STATION · type · EASTING · NORTHING · TERMINATION REQUIREMENT

**Four columns and a sentence.** No ground level, no rockhead, no lengths, and above all no
soil/rock split — the depth is prose ("~6M BELOW EXISTING GROUND LEVEL OR +11MPD, WHICHEVER IS
LOWER"), which is a rule for the driller and not a number for a rate. A reader that pushes both
sheets through one shape produces environmental stations with `soil_m = 0.0` and `rock_m = 0.0`,
and those are indistinguishable from holes that genuinely drill nothing. So the missing columns are
marked **unread** and the termination requirement is kept verbatim as a note. A blank is not a zero,
and a column that is not on the sheet is not a blank either.

THE MEASUREMENT OUTRANKS THE MODEL (repo trap 9)
------------------------------------------------
Every numeric field on the model's own output type is ``Optional``, so a cell it could not make out
comes back as ``None`` rather than as a confident number — and the deterministic mapper below turns
``None`` on a depth field into an ``unread`` mark, never into ``0.0``. The model is not given a
field it could use to settle anything: `RawSchedule` has no `confirmed`, no `usable`, no tolerance
and no totals. It structurally cannot approve its own reading, exactly as `DepartureProposal` cannot
give itself a verdict.

AND THE ARITHMETIC IS THE REAL GATE
-----------------------------------
Two checks the reader does not perform and cannot influence:

1. **Per row** — ``tentative length ≈ soil + rock``, within `ROW_TOLERANCE_M`. Verified on the real
   sheet: 29.90 + 5.0 = 34.90.
2. **Against the client's own bill** — `boq/derive.py` sets Σ soil and Σ rock beside Bill No.2's
   quantities. Two documents that never saw each other agreeing is worth more than any confidence a
   model could report, and where they disagree **that disagreement is the product**.

Which is why reading a table off a picture is safe here at all: nothing downstream trusts the
reading, it trusts the arithmetic.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.schedule import Station, StationSchedule, TrialPit
from client_boq.ingest import pdfops

#: The render the model sees. `pdfops.render_page` solves for the DPI that lands on its 1,400 px
#: width cap, and the API downscales to ~1,568 px anyway — so asking for more buys nothing but
#: bandwidth. Measured legible at that size, cell by cell, on the real sheet.
READ_DPI = pdfops.MAX_RENDER_DPI

#: WHAT ONE SHEET'S ANSWER COSTS TO WRITE, and the ceiling it was hitting.
#:
#: Measured 2026-08-11, on the first live run against the real pack. Serialising this module's own
#: output type for GI/210 — 91 boreholes and 21 trial pits — is 36,885 characters, roughly
#: **9,200-10,250 output tokens**. `DEFAULT_MAX_TOKENS` is 8,000 and this call passed no budget at
#: all, so the model wrote valid JSON and ran out of room. GI/310, at 9 rows, needs ~991 and read
#: perfectly. That is the entire difference between the two sheets.
#:
#: The floor that exists for this failure could not help: `DEEPSEEK_MIN_MAX_TOKENS` is 32,000, but
#: `_route` sends any request carrying images to a VISION_CAPABLE provider and DeepSeek is excluded
#: from that set — so a vision call can never reach the guard by construction.
#:
#: 16,000 is not the fix, it is the headroom. A bigger constant is a higher ceiling somebody else's
#: sheet will hit, which is what `BANDS_ON_TRUNCATION` below is for.
READ_MAX_TOKENS = 16_000

#: How many slices to cut a sheet into when one call could not hold its answer.
#:
#: Four is one call's worth of headroom per band on a table twice the size of the reference sheet's,
#: and it is the number that makes a failure PARTIAL: band 3 failing leaves bands 1, 2 and 4 read,
#: where today a single failure zeroes 91 rows. Derived from a real truncation rather than guessed
#: up front, so a small sheet still costs exactly one call.
BANDS_ON_TRUNCATION = 4

#: What the model must not be allowed to leave out silently. These three have no way to say
#: "unknown" on `Station` — they are plain floats defaulting to 0.0 — so a `None` from the reader
#: becomes an `unread` mark rather than a zero.
DEPTH_FIELDS = ("soil_m", "hard_above_rockhead_m", "rock_m")

SYSTEM = (
    "You transcribe a printed table from an engineering drawing. You are a pair of eyes, not an "
    "engineer: copy what is printed and nothing else.\n\n"
    "RULES, in order of importance:\n"
    "1. If you cannot read a cell with certainty, return null for it. Never guess, never "
    "interpolate from the rows around it, and never carry a value down from the row above.\n"
    "2. A cell that is genuinely blank on the sheet is also null. Do not invent a zero.\n"
    "3. Transcribe every row you can see, in the order they are printed.\n"
    "4. Station names are printed exactly, including their prefix and any letter suffix.\n"
    "5. A tick column is true only where a mark is printed. An empty cell is false. A mark you "
    "cannot identify is null.\n"
    "6. Do not total anything, do not check anything, and do not comment on whether the table "
    "looks right. Something else does that."
)

INSTRUCTION = (
    "Transcribe every row of the station schedule table(s) on this drawing.\n\n"
    "There may be two tables: boreholes, and trial pits. Put each row in the list that matches the "
    "table it is printed in. A row's 'kind' column usually reads BH or TP.\n\n"
    "Some sheets carry only station, easting, northing and a TERMINATION REQUIREMENT written as a "
    "sentence. On those sheets there is no ground level, no rockhead and no soil/rock split — "
    "return null for every one of them and put the termination sentence verbatim in "
    "'termination'. Do not translate a termination sentence into a depth.\n\n"
    "Column meanings, where they appear:\n"
    "  TENTATIVE BOREHOLE LENGTH -> length_m\n"
    "  MAX. BORING LENGTH -> max_boring_m\n"
    "  TENTATIVE LENGTH IN SOIL -> soil_m\n"
    "  EXPECTED LENGTH IN ROCK/CORESTONE/BOULDER ABOVE ROCKHEAD -> hard_above_rockhead_m\n"
    "  EXPECTED LENGTH IN ROCK -> rock_m\n"
    "  TENTATIVE EXCAVATION DEPTH -> depth_m (trial pits)\n"
    "  MAX. EXCAVATION DEPTH -> max_depth_m (trial pits)\n"
    "  TENTATIVE DEPTH IN SOIL -> depth_in_soil_m (trial pits)\n"
)


class RawStation(BaseModel):
    """One row as the reader saw it. EVERY value optional — `None` means "I could not read this".

    There is deliberately no confidence field, no note about whether the row looks right, and no
    way to mark a reading as checked. A reader that can grade itself is a reader whose grade
    somebody will eventually believe.
    """

    station: str = ""
    kind: str = ""                                  # "BH" | "TP", as printed
    easting: Optional[float] = None
    northing: Optional[float] = None
    ground_level_mpd: Optional[float] = None
    rockhead_level_mpd: Optional[float] = None
    length_m: Optional[float] = None
    max_boring_m: Optional[float] = None
    soil_m: Optional[float] = None
    hard_above_rockhead_m: Optional[float] = None
    rock_m: Optional[float] = None
    standpipe: Optional[bool] = None
    piezometer: Optional[bool] = None
    #: The environmental sheet's prose depth rule, verbatim. Never turned into a number here.
    termination: str = ""
    # Trial-pit columns.
    depth_m: Optional[float] = None
    max_depth_m: Optional[float] = None
    depth_in_soil_m: Optional[float] = None


class RawSchedule(BaseModel):
    """What the reader returned. Not a schedule — the deterministic mapper makes one of these."""

    boreholes: list[RawStation] = Field(default_factory=list)
    trial_pits: list[RawStation] = Field(default_factory=list)


class ReadReport(BaseModel):
    """The proposal, and everything about the reading a person should see before trusting it."""

    schedule: StationSchedule = Field(default_factory=StationSchedule)
    sheet: str = ""
    read: bool = False
    #: Why nothing was read, when nothing was. Empty on a successful read — and a read that
    #: produced no rows still says so here rather than returning an empty schedule silently.
    problem: str = ""
    cells_unread: int = 0
    #: How many slices the sheet was cut into. 1 is the ordinary case; more means one call could
    #: not hold the answer and the sheet was banded.
    bands: int = 1
    #: Bands that failed, with why. A PARTIAL read: the rows from the bands that worked are in the
    #: schedule above, and these say what is missing from it — which is the difference between a
    #: take-off that is short and a take-off nobody knows is short.
    bands_failed: list[str] = Field(default_factory=list)

    def partial(self) -> bool:
        return bool(self.read and self.bands_failed)

    def headline(self) -> str:
        if not self.read:
            return f"{self.sheet or 'the drawing'} was not read: {self.problem}"
        schedule = self.schedule
        if not schedule.stations and not schedule.trial_pits:
            return (f"{self.sheet}: the reader returned no rows at all. That is not an empty "
                    f"schedule — it is a sheet nobody has managed to read.")
        parts = [f"{len(schedule.stations)} borehole(s)"]
        if schedule.trial_pits:
            parts.append(f"{len(schedule.trial_pits)} trial pit(s)")
        head = f"{self.sheet}: read {' and '.join(parts)}"
        if self.bands > 1:
            head += (f" from {self.bands - len(self.bands_failed)} of {self.bands} slices "
                     f"(one call could not hold the whole sheet)")
        if self.bands_failed:
            return (f"{head}. THIS SHEET IS ONLY PARTLY READ — "
                    f"{'; '.join(self.bands_failed)}. Whatever rows those slices carried are "
                    f"missing from the take-off above, and no total on it is the sheet's total.")
        problems = schedule.problems()
        if not self.cells_unread and not problems:
            return (f"{head} — {schedule.soil_m():,g} m of soil and {schedule.rock_m():,g} m of "
                    f"rock, every cell read. Check it against the sheet before you confirm it: "
                    f"nothing here has been verified by anything but arithmetic.")
        tail = []
        if self.cells_unread:
            tail.append(f"{self.cells_unread} cell(s) could not be read")
        if problems:
            tail.append(f"{len(problems)} row(s) are not settled")
        return (f"{head}, but {'; '.join(tail)}. Nothing was guessed at — every one is named, and "
                f"no unread cell has been filled in with a zero.")


def _station(raw: RawStation, sheet: str) -> Station:
    """One raw row into a `Station`, marking every cell the reader could not read.

    THE WHOLE DISCIPLINE IS HERE. `soil_m`, `hard_above_rockhead_m` and `rock_m` are plain floats on
    `Station` with no way to say "unknown", so a `None` from the reader would land as `0.0` and be
    indistinguishable from a printed zero. It becomes an `unread` mark instead — and the schedule
    then refuses to be usable until a person settles it.

    The optional fields need no such help: they model absence honestly, so a `None` stays `None`.
    """
    unread: list[str] = []
    notes: list[str] = []
    values: dict = {"station": (raw.station or "").strip(), "kind": (raw.kind or "BH").strip().upper()}

    for field in ("easting", "northing", "ground_level_mpd", "rockhead_level_mpd",
                  "length_m", "max_boring_m"):
        value = getattr(raw, field)
        if value is not None:
            values[field] = float(value)

    for field in DEPTH_FIELDS:
        value = getattr(raw, field)
        if value is None:
            unread.append(field)
        else:
            values[field] = float(value)

    for field in ("standpipe", "piezometer"):
        value = getattr(raw, field)
        if value is None:
            unread.append(field)
            values[field] = False
        else:
            values[field] = bool(value)

    if raw.termination.strip():
        # THE ENVIRONMENTAL SHEET'S DEPTH RULE, kept as words. It is a driller's instruction —
        # "~6M BELOW EXISTING GROUND LEVEL OR +11MPD, WHICHEVER IS LOWER" — and turning it into a
        # metre would be the reader deciding something the drawing left to site.
        notes.append(f"termination requirement, as printed: {raw.termination.strip()}")
        if set(DEPTH_FIELDS) <= set(unread):
            notes.append(
                "this sheet carries no ground level, no rockhead and no soil/rock split — it gives "
                "coordinates and a termination rule. The lengths are unread rather than zero, "
                "because a column that is not on the sheet is not a blank cell."
            )

    return Station(**values, sheet=sheet, unread=unread, notes=notes)


def _trial_pit(raw: RawStation, sheet: str) -> TrialPit:
    """A trial pit's own three depth columns, onto its own model.

    `TrialPit` already has `depth_m`, `max_depth_m` and `depth_in_soil_m`, which is exactly the
    printed table — so no judgement is needed and none is made. What must never happen is a pit's
    excavation depth landing on a borehole's `soil_m`: pits are dug and boreholes are drilled, they
    are measured by different items, and putting pit metres into a drilling duration would inflate
    a rate with work no rig does.
    """
    values: dict = {"station": (raw.station or "").strip()}
    for field in ("easting", "northing", "ground_level_mpd", "max_depth_m", "depth_in_soil_m"):
        value = getattr(raw, field)
        if value is not None:
            values[field] = float(value)
    if raw.depth_m is not None:
        values["depth_m"] = float(raw.depth_m)
    return TrialPit(**values, sheet=sheet)


def to_schedule(raw: RawSchedule, *, set_id: str, sheet: str) -> StationSchedule:
    """The reader's rows into a proposed take-off. Deterministic and pure.

    A row is routed by the table it was printed in, not by its name — the reader is told which list
    each row came from, and `kind` is kept as printed so a mismatch is visible rather than silently
    resolved. `confirmed_by` is left empty because this function has no way to fill it: a machine
    reading is a proposal, and confirming is a person saying they checked THIS reading.
    """
    return StationSchedule(
        set_id=set_id, source_sheet=sheet,
        stations=[_station(row, sheet) for row in raw.boreholes if (row.station or "").strip()],
        trial_pits=[_trial_pit(row, sheet) for row in raw.trial_pits
                    if (row.station or "").strip()],
        notes=[f"read from {sheet} by the drawing reader — a proposal, not a confirmed take-off"],
    )


def _ask(client, png: bytes, demo_fixture: str, *, band: str = "") -> RawSchedule:
    """One image to the model. Raises; the caller decides what a failure means."""
    import base64

    user = INSTRUCTION
    if band:
        user += (f"\n\nTHIS IMAGE IS A SLICE of a larger sheet: {band}. The table's column "
                 f"headings are reproduced at the top of the image above the slice. Transcribe "
                 f"only the rows in the slice, and expect the first and last of them to also "
                 f"appear in a neighbouring slice — that is intended, do not try to correct it.")
    return client.complete_json(
        system=SYSTEM, user=user, target_model=RawSchedule,
        images=[base64.b64encode(png).decode("ascii")],
        max_tokens=READ_MAX_TOKENS,
        demo_fixture=demo_fixture, purpose="client_boq-ingest-schedule-read",
    )


def _truncated(exc: Exception) -> bool:
    """Did the answer run out of room, as opposed to being wrong?

    Imported lazily and matched by NAME as well as by class, because `CompletionTruncated` lives in
    the procurement chassis and this module must not fail to recognise it if that import ever moves.
    """
    try:
        from pipeline.llm_client import CompletionTruncated

        if isinstance(exc, CompletionTruncated):
            return True
    except Exception:  # noqa: BLE001 — the name check below still works
        pass
    return type(exc).__name__ == "CompletionTruncated"


def _merge_raw(parts: list[RawSchedule]) -> RawSchedule:
    """Several slices of one sheet into one reading, de-duplicated on the station name.

    Bands overlap by design, so a row near a boundary is read twice on purpose. First occurrence
    wins — the same rule every other reader in this module uses — and the duplicate is dropped
    silently HERE because it is an artefact of how the sheet was cut, not a fact about the pack.
    A station genuinely printed twice on one sheet still survives as one row, and a station on two
    different SHEETS is a different question that `duplicate_names()` still answers.
    """
    merged = RawSchedule()
    seen: set[str] = set()
    for part in parts:
        for row in part.boreholes:
            name = (row.station or "").strip()
            if name and name not in seen:
                seen.add(name)
                merged.boreholes.append(row)
        for row in part.trial_pits:
            name = (row.station or "").strip()
            if name and name not in seen:
                seen.add(name)
                merged.trial_pits.append(row)
    return merged


def read_sheet(data: bytes, *, set_id: str, sheet: str, page: int = 1,
               client=None, demo_fixture: str = "cases/client_boq/station_schedule_read.json",
               bands_on_truncation: int = BANDS_ON_TRUNCATION,
               ) -> ReadReport:
    """Read one schedule drawing. Returns a proposal; stores nothing; never raises.

    ONE CALL, THEN SLICES — adaptive rather than decided up front. A nine-row sheet costs exactly
    one call, as it does today. A ninety-one-row sheet whose answer will not fit is cut into bands
    and read again, and the band count is derived from a real truncation rather than guessed at
    every sheet's expense.

    MEASURE FIRST, IN EVERY MODE. The render is attempted before the fixture is considered, because
    a fixture returned in front of an unreadable sheet is the trap-9 failure exactly: a confident
    schedule for pixels nobody saw. A sheet that will not render is reported as unread whether or
    not there is a fixture behind it.

    A PARTIAL READ IS A READ. If three bands of four come back, the rows from those three are kept
    and the fourth is named — because a take-off that is short and says so is a different thing from
    a take-off nobody knows is short. Only a sheet where NOTHING came back is reported as unread.
    """
    try:
        png = pdfops.render_page(data, page, dpi=READ_DPI)
    except Exception as exc:  # noqa: BLE001 — an unreadable sheet is a gap, not a crash
        return ReadReport(sheet=sheet, problem=f"the drawing could not be rendered ({exc})")
    if not png:
        return ReadReport(sheet=sheet,
                          problem=("the drawing could not be rendered to an image, so nothing on "
                                   "it has been looked at"))

    if client is None:
        from client_boq.llm import make_client

        client = make_client()

    try:
        raw = _ask(client, png, demo_fixture)
    except Exception as exc:  # noqa: BLE001 — a failed read is a gap that says so
        if not _truncated(exc) or bands_on_truncation < 2:
            return ReadReport(
                sheet=sheet,
                problem=(f"reading the drawing failed ({type(exc).__name__}: {exc})"
                         if not _truncated(exc) else
                         f"the sheet's answer did not fit in one call and it could not be sliced "
                         f"({exc})"))
        return _read_in_bands(data, page, set_id=set_id, sheet=sheet, client=client,
                              demo_fixture=demo_fixture, bands=bands_on_truncation, why=str(exc))

    schedule = to_schedule(raw, set_id=set_id, sheet=sheet)
    return ReadReport(schedule=schedule, sheet=sheet, read=True,
                      cells_unread=sum(len(s.unread) for s in schedule.stations))


def _read_in_bands(data: bytes, page: int, *, set_id: str, sheet: str, client,
                   demo_fixture: str, bands: int, why: str) -> ReadReport:
    """The sheet in slices, after one call could not hold its answer.

    Every band is attempted even after one fails: the whole point of slicing is that a failure stops
    being all-or-nothing, and abandoning the rest at the first error would give that back.
    """
    parts: list[RawSchedule] = []
    failed: list[str] = []
    for index in range(bands):
        png = pdfops.render_band(data, page, index, bands, dpi=READ_DPI)
        if not png:
            failed.append(f"slice {index + 1} of {bands} could not be rendered")
            continue
        try:
            parts.append(_ask(client, png, demo_fixture,
                              band=f"slice {index + 1} of {bands}, top to bottom"))
        except Exception as exc:  # noqa: BLE001 — one bad slice must not lose the others
            failed.append(f"slice {index + 1} of {bands} failed ({type(exc).__name__}: {exc})")

    if not parts:
        return ReadReport(
            sheet=sheet, bands=bands, bands_failed=failed,
            problem=(f"the sheet's answer did not fit in one call ({why}), and none of its "
                     f"{bands} slices could be read either"))

    schedule = to_schedule(_merge_raw(parts), set_id=set_id, sheet=sheet)
    schedule.notes.append(
        f"one call could not hold this sheet's answer, so it was read in {bands} slices "
        f"({bands - len(failed)} of them successfully). Rows near a slice boundary are read twice "
        f"by design and de-duplicated on the station name.")
    return ReadReport(schedule=schedule, sheet=sheet, read=True, bands=bands, bands_failed=failed,
                      cells_unread=sum(len(s.unread) for s in schedule.stations))


def merge(reports: list[ReadReport], *, set_id: str) -> StationSchedule:
    """Both sheets into one take-off, keeping each hole's own source sheet.

    THE ENVIRONMENTAL SHEET IS NOT OPTIONAL. Bills 3 and 5 are the environmental-borehole bills, so
    a take-off assembled from `GI/210` alone is short by every hole on `GI/310` — and every check
    downstream would agree with it, because they all measure what was read against what was read.
    Merging is what makes "we read the schedule" mean "we read the schedules".

    A duplicate station name across two sheets is NOT resolved here. `duplicate_names()` names it,
    which is right: two sheets claiming one station is a fact about the pack.
    """
    merged = StationSchedule(set_id=set_id)
    sheets = [r.sheet for r in reports if r.read and r.sheet]
    merged.source_sheet = " + ".join(sheets)
    for report in reports:
        if not report.read:
            merged.notes.append(f"{report.sheet or 'a drawing'} was NOT read: {report.problem}")
            continue
        if report.partial():
            # A PARTIALLY-READ SHEET POISONS EVERY TOTAL BELOW IT, and the totals do not know that.
            # `soil_m()` sums what is there; it cannot sum what a failed slice was carrying. So the
            # take-off says it, at the top, in the notes that travel with it — not only in the
            # per-sheet report a screen might not show.
            merged.notes.append(
                f"{report.sheet} is only PARTLY read — {'; '.join(report.bands_failed)}. Rows from "
                f"those slices are missing, so no total on this take-off is that sheet's total.")
        merged.stations.extend(report.schedule.stations)
        merged.trial_pits.extend(report.schedule.trial_pits)
    merged.notes.append(
        f"read from {len(sheets)} drawing(s) by the drawing reader — a proposal, not a confirmed "
        f"take-off. Check it against the sheets, and against Bill No.2's own quantities."
    )
    return merged
