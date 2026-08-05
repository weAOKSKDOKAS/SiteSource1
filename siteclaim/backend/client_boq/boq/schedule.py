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
    def bad_rows(self) -> list[str]:
        """Rows that fail their own arithmetic. These are never priced."""
        return [note for note in (s.discrepancy() for s in self.stations) if note]

    def usable(self) -> bool:
        return bool(self.stations) and not self.bad_rows()
