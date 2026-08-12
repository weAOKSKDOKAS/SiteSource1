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

import os
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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

#: FORCE A BAND COUNT, for trying one provider against another on the same sheet.
#:
#: ``0`` or unset keeps the adaptive behaviour: one call, then slices only if that call could not
#: hold its answer. ``1`` pins it to a single call and never slices. ``2`` or more slices EVERY
#: sheet at that count without attempting the whole sheet first.
#:
#: It exists because the adaptive path can only be triggered by a failure, so there was no way to
#: ask "does this model do better on a quarter of the sheet?" without editing the module. That is a
#: question about a live provider, and a question you cannot ask is a question that gets answered
#: by guessing.
BANDS_ENV = "SCHEDULE_READ_BANDS"

#: How many times a band that TRUNCATED may be re-asked as its own two halves.
#:
#: 1 turns a failed quarter into two eighths, and only that quarter pays — the three that read are
#: not re-read. 2 would go on to sixteenths. Beyond that a band is not too big, something else is
#: wrong with it, and halving forever spends real money discovering that.
SPLIT_DEPTH_ON_TRUNCATION = 1

#: A ROW WITH NO NUMBER ON IT AT ALL is the shape of a reader that gave up politely: it returns the
#: table's skeleton — the right number of rows, plausible station names — and fills in nothing.
#: Measured on a live run, one provider returned 70 such rows for a sheet another read as 22 rows
#: with correct coordinates and levels.
#:
#: The share, not the count, because sheets differ in size. Half is deliberately not marginal: a
#: legitimate sheet has SOME numbers on most rows, and GI/310 — four columns and a sentence — still
#: carries an easting and a northing on every row, so it never trips this.
HOLLOW_SHARE_ENV = "SCHEDULE_READ_HOLLOW_SHARE"
HOLLOW_SHARE = 0.5

#: Below this many rows the share means nothing and the check stays quiet — two hollow rows out of
#: three is a small sheet with two bad rows, not a reader that gave up.
HOLLOW_MIN_ROWS = 4

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
    "OMIT any field you have no value for. Do not write it as null — a table of 91 rows repeats "
    "every key name on every row, and leaving out what is empty is the difference between an "
    "answer that fits in one reply and one that does not. A field you leave out means exactly what "
    "null means: not read, or not on this sheet.\n\n"
    "The borehole table's columns are printed LEFT TO RIGHT in this order. Read a row by its "
    "position in that order, so a heading you cannot make out never moves a value into the "
    "neighbouring field:\n"
    "  1 STATION -> station\n"
    "  2 the BH/TP type -> kind\n"
    "  3 EASTING -> easting\n"
    "  4 NORTHING -> northing\n"
    "  5 APPROXIMATE GROUND LEVEL (mPD) -> ground_level_mpd\n"
    "  6 TENTATIVE ROCKHEAD LEVEL (mPD) -> rockhead_level_mpd\n"
    "  7 TENTATIVE BOREHOLE LENGTH -> length_m\n"
    "  8 MAX. BORING LENGTH -> max_boring_m\n"
    "  9 TENTATIVE LENGTH IN SOIL -> soil_m\n"
    " 10 EXPECTED LENGTH IN ROCK/CORESTONE/BOULDER ABOVE ROCKHEAD -> hard_above_rockhead_m\n"
    " 11 EXPECTED LENGTH IN ROCK -> rock_m\n"
    " 12 STANDPIPE -> standpipe\n"
    " 13 PIEZOMETER -> piezometer\n\n"
    "TWO OF THOSE HEADINGS START WITH THE SAME WORDS and they are different columns. Column 10 "
    "begins 'EXPECTED LENGTH IN ROCK' and CONTINUES '/CORESTONE/BOULDER ABOVE ROCKHEAD'; column "
    "11 is the shorter one that ends at 'ROCK'. Both are printed wrapped over several lines. If "
    "you cannot read a whole heading, use the column's POSITION in the order above — and if you "
    "still cannot tell which of the two you are in, return null for both. A metre of hard "
    "material recorded as rock is a wrong number that looks like a right one.\n\n"
    "Trial pits have their own columns:\n"
    "  TENTATIVE EXCAVATION DEPTH -> depth_m\n"
    "  MAX. EXCAVATION DEPTH -> max_depth_m\n"
    "  TENTATIVE DEPTH IN SOIL -> depth_in_soil_m\n"
)


