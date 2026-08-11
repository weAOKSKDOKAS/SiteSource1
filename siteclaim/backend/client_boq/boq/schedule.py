"""BOQ — the station schedule: the take-off, as the client drew it.

Bucket: **Deterministic** models and checks. Reading them off a raster drawing is a separate stage; by
the time anything arrives here it is data, and every row is checked.

WHAT THIS IS
------------
Drawing GI/210 carries a table with one row per borehole:

    station · easting · northing · ground level · tentative rockhead level ·
    tentative borehole length · max boring length · **length in soil** · length in
    rock/corestone/boulder/ARM above rockhead · **length in rock** · standpipe ✓ · piezometer ✓

That is the take-off. The bill says "2,300 m of drilling in soil" and this is the 91 rows it was summed
from — including the material split, which is the single largest unknown in pricing Bill 2 and which
turns out to be a printed column.

TWO INDEPENDENT CHECKS, WHICH IS WHY READING IT OFF A PICTURE IS SAFE
---------------------------------------------------------------------
1. **Each row must satisfy itself:** ``tentative_length ≈ soil + rock``. Verified on the real sheet —
   29.90 + 5.0 = 34.90, 21.10 + 5.0 = 26.10, 23.11 + 5.0 = 28.11, 18.56 + 5.0 = 23.56.
2. **The totals must equal the client's own bill:** Σ soil = 2,300 m, Σ rock = 600 m, stations = 91,
   standpipes = 47, piezometers = 68.

So the bill is the answer key for our own reading. **When the two disagree, that disagreement is the
most valuable thing here** — either we misread the drawing, or the client's bill diverges from the
client's drawing, and both are worth knowing before pricing. One such divergence already exists: GI/100
Table 1 gives 52 permeability and 30 pressuremeter tests; the bill says 54 and 31.

WHAT IS NOT IN THIS TABLE
-------------------------
**The access class.** The bill prices 80 Class A and 11 Class B rig moves, and no document says which
holes. There is no class column here and no class symbol in the drawing legend. That allocation is the
estimator's, and :mod:`client_boq.boq.groups` is where he makes it.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# How far a row's own arithmetic may be out before it is refused. The schedule is printed to 2 dp.
ROW_TOLERANCE_M = 0.05

#: A BLANK IS NOT A ZERO.
#:
#: ``soil_m``, ``rock_m`` and ``hard_above_rockhead_m`` are plain floats defaulting to ``0.0``, which
#: is right for the arithmetic and wrong for a reader: a cell nobody could read arrives as the same
#: value as a cell printed ``0.00``. And ``rock_m == 0`` is ordinary — a soil-only hole, which the
#: screen renders as an em dash — so "zero means unread" cannot be inferred downstream by anything.
#:
#: So a reader that cannot make out a cell names it here instead of guessing at it. The names are the
#: field names; the values are what a person sees. Nothing consumes this to change a number — it
#: exists so :meth:`StationSchedule.unread_rows` can say the row out loud and :meth:`usable` can
#: refuse it, which is the whole of the honest-degradation rule applied to a cell rather than a page.
UNREADABLE = {
    "station": "the station name",
    "easting": "the easting",
    "northing": "the northing",
    "ground_level_mpd": "the ground level",
    "rockhead_level_mpd": "the rockhead level",
    "length_m": "the tentative borehole length",
    "max_boring_m": "the maximum boring length",
    "soil_m": "the length in soil",
    "hard_above_rockhead_m": "the length in hard material above rockhead",
    "rock_m": "the length in rock",
    "standpipe": "the standpipe tick",
    "piezometer": "the piezometer tick",
}


class Station(BaseModel):
    """One proposed borehole, as scheduled."""

    station: str = ""              # "CE19-ABH19"
    kind: str = "BH"               # BH | TP
    easting: Optional[float] = None
    northing: Optional[float] = None
    ground_level_mpd: Optional[float] = None
    rockhead_level_mpd: Optional[float] = None
    length_m: Optional[float] = None          # tentative borehole length
    max_boring_m: Optional[float] = None
    soil_m: float = 0.0                       # tentative length in soil
    hard_above_rockhead_m: float = 0.0        # rock/corestone/boulder/ARM above rockhead
    rock_m: float = 0.0                       # expected length in rock
    standpipe: bool = False
    piezometer: bool = False
    sheet: str = ""                           # the drawing it was read from
    notes: list[str] = Field(default_factory=list)
    #: Field names whose cell was on the sheet but could not be read — see ``UNREADABLE`` below.
    #: Empty on a schedule somebody typed: a person who types a row has read every cell of it.
    unread: list[str] = Field(default_factory=list)

    @property
    def total_m(self) -> float:
        return self.soil_m + self.rock_m

    @property
    def instruments(self) -> int:
        return int(self.standpipe) + int(self.piezometer)

    def reconciles(self, tolerance: float = ROW_TOLERANCE_M) -> bool:
        """Does the row satisfy its own arithmetic? ``length = soil + rock``."""
        if self.length_m is None:
            return True                        # nothing to check against
        return abs(self.length_m - self.total_m) <= tolerance

    def discrepancy(self) -> Optional[str]:
        if self.reconciles():
            return None
        return (f"{self.station}: soil {self.soil_m:g} + rock {self.rock_m:g} = {self.total_m:g} m "
                f"against a tentative borehole length of {self.length_m:g} m")

    def unread_note(self) -> Optional[str]:
        """The cells this row is missing, named. ``None`` when every cell was read."""
        if not self.unread:
            return None
        cells = ", ".join(UNREADABLE.get(f, f) for f in self.unread)
        return (f"{self.station or 'an unnamed row'}: {cells} could not be read off the sheet. "
                f"A blank is not a zero — type the value in or say the row does not belong.")

    def measures_nothing(self) -> bool:
        """No soil and no rock. A borehole that drills no metres is not a borehole.

        ``rock_m == 0`` alone is ordinary (a soil-only hole). Both zero is not: the row recovers no
        length, drives no cost, and appears in no total — so it is either a cell nobody read or a
        row that does not belong. Either way it is worth a sentence, because
        :meth:`reconciles` cannot see it (``length_m is None`` short-circuits to True, and
        ``0 + 0 = 0`` satisfies any stated length of zero)."""
        return not self.soil_m and not self.rock_m


class TrialPit(BaseModel):
    """One proposed trial pit. Depth is the client's; the plan geometry is GI/100's."""

    station: str = ""
    easting: Optional[float] = None
    northing: Optional[float] = None
    ground_level_mpd: Optional[float] = None
    depth_m: float = 0.0                      # tentative excavation depth
    max_depth_m: Optional[float] = None
    depth_in_soil_m: Optional[float] = None
    sheet: str = ""


class StationSchedule(BaseModel):
    """The whole schedule, plus whatever the reader could not do cleanly."""

    set_id: str = ""
    source_sheet: str = ""                    # "60740338/GI/210"
    stations: list[Station] = Field(default_factory=list)
    trial_pits: list[TrialPit] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    confirmed_by: str = ""                    # nothing prices from an unconfirmed extraction

    # --- the sums the bill can be checked against ------------------------------------------------
    def soil_m(self) -> float:
        return round(sum(s.soil_m for s in self.stations), 3)

    def rock_m(self) -> float:
        return round(sum(s.rock_m for s in self.stations), 3)

    def hard_m(self) -> float:
        return round(sum(s.hard_above_rockhead_m for s in self.stations), 3)

    def total_m(self) -> float:
        return round(self.soil_m() + self.rock_m(), 3)

    def hole_count(self) -> int:
        return len(self.stations)

    def standpipes(self) -> int:
        return sum(1 for s in self.stations if s.standpipe)

    def piezometers(self) -> int:
        return sum(1 for s in self.stations if s.piezometer)

    def instruments(self) -> int:
        """Standpipes plus piezometers — which is exactly the AGMD count, one per instrument."""
        return self.standpipes() + self.piezometers()

    def deepest(self) -> float:
        return max((s.total_m for s in self.stations), default=0.0)

    def holes_past(self, depth_m: float) -> int:
        """How many holes cross a depth band. Deep metres are slower metres, and the measurement
        rules stage drilling in 20 m lengths, so this drives both cost and a possible query."""
        return sum(1 for s in self.stations if s.total_m > depth_m)

    def index(self) -> dict[str, Station]:
        return {s.station: s for s in self.stations}

    # --- the honesty checks -----------------------------------------------------------------------
    #
    # Four of them, and they catch four different ways a row can be wrong. `bad_rows` was the only
    # one for a long time, and it is the narrowest: it needs a `length_m` to check against and a
    # row that fails it is at least a row somebody READ. The other three exist because a reader can
    # fail in ways arithmetic cannot see — a cell it could not make out, a name it read twice, and a
    # row it emptied. None of them repairs anything; each is a sentence naming a station.
    def bad_rows(self) -> list[str]:
        """Rows that fail their own arithmetic. These are never priced."""
        return [note for note in (s.discrepancy() for s in self.stations) if note]

    def unread_rows(self) -> list[str]:
        """Rows carrying a cell the reader could not make out. The blank-is-not-a-zero check."""
        return [note for note in (s.unread_note() for s in self.stations) if note]

    def empty_rows(self) -> list[str]:
        """Rows that drill no metres at all — invisible to every other check, and to every total.

        A row whose soil or rock cell is already marked unread is skipped: :meth:`unread_rows` has
        said the same thing about it more precisely, and two sentences about one row is how a screen
        stops being read. A row marked unread somewhere ELSE — the easting, say — still gets its
        note, because nothing has yet accounted for the missing metres.
        """
        return [f"{s.station or 'an unnamed row'}: no length in soil and none in rock, so the row "
                f"adds nothing to either total. Either a cell was missed or the row does not belong."
                for s in self.stations
                if s.measures_nothing() and not {"soil_m", "rock_m"} & set(s.unread)]

    def duplicate_names(self) -> list[str]:
        """Station names appearing more than once.

        :meth:`index` is keyed on the name, so a repeated one silently overwrites its twin and the
        schedule quietly gets shorter than the sheet. A model transcribing 91 rows off a picture is
        exactly the thing that repeats a name; nothing else here would ever notice.
        """
        seen: dict[str, int] = {}
        for s in self.stations:
            seen[s.station] = seen.get(s.station, 0) + 1
        return [f"{name or 'an unnamed row'}: appears {n} times, and only the last one survives — "
                f"the schedule is keyed on the station name."
                for name, n in seen.items() if n > 1]

    def problems(self) -> list[str]:
        """Every honesty check, in one list. Empty means the take-off can be priced from."""
        return (self.bad_rows() + self.unread_rows() + self.empty_rows() + self.duplicate_names())

    def usable(self) -> bool:
        return bool(self.stations) and not self.problems()
