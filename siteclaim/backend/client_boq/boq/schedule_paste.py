"""BOQ — the station schedule, pasted in.

Bucket: **Deterministic.** A pure function of text. No model, no network, no store, no I/O. It
parses and it reports; it never saves and it never guesses at a cell.

WHY THIS EXISTS
---------------
``POST /site/schedule`` has always accepted a :class:`~client_boq.boq.schedule.StationSchedule`, and
nothing in this application has ever produced one. No frontend code called the endpoint, no backend
code constructed the model outside its own class statement, and the demo database holds zero
schedules. The screen said *"Read it off the borehole details drawing (GI/210) and save it first"* —
an instruction the app gave no means of following, and behind that dead end sat the bill-vs-drawing
check, the access map, and the only place in the whole application where a hole is given its class.

So the take-off had no reader. It also had no **door**, and the door is worth more: an estimator has
the schedule in front of him on a sheet or in a spreadsheet, and ninety-one rows of it. This is the
door. A reader that transcribes the drawing arrives later and comes through the same one.

WHY A PASTE BOX AND NOT A FORM
------------------------------
Ninety-one rows and twelve columns is 1,092 form fields. Whatever the estimator is reading from — an
Excel take-off, a table copied out of a PDF, a column of figures typed in a text file — it is
already tabular, and the tab character is what it comes with. So: paste it, see exactly what was
understood, then save.

THE ONE RULE
------------
**A cell this cannot read is named, never filled in.**

``soil_m``, ``rock_m`` and ``hard_above_rockhead_m`` are plain floats defaulting to ``0.0``. If a
cell reads ``"n/a"`` or ``"-"`` or a smudge, writing ``0.0`` produces a hole that drills no soil —
a confident, specific, wrong number that flows into Σ soil and out again into a rate. So the parser
records the field in ``Station.unread`` instead, and :meth:`StationSchedule.usable` refuses the
schedule until a person settles it. Every other rule in this module follows from that one.

Note the asymmetry, and it is the model's, not this parser's: ``easting`` and its kind are
``Optional`` and already model absence honestly, so a blank there is simply ``None``. The three
depth fields have no way to say "unknown", which is exactly what ``unread`` was added for.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.schedule import Station, StationSchedule, TrialPit

#: What a column header may be called. Matched on the header text with everything but letters and
#: digits stripped, so "Length in Soil (m)", "LENGTH IN SOIL", and "length_in_soil" are one key.
#: Order matters within a field: the first pattern that matches a header claims it, and the field
#: order below is the order of a real GI/210 sheet, so a positional read of a headerless paste lands
#: on the right columns too.
COLUMNS: list[tuple[str, tuple[str, ...]]] = [
    ("station", ("station", "hole", "holeno", "boreholeno", "borehole", "ref", "id", "name")),
    ("easting", ("easting", "east", "e", "x")),
    ("northing", ("northing", "north", "n", "y")),
    ("ground_level_mpd", ("groundlevel", "gl", "groundlevelmpd", "existinggroundlevel")),
    ("rockhead_level_mpd", ("rockhead", "rockheadlevel", "tentativerockheadlevel", "rockheadmpd")),
    ("length_m", ("tentativelength", "tentativeboreholelength", "boreholelength", "totaldepth",
                  "totallength", "length", "depth")),
    ("max_boring_m", ("maxboring", "maximumboring", "maxboringlength", "maximumboringlength")),
    ("soil_m", ("lengthinsoil", "tentativelengthinsoil", "soil", "soillength", "soilm")),
    ("hard_above_rockhead_m", ("hard", "hardmaterial", "arm", "corestone", "boulder",
                               "lengthinhardmaterial", "abovearockhead", "aboverockhead")),
    ("rock_m", ("lengthinrock", "expectedlengthinrock", "rock", "rocklength", "rockm")),
    ("standpipe", ("standpipe", "sp", "st", "standpipes")),
    ("piezometer", ("piezometer", "pz", "piezometers", "piezo")),
]

#: The three that cannot say "unknown". A blank here is a fact nobody established, not a zero.
DEPTH_FIELDS = ("soil_m", "hard_above_rockhead_m", "rock_m")

#: Every other numeric field. These are ``Optional`` on the model, so blank means ``None`` and says
#: so honestly without any help from us.
OPTIONAL_NUMERIC = ("easting", "northing", "ground_level_mpd", "rockhead_level_mpd",
                    "length_m", "max_boring_m")

TICKS = ("standpipe", "piezometer")

#: A cell a person writes to mean "there is nothing here". Anything else that is not a number is a
#: cell we could not read, and gets said out loud rather than assumed away.
BLANKS = {"", "-", "--", "—", "–", "n/a", "na", "nil", "none", ".", "/"}

_YES = {"y", "yes", "✓", "✔", "x", "t", "true", "1", "tick", "√"}
_NO = {"n", "no", "f", "false", "0"}

#: A trial pit's name on the reference contract is CE19-NTP01; a borehole's is CE19-ABH00. Used only
#: to route a row to the right list when the paste mixes them, which the real sheet does.
_TRIAL_PIT = re.compile(r"(^|[^A-Z])(N?TP|TRIALPIT)", re.I)

_NUMBER = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^[+-]?\d*\.?\d+$")


class PasteReport(BaseModel):
    """What the paste was understood to say, and everything that was not understood.

    The schedule is a **proposal**: it is returned, never stored. Saving it is a separate call that
    a person makes, which is the same shape every other machine-derived thing in this module has.
    """

    schedule: StationSchedule = Field(default_factory=StationSchedule)
    #: The header row as it was mapped, ``field -> the header text it came from``. Empty when the
    #: paste had no recognisable header and the columns were taken in the sheet's printed order.
    mapping: dict[str, str] = Field(default_factory=dict)
    #: Column headers present in the paste that match no field. Named rather than dropped: a column
    #: we ignored is a column somebody may have needed.
    unmapped_columns: list[str] = Field(default_factory=list)
    #: Fields this schedule has no column for at all.
    missing_columns: list[str] = Field(default_factory=list)
    #: Lines that could not be made into a row at all, with the line number as pasted.
    skipped_lines: list[str] = Field(default_factory=list)
    header_found: bool = False
    #: The delimiter that was used, for the screen to say so.
    delimiter: str = ""

    def cells_unread(self) -> int:
        return sum(len(s.unread) for s in self.schedule.stations)

    def headline(self) -> str:
        """One sentence for the top of the screen. Reassuring only when it is true."""
        s = self.schedule
        if not s.stations and not s.trial_pits:
            return ("Nothing in that paste looked like a station row. Expected one row per hole, "
                    "columns separated by tabs or commas.")
        parts = [f"{len(s.stations)} borehole(s)"]
        if s.trial_pits:
            parts.append(f"{len(s.trial_pits)} trial pit(s)")
        read = f"Read {' and '.join(parts)}"
        problems = s.problems()
        if not problems and not self.skipped_lines:
            return (f"{read}: {s.soil_m():,g} m of soil and {s.rock_m():,g} m of rock. Every cell "
                    f"was read. Check it against the sheet, then save.")
        tail = []
        if self.cells_unread():
            tail.append(f"{self.cells_unread()} cell(s) could not be read")
        if self.skipped_lines:
            tail.append(f"{len(self.skipped_lines)} line(s) were not rows")
        if problems:
            tail.append(f"{len(problems)} row(s) are not settled")
        return f"{read}, but {'; '.join(tail)}. Nothing was guessed at — every one is named below."


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _split(line: str, delimiter: str) -> list[str]:
    if delimiter == "\t":
        return [c.strip() for c in line.split("\t")]
    if delimiter == ",":
        return [c.strip() for c in line.split(",")]
    return [c for c in re.split(r"\s{2,}", line.strip()) if c != ""]


def _pick_delimiter(lines: list[str]) -> str:
    """Tabs, then commas, then runs of whitespace.

    Tabs first because that is what a spreadsheet and a PDF table both put on the clipboard, and
    because a station name may legitimately carry a comma and never carries a tab.
    """
    if any("\t" in ln for ln in lines):
        return "\t"
    if sum(ln.count(",") for ln in lines) >= max(1, len(lines)):
        return ","
    return "  "


def _map_header(cells: list[str]) -> tuple[dict[int, str], list[str], bool]:
    """``column index -> field``, the headers that matched nothing, and whether this IS a header.

    A row is a header when at least three cells name a field and none of them parses as a number —
    the second half matters, because a bare data row of coordinates would otherwise match ``e`` and
    ``n`` by accident.
    """
    by_index: dict[int, str] = {}
    unmapped: list[str] = []
    taken: set[str] = set()
    for i, cell in enumerate(cells):
        key = _key(cell)
        if not key:
            continue
        hit = next((field for field, names in COLUMNS
                    if field not in taken and key in names), "")
        if hit:
            by_index[i] = hit
            taken.add(hit)
        else:
            unmapped.append(cell)
    numeric = sum(1 for c in cells if _NUMBER.match(c.replace(" ", "")))
    return by_index, unmapped, len(by_index) >= 3 and numeric == 0


def _is_blank(raw: str) -> bool:
    """A cell a person wrote to mean "nothing here".

    Matched on the trimmed, lower-cased text and nothing cleverer. A key-stripped comparison was
    tried and is wrong: it turns ``"***"`` into the empty string and so into a blank, when a row of
    asterisks is exactly the smudge this module exists to name.
    """
    return (raw or "").strip().lower() in BLANKS


def _number(raw: str) -> tuple[Optional[float], bool]:
    """``(value, readable)``. ``(None, True)`` is an honest blank; ``(None, False)`` is a smudge."""
    text = (raw or "").strip()
    if _is_blank(text):
        return None, True
    cleaned = text.replace(",", "").replace(" ", "")
    # A trailing unit is ordinary on a pasted table — "34.90 m", "+8.15mPD".
    cleaned = re.sub(r"(?i)(m|mpd|mm|m\.?p\.?d\.?)$", "", cleaned)
    if not _NUMBER.match(cleaned):
        return None, False
    try:
        return float(cleaned), True
    except ValueError:
        return None, False


def _tick(raw: str) -> tuple[bool, bool]:
    """``(value, readable)``. An unrecognised mark is not a "no" — it is a cell nobody read.

    Compared on the trimmed text, NOT on a key-stripped one: a tick is punctuation, and stripping
    punctuation turns "✓" into the empty string and so into a blank — reading every instrumented
    hole as uninstrumented, which is 47 standpipes and 68 piezometers silently priced at zero.
    """
    text = (raw or "").strip().lower()
    if not text or text in BLANKS:
        return False, True
    if text in _YES:
        return True, True
    if text in _NO:
        return False, True
    return False, False


def _row(cells: list[str], fields: dict[int, str], sheet: str) -> Optional[Station]:
    """One data row into a station, with every cell it could not read named on the station."""
    values: dict[str, object] = {}
    unread: list[str] = []
    notes: list[str] = []
    for index, field in fields.items():
        raw = cells[index] if index < len(cells) else ""
        if field == "station":
            values["station"] = raw.strip()
            continue
        if field in TICKS:
            value, ok = _tick(raw)
            values[field] = value
            if not ok:
                unread.append(field)
                notes.append(f"{field}: {raw.strip()!r} is neither a tick nor a blank")
            continue
        value, ok = _number(raw)
        if not ok:
            unread.append(field)
            notes.append(f"{field}: {raw.strip()!r} is not a number")
            continue
        if value is None:
            # A blank. Honest for an Optional field, which models absence as None; unknown for one
            # that cannot say so, and a metre nobody wrote down is not a metre nobody drills.
            if field in DEPTH_FIELDS:
                unread.append(field)
                notes.append(f"{field}: blank, and a blank is not a zero")
            continue
        values[field] = value
    if not str(values.get("station") or "").strip():
        return None
    return Station(**values, sheet=sheet, unread=unread, notes=notes)  # type: ignore[arg-type]


def _is_a_row(cells: list[str]) -> bool:
    """Two cells or it is not a row.

    A prose line pasted in by accident — a note under the table, a title, a sentence out of the
    specification — splits into ONE cell under every delimiter, and would otherwise become a station
    whose name is the whole sentence and whose every metre is unread. One cell is never a schedule
    row anyway: a station name with no numbers beside it measures nothing, which the take-off's own
    checks would then have to refuse a second time.
    """
    return len([c for c in cells if c.strip()]) >= 2


def _pit(station: Station) -> TrialPit:
    """A trial pit is dug, not drilled, so its depth is its soil length or its stated length."""
    return TrialPit(station=station.station, easting=station.easting, northing=station.northing,
                    ground_level_mpd=station.ground_level_mpd,
                    depth_m=station.length_m if station.length_m is not None else station.soil_m,
                    max_depth_m=station.max_boring_m, sheet=station.sheet)


def parse(text: str, *, set_id: str = "", source_sheet: str = "") -> PasteReport:
    """Read a pasted table into a proposed schedule. Pure; nothing is stored and nothing is fixed.

    Degrades rather than fails, the same ladder :func:`client_boq.ingest.pdfops.plan_draft` uses:
    a recognised header maps the columns by name; no header takes them in the printed order of the
    sheet; a line that is not a row is kept as a skipped line rather than dropped. There is no
    failure mode that raises, and none that silently loses a line.
    """
    lines = [ln for ln in (text or "").replace("\r\n", "\n").split("\n") if ln.strip()]
    report = PasteReport(schedule=StationSchedule(set_id=set_id, source_sheet=source_sheet))
    if not lines:
        return report

    delimiter = _pick_delimiter(lines)
    report.delimiter = {"\t": "tab", ",": "comma"}.get(delimiter, "spaces")

    rows = [_split(ln, delimiter) for ln in lines]
    fields, unmapped, is_header = _map_header(rows[0])
    if is_header:
        report.header_found = True
        report.mapping = {field: rows[0][i] for i, field in fields.items()}
        report.unmapped_columns = unmapped
        body, offset = rows[1:], 2
    else:
        # No header. Take the columns in the order a GI/210 sheet prints them, as far as the paste
        # goes — which is why COLUMNS is in that order and not alphabetical.
        width = max(len(r) for r in rows)
        fields = {i: COLUMNS[i][0] for i in range(min(width, len(COLUMNS)))}
        body, offset = rows, 1
    report.missing_columns = [f for f, _ in COLUMNS if f not in fields.values()]

    for n, cells in enumerate(body):
        station = _row(cells, fields, source_sheet) if _is_a_row(cells) else None
        if station is None:
            report.skipped_lines.append(f"line {n + offset}: {lines[n + offset - 1].strip()[:90]}")
            continue
        if _TRIAL_PIT.search(station.station):
            report.schedule.trial_pits.append(_pit(station))
        else:
            report.schedule.stations.append(station)
    return report