def _or_none(value):
    """Anything the reader could not give as a number becomes ``None``, per cell.

    THE READER'S OUTPUT TYPE MUST BE THE MOST TOLERANT THING IN THIS MODULE, and that is not
    laxness — it is where the honesty discipline actually has to live. Every ounce of strictness
    here converts a partial read into a total failure, because pydantic validates the payload as
    ONE object: measured, a single null in row 11 discarded 22 perfectly good rows. The strictness
    that matters is downstream, in arithmetic that cannot be talked out of it.

    So a cell that arrives as ``"n/a"``, ``"-"`` or a smudge degrades to "not read" — exactly what
    the mapper below already does with a genuine ``None`` — instead of taking its row, its slice and
    its sheet with it.
    """
    if value is None or isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class RawStation(BaseModel):
    """One row as the reader saw it. EVERY value optional — `None` means "I could not read this".

    There is deliberately no confidence field, no note about whether the row looks right, and no
    way to mark a reading as checked. A reader that can grade itself is a reader whose grade
    somebody will eventually believe.

    ALL THREE TEXT FIELDS ACCEPT ``None``, and that is the fix for the second live run. `station`,
    `kind` and `termination` were plain ``str``: a default makes a field safe to OMIT, and does
    nothing at all when the key is present holding ``null``. GI/210's boreholes have no termination
    column — it exists only on GI/310 — so the model correctly returned ``null`` and the schema
    rejected the row for it, taking every other field on every other row in that slice with it,
    including the ground level, the rockhead and the soil/rock split it had plainly read.

    That is the principle this module already enforces for the depth columns — *a column that is
    not on the sheet is not a blank cell* — arriving one field late.
    """

    station: Optional[str] = None
    kind: Optional[str] = None
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
    #: The environmental sheet's prose depth rule, verbatim. Never turned into a number here, and
    #: ``None`` on any sheet that does not carry the column at all.
    termination: Optional[str] = None
    # Trial-pit columns.
    depth_m: Optional[float] = None
    max_depth_m: Optional[float] = None
    depth_in_soil_m: Optional[float] = None

    _numbers = field_validator(
        "easting", "northing", "ground_level_mpd", "rockhead_level_mpd", "length_m",
        "max_boring_m", "soil_m", "hard_above_rockhead_m", "rock_m", "depth_m", "max_depth_m",
        "depth_in_soil_m", mode="before")(_or_none)


class RawSchedule(BaseModel):
    """What the reader returned. Not a schedule — the deterministic mapper makes one of these.

    A ROW THAT CANNOT BE MADE SENSE OF IS DROPPED AND COUNTED, never allowed to fail the payload.
    Measured on the second live run: two slices came back as complete, correct JSON and were thrown
    away whole because one field on one row held ``null``. Forty-seven boreholes and twenty-one
    trial pits, read correctly, discarded by a schema.

    So the last line of defence is structural rather than hopeful: whatever the reader sends, this
    keeps the rows it can and names the ones it cannot. It is the same rule as everywhere else here
    — no silent drops — with the emphasis on *silent*, not on *drops*.
    """

    boreholes: list[RawStation] = Field(default_factory=list)
    trial_pits: list[RawStation] = Field(default_factory=list)
    #: Rows the reader sent that could not be made into a row at all, as they arrived. Never
    #: silently discarded: a slice that lost four rows is a different thing from one that read four
    #: fewer.
    unusable_rows: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _keep_what_can_be_kept(cls, data):
        if not isinstance(data, dict):
            return data
        kept: dict = {"boreholes": [], "trial_pits": [],
                      "unusable_rows": list(data.get("unusable_rows") or [])}
        for key in ("boreholes", "trial_pits"):
            for row in (data.get(key) or []):
                if isinstance(row, RawStation):
                    kept[key].append(row)
                    continue
                try:
                    kept[key].append(RawStation.model_validate(row))
                except Exception:  # noqa: BLE001 — a row we cannot read is named, not fatal
                    kept["unusable_rows"].append(str(row)[:200])
        return kept


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
    #: WHY the sheet was sliced, in a few words, for the headline. There are three triggers now —
    #: a truncated answer, an operator asking, and a whole-sheet read that came back empty — and
    #: the headline used to state the first as though it were the only one.
    sliced_because: str = ""
    #: WHAT THE RUN COST AND HOW LONG IT TOOK, per sheet. One entry per live call — provider,
    #: model, ms, input and output tokens. Empty in DEMO, which is the honest answer there.
    #:
    #: Carried because comparing two providers on one sheet has been done twice by hand from row
    #: counts, an afternoon each time. The evidence existed at `_log_call` and had nowhere to go.
    calls: list[dict] = Field(default_factory=list)
    #: The reader returned rows and put no numbers in them. Empty when it did not.
    #:
    #: A SEPARATE FACT FROM `problem`, and it has to be. `problem` means nothing came back at all;
    #: this means something came back that is the right SHAPE and carries no reading. The second is
    #: the more dangerous of the two, because it arrives with `read=True` and a plausible row
    #: count — so it is stated rather than left to be inferred from `cells_unread`.
    gave_up: str = ""

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
            head += f" from {self.bands - len(self.bands_failed)} of {self.bands} slices"
            if self.sliced_because:
                head += f" ({self.sliced_because})"
        # FIRST, above every other tail. A row count is the most reassuring thing on this line and
        # it is exactly what a surrendered read gets right — 70 rows and not one number in them
        # reads as a fuller take-off than 22 rows that were actually transcribed.
        if self.gave_up:
            return (f"{head}, BUT THE READER DID NOT READ IT: {self.gave_up}. The row count above "
                    f"is a count of outlines. Try another provider, or slice the sheet with "
                    f"{BANDS_ENV}, before trusting anything here.")
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

    if (raw.termination or '').strip():
        # THE ENVIRONMENTAL SHEET'S DEPTH RULE, kept as words. It is a driller's instruction —
        # "~6M BELOW EXISTING GROUND LEVEL OR +11MPD, WHICHEVER IS LOWER" — and turning it into a
        # metre would be the reader deciding something the drawing left to site.
        notes.append(f"termination requirement, as printed: {(raw.termination or '').strip()}")
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
    notes = [f"read from {sheet} by the drawing reader — a proposal, not a confirmed take-off"]
    if raw.unusable_rows:
        notes.append(
            f"{len(raw.unusable_rows)} row(s) the reader sent could not be made into a station at "
            f"all and are NOT in this take-off: {'; '.join(raw.unusable_rows[:5])}"
            + (" …" if len(raw.unusable_rows) > 5 else ""))
    return StationSchedule(
        set_id=set_id, source_sheet=sheet,
        stations=[_station(row, sheet) for row in raw.boreholes if (row.station or "").strip()],
        trial_pits=[_trial_pit(row, sheet) for row in raw.trial_pits
                    if (row.station or "").strip()],
        notes=notes,
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


def _numeric_fields() -> tuple[str, ...]:
    """Every ``float`` column on :class:`RawStation`, read off the model rather than listed.

    A new column added to the row type is covered the day it is added. A list here would be one
    more place to forget, and forgetting it would silently shrink what "gave up" means.
    """
    out = []
    for name, info in RawStation.model_fields.items():
        args = getattr(info.annotation, "__args__", ()) or (info.annotation,)
        if any(arg is float for arg in args):
            out.append(name)
    return tuple(out)


NUMERIC_FIELDS = _numeric_fields()


def hollow(row: RawStation) -> bool:
    """A row carrying no number at all — not one coordinate, level, length or depth.

    Not the same as a row with gaps. A real row on the engineering sheet has eleven numbers and a
    real row on the environmental sheet has two; a row with **zero** is a row the reader wrote the
    shape of and did not read.
    """
    return all(getattr(row, name) is None for name in NUMERIC_FIELDS)


def gave_up(raw: RawSchedule, *, share: Optional[float] = None) -> str:
    """Did the reader return the table's skeleton and fill in nothing? The sentence, or ``""``.

    **THE FAILURE THAT LOOKS LIKE A SUCCESS**, and the reason this exists. Slicing was reachable
    only through `CompletionTruncated`, so a model that errors gets a second chance and a model
    that politely surrenders does not. Measured on a live run of the same sheet: one provider
    returned 70 rows with every numeric cell null — no easting, no northing, no ground level, no
    rockhead — and it came back `read=True, bands=1`, indistinguishable at a glance from a sheet
    that simply had little on it. The other read 22 rows with correct coordinates and levels.

    Nothing downstream was fooled: 350 unread cells reach `unread_rows()` and `usable()` is False.
    But the READER was, and it is the only thing in the chain that can still do something about it.

    Deterministic, and it never looks at the values — only at whether there are any. There is no
    judgement here about whether a number is *right*; that is the arithmetic's job, twice over.
    """
    rows = list(raw.boreholes) + list(raw.trial_pits)
    if len(rows) < HOLLOW_MIN_ROWS:
        return ""
    limit = HOLLOW_SHARE if share is None else share
    empty = [row for row in rows if hollow(row)]
    if len(empty) / len(rows) <= limit:
        return ""
    return (f"{len(empty)} of {len(rows)} rows came back with no number on them at all — no "
            f"coordinate, level, length or depth. That is the shape of a table the reader outlined "
            f"and did not read, not a sheet with little on it")


def _env_int(name: str, default: int) -> int:
    """An int from the environment, ignoring anything that is not one. Never raises."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


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
        merged.unusable_rows.extend(part.unusable_rows)
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
               bands: Optional[int] = None,
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
        from client_boq.llm import STAGE_DRAWING, make_client

        # `stage=STAGE_DRAWING` — its own question, falling through to ingest and then to the
        # app-wide setting, so an installation that names no reader behaves exactly as before.
        # It is separate because this is the one call where the strongest model is worth its cost
        # and its latency, and choosing it here must not also change the model that classifies a
        # document or drafts an enquiry.
        #
        # The stage was absent entirely and that was a live-run defect. This read
        # `make_client()`, so `resolve_provider` never reached its ingest branch and
        # `EXTRACTION_PROVIDER` was skipped entirely — for the one call in the module that is
        # most obviously the ingest stage, reading a tender drawing. With nothing stored the
        # provider then came back `None`, and `_route` sends an image call with no explicit
        # provider to `VISION_FALLBACK`. Confirmed live: `.env` said openai, the settings table
        # was empty, and the failure named Anthropic.
        #
        # Guarded, because "never raises" is a promise this function makes in its own docstring
        # and `make_client` reads the settings table to keep it — so an unreachable store threw
        # straight past the whole degrade-not-fail path below.
        try:
            client = make_client(stage=STAGE_DRAWING)
        except Exception as exc:  # noqa: BLE001 — a client we cannot build is a gap that says so
            return ReadReport(
                sheet=sheet,
                problem=(f"the reader could not be set up ({type(exc).__name__}: {exc}), so "
                         f"nothing on this drawing has been looked at"))

    # FORCED, when an operator has asked for it. Two or more slices every sheet, without the
    # whole-sheet attempt — the only way to ask "is this provider better on a quarter of the
    # table?" without editing this file. `1` pins a single call and disables slicing entirely.
    #
    # The argument wins over the environment so one sheet can be tried both ways in one session;
    # the environment is for a whole run. Neither is a decision about the take-off — both only
    # change how many times the sheet is looked at.
    forced = _env_int(BANDS_ENV, 0) if bands is None else int(bands)
    if forced >= 2:
        return _read_in_bands(data, page, set_id=set_id, sheet=sheet, client=client,
                              demo_fixture=demo_fixture, bands=forced,
                              why=f"{BANDS_ENV}={forced} — sliced on request, not on a failure",
                              because="sliced on request")

    try:
        raw = _ask(client, png, demo_fixture)
    except Exception as exc:  # noqa: BLE001 — a failed read is a gap that says so
        if not _truncated(exc) or bands_on_truncation < 2 or forced == 1:
            return ReadReport(
                sheet=sheet,
                problem=(f"reading the drawing failed ({type(exc).__name__}: {exc})"
                         if not _truncated(exc) else
                         f"the sheet's answer did not fit in one call and it could not be sliced "
                         f"({exc})"))
        return _read_in_bands(data, page, set_id=set_id, sheet=sheet, client=client,
                              demo_fixture=demo_fixture, bands=bands_on_truncation, why=str(exc),
                              because="one call could not hold the whole sheet")

    # SLICING ON THE RESULT, not only on an exception.
    #
    # A reader that gives up politely — the table's skeleton, every number null — never raised, so
    # it never reached the retry above and its failure passed as a partial success. Measured live:
    # 70 rows, not one coordinate, `read=True, bands=1`, against 22 correct rows from the other
    # provider on the same sheet. Surrender reading as success is this codebase's recurring shape;
    # here the reader is the one component still able to do something about it.
    surrendered = gave_up(raw, share=_env_float(HOLLOW_SHARE_ENV, HOLLOW_SHARE))
    if surrendered and bands_on_truncation >= 2 and forced != 1:
        retried = _read_in_bands(data, page, set_id=set_id, sheet=sheet, client=client,
                                 demo_fixture=demo_fixture, bands=bands_on_truncation,
                                 why=surrendered,
                                 because="the whole-sheet read came back with no numbers in it")
        # The slices are only worth having if they read something the whole sheet did not. If they
        # gave up too, the FIRST reading is kept — it has as many rows and cost one call — and the
        # surrender is carried on the report either way, because a second empty answer is evidence
        # about the provider rather than about the sheet.
        if retried.read and not retried.gave_up:
            return retried.model_copy(update={
                "gave_up": f"{surrendered}. Re-read in {retried.bands} slices, which did read."})

    schedule = to_schedule(raw, set_id=set_id, sheet=sheet)
    return ReadReport(schedule=schedule, sheet=sheet, read=True, gave_up=surrendered,
                      calls=list(getattr(client, "call_log", []) or []),
                      cells_unread=sum(len(s.unread) for s in schedule.stations))


def _split_failed_band(data: bytes, page: int, index: int, bands: int, *, client,
                       demo_fixture: str, depth: int, exc: Exception):
    """A truncated band, re-asked as its own two halves. ``None`` when that does not apply.

    Returns ``(schedules, notes)`` — whatever the halves read, and a note for each half that still
    failed. A half that fails is NOT split again beyond ``depth``: past a certain point a band is
    not too big, something else is wrong with it, and halving forever would spend real money
    discovering that.

    Only a TRUNCATION is retried. A refusal, a validation error or a transport failure is not a
    size problem, and re-asking half of it would cost a call to fail the same way.
    """
    if depth < 1 or not _truncated(exc):
        return None
    got: list[RawSchedule] = []
    notes: list[str] = []
    finer = bands * 2
    for half in (index * 2, index * 2 + 1):
        png = pdfops.render_band(data, page, half, finer, dpi=READ_DPI)
        if not png:
            notes.append(f"slice {index + 1} of {bands}, half {half % 2 + 1}, "
                         f"could not be rendered")
            continue
        try:
            got.append(_ask(client, png, demo_fixture,
                            band=f"slice {half + 1} of {finer}, top to bottom"))
        except Exception as inner:  # noqa: BLE001 — a half that fails is named, not fatal
            deeper = _split_failed_band(data, page, half, finer, client=client,
                                        demo_fixture=demo_fixture, depth=depth - 1, exc=inner)
            if deeper is None:
                notes.append(f"slice {index + 1} of {bands}, half {half % 2 + 1} "
                             f"({half + 1} of {finer}), failed "
                             f"({type(inner).__name__}: {inner})")
                continue
            got.extend(deeper[0])
            notes.extend(deeper[1])
    if not got and not notes:
        return None
    return got, notes


def _read_in_bands(data: bytes, page: int, *, set_id: str, sheet: str, client,
                   demo_fixture: str, bands: int, why: str, because: str = "",
                   depth: int = SPLIT_DEPTH_ON_TRUNCATION) -> ReadReport:
    """The sheet in slices, after one call could not hold its answer.

    Every band is attempted even after one fails: the whole point of slicing is that a failure stops
    being all-or-nothing, and abandoning the rest at the first error would give that back. And a
    band that fails on TRUNCATION is re-asked as its own two halves before it is given up on — see
    :func:`_split_failed_band`.
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
            # ONE TRUNCATED BAND BECOMES TWO, AND ONLY IT PAYS.
            #
            # A band whose answer did not fit is asked again as its own two halves, rather than
            # the whole sheet being re-cut or the band abandoned. The arithmetic makes this free:
            # band `i` of `n` covers [i/n, (i+1)/n], and bands `2i` and `2i+1` of `2n` are exactly
            # its two halves with the same overlap — so `render_band` needs no new geometry and
            # the caller's de-duplication on station name already handles the seam.
            #
            # Not a budget change. The budget is measured not to be the constraint (a quarter-band
            # is ~1,800-2,100 tokens against 16,000) and raising it is a written trap. This is the
            # other half of the same finding: whatever consumed that one call, half as much of the
            # sheet is a smaller ask for it.
            halves = _split_failed_band(
                data, page, index, bands, client=client, demo_fixture=demo_fixture,
                depth=depth, exc=exc)
            if halves is None:
                failed.append(f"slice {index + 1} of {bands} failed ({type(exc).__name__}: {exc})")
                continue
            got, notes = halves
            parts.extend(got)
            failed.extend(notes)

    if not parts:
        return ReadReport(
            sheet=sheet, bands=bands, bands_failed=failed,
            problem=(f"the sheet's answer did not fit in one call ({why}), and none of its "
                     f"{bands} slices could be read either"))

    merged = _merge_raw(parts)
    # The same verdict on the sliced reading as on the whole-sheet one, computed HERE so there is
    # one implementation of it. Slicing does not make a surrender stop being one — it just moves
    # the evidence from "this sheet is hard" to "this provider will not read it".
    surrendered = gave_up(merged, share=_env_float(HOLLOW_SHARE_ENV, HOLLOW_SHARE))
    schedule = to_schedule(merged, set_id=set_id, sheet=sheet)
    schedule.notes.append(
        f"this sheet was read in {bands} slices ({bands - len(failed)} of them successfully) "
        f"because {why}. Rows near a slice boundary are read twice by design and de-duplicated "
        f"on the station name.")
    return ReadReport(schedule=schedule, sheet=sheet, read=True, bands=bands, bands_failed=failed,
                      gave_up=surrendered, sliced_because=because,
                      calls=list(getattr(client, "call_log", []) or []),
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
