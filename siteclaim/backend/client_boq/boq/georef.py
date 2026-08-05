"""BOQ — putting a station on a drawing sheet, arithmetically.

Bucket: **Deterministic**. No vision, no model, no image pipeline. Two known points and the survey
coordinates the schedule already carries are enough to place all ninety-one holes, and the result is
checkable: plot them and they land on the printed symbols.

WHY THIS EXISTS
---------------
The client bills 80 Class A and 11 Class B rig moves and never says which holes are which. Deciding
means looking at each station on the site plan — and the site plan is five 1:2000 sheets. Ninety-one
holes hunted across five sheets is an afternoon's work that nobody enjoys and everybody rushes.

So: render each sheet **once**, and crop that one render ninety-one ways, centred on each station's
own surveyed easting and northing. The estimator gets ninety-one small pictures instead of five big
ones, and the browser downloads one image per sheet.

WHY IT IS NOT A MODEL
---------------------
Asking a vision model for a pixel coordinate is asking it to be a ruler, which it is not — and a
station placed thirty metres out is worse than no picture, because it looks right. A drawing sheet
prints its grid: crosses or ticks at round HK1980 coordinates, with the values written beside them.
Read two of those (a person types them once per sheet, or an extraction proposes them for
confirmation) and every other point on the sheet follows by arithmetic that cannot be wrong.

THE MAP
-------
Survey grids and page coordinates are both rectangular and the drawing is axis-aligned, so the
transform is a scale and a shift per axis — with **northing inverted**, because north is up the page
and page ``y`` grows downward:

    x = (easting  − e0) / metres_across  ·  and the same for y, flipped

Rotation is not supported and is not silently approximated: a rotated sheet is refused by name. Two
control points give four numbers, which is exactly enough and no more, so a bad mark cannot hide —
:meth:`SheetRegistration.problems` reports a scale mismatch between the axes rather than averaging it
away, since a drawing is isotropic and a mismatch means somebody mistyped a coordinate.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.schedule import StationSchedule

# A drawing is isotropic: one metre across is one metre down. If the two axes disagree by more than
# this, a control point is wrong — and reporting that is far more useful than quietly splitting the
# difference and placing every station slightly askew.
SCALE_TOLERANCE = 0.02          # 2%

# The default window a tile shows. Wide enough to carry the context that decides an access class —
# a road, a stream, a contour crowding — and tight enough that the station is unmistakably the
# subject of the picture.
DEFAULT_WINDOW_M = 100.0


class GridMark(BaseModel):
    """One printed grid intersection: what it says, and where it sits on the page.

    ``x`` and ``y`` are fractions of the page (0–1), not pixels, so a registration survives a
    re-render at any DPI — which matters, because the tile render and the full-page view do not use
    the same one.
    """

    easting: float
    northing: float
    x: float                    # 0 = left edge of the page, 1 = right
    y: float                    # 0 = top edge, 1 = bottom
    label: str = ""             # what is printed beside it, kept for checking


class Placed(BaseModel):
    """A station's position on a sheet, and whether that position is actually on it."""

    station: str
    x: float
    y: float
    on_sheet: bool = True       # False when the point falls outside the page: it is on another sheet


class SheetRegistration(BaseModel):
    """One drawing sheet, tied to the survey grid by two of its own printed marks."""

    sheet: str = ""             # "60740338/GI/201"
    part_id: str = ""           # the part the page lives in, so a caller can fetch the render
    page: int = 1
    marks: list[GridMark] = Field(default_factory=list)
    confirmed_by: str = ""      # '' = proposed, not yet checked against the sheet by a person

    # ------------------------------------------------------------------ checks
    def problems(self) -> list[str]:
        """Everything wrong with this registration. Empty means it can be used.

        Refuses rather than approximates. A registration that is 3% out places a station three
        metres from where it is, which is invisible on the tile and wrong in exactly the way that
        makes somebody trust it.
        """
        if len(self.marks) < 2:
            return [f"{self.sheet or 'this sheet'} needs two grid marks to be located; "
                    f"it has {len(self.marks)}"]

        a, b = self.marks[0], self.marks[1]
        problems: list[str] = []
        if a.easting == b.easting or a.x == b.x:
            problems.append("both grid marks share an easting (or a page column) — "
                            "they must differ across the page")
        if a.northing == b.northing or a.y == b.y:
            problems.append("both grid marks share a northing (or a page row) — "
                            "they must differ down the page")
        if problems:
            return problems

        across, down = self._metres_across(), self._metres_down()
        if across <= 0 or down <= 0:
            return ["the grid marks are the wrong way round: page coordinates must increase "
                    "eastward and northward must run up the page"]

        drift = abs(across - down) / max(across, down)
        if drift > SCALE_TOLERANCE:
            problems.append(
                f"the sheet reads {across:.1f} m across and {down:.1f} m down — a drawing is the "
                f"same scale both ways, so one of the grid marks is mistyped "
                f"({drift * 100:.1f}% apart)")
        return problems

    def usable(self) -> bool:
        return not self.problems()

    # ------------------------------------------------------------------ the map
    def _metres_across(self) -> float:
        """Metres spanned by the full page width."""
        a, b = self.marks[0], self.marks[1]
        return (b.easting - a.easting) / (b.x - a.x)

    def _metres_down(self) -> float:
        """Metres spanned by the full page height. Positive: northing falls as y grows."""
        a, b = self.marks[0], self.marks[1]
        return (a.northing - b.northing) / (b.y - a.y)

    def metres_per_page(self) -> tuple[float, float]:
        """(across, down) in metres — what a tile window is measured against."""
        self._require_usable()
        return self._metres_across(), self._metres_down()

    def locate(self, easting: float, northing: float) -> tuple[float, float]:
        """Survey coordinates to page fractions. May fall outside 0–1; that is information."""
        self._require_usable()
        a = self.marks[0]
        return (a.x + (easting - a.easting) / self._metres_across(),
                a.y + (a.northing - northing) / self._metres_down())

    def place(self, station: str, easting: float, northing: float) -> Placed:
        x, y = self.locate(easting, northing)
        return Placed(station=station, x=x, y=y, on_sheet=0.0 <= x <= 1.0 and 0.0 <= y <= 1.0)

    def crop(self, easting: float, northing: float,
             window_m: float = DEFAULT_WINDOW_M) -> "CropBox":
        """A square window of the page, in fractions, centred on a point.

        Returned unclamped and marked instead. A station near the sheet edge produces a box that
        runs off the page, and the honest thing is to say so — a silently shifted crop is a picture
        of somewhere the estimator did not ask about, captioned with the station he did.
        """
        self._require_usable()
        x, y = self.locate(easting, northing)
        across, down = self._metres_across(), self._metres_down()
        half_x = (window_m / 2.0) / across
        half_y = (window_m / 2.0) / down
        box = CropBox(x0=x - half_x, y0=y - half_y, x1=x + half_x, y1=y + half_y,
                      centre_x=x, centre_y=y, window_m=window_m)
        return box

    def _require_usable(self) -> None:
        problems = self.problems()
        if problems:
            raise ValueError(f"sheet {self.sheet or '?'} is not located: {'; '.join(problems)}")


class CropBox(BaseModel):
    """A window of a page, as fractions. What ``MapCrop`` turns into a CSS transform."""

    x0: float
    y0: float
    x1: float
    y1: float
    centre_x: float
    centre_y: float
    window_m: float = DEFAULT_WINDOW_M

    @property
    def clipped(self) -> bool:
        """Whether the window runs off the page — the station sits near a sheet edge."""
        return self.x0 < 0.0 or self.y0 < 0.0 or self.x1 > 1.0 or self.y1 > 1.0


class SheetPlot(BaseModel):
    """Every station placed on one sheet, and what did not land.

    The self-check. Render the sheet, draw these, and every mark should sit on a printed borehole
    symbol. Nothing else in this module needs proving; this is the proof.
    """

    sheet: str = ""
    placed: list[Placed] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)

    def on_sheet(self) -> list[Placed]:
        return [p for p in self.placed if p.on_sheet]

    def elsewhere(self) -> list[str]:
        """Stations that fall outside this page — they belong to another sheet, not to nowhere."""
        return [p.station for p in self.placed if not p.on_sheet]


def plot(schedule: StationSchedule, registration: SheetRegistration) -> SheetPlot:
    """Place every located station in the schedule onto one sheet.

    Stations without coordinates are skipped rather than placed at the origin, which would put them
    in the top-left corner looking like a real answer.
    """
    problems = registration.problems()
    if problems:
        return SheetPlot(sheet=registration.sheet, problems=problems)

    placed = [
        registration.place(station.station, station.easting, station.northing)
        for station in schedule.stations
        if station.easting is not None and station.northing is not None
    ]
    missing = [s.station for s in schedule.stations
               if s.easting is None or s.northing is None]
    notes = ([f"{len(missing)} station(s) have no coordinates and cannot be placed: "
              f"{', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}"] if missing else [])
    return SheetPlot(sheet=registration.sheet, placed=placed, problems=notes)


def crops_for(schedule: StationSchedule, registration: SheetRegistration,
              window_m: float = DEFAULT_WINDOW_M) -> dict[str, CropBox]:
    """One crop box per station that lands on this sheet. The Holes screen's whole data need.

    Keyed by station so the frontend joins it to the schedule row it already has, and computed for
    the on-sheet ones only — a station belonging to another sheet gets no tile here rather than a
    tile of the wrong place.
    """
    if not registration.usable():
        return {}
    out: dict[str, CropBox] = {}
    for station in schedule.stations:
        if station.easting is None or station.northing is None:
            continue
        placed = registration.place(station.station, station.easting, station.northing)
        if placed.on_sheet:
            out[station.station] = registration.crop(station.easting, station.northing, window_m)
    return out


def sheet_for(station_easting: float, station_northing: float,
              registrations: list[SheetRegistration]) -> Optional[SheetRegistration]:
    """Which of several sheets a point actually falls on.

    The site plan is five sheets and a station is on exactly one of them. Returns the first that
    contains the point, or ``None`` — never a nearest-match, because a station that is on no sheet
    is a fact worth surfacing (the coordinate is wrong, or a sheet is missing from the set).
    """
    for registration in registrations:
        if not registration.usable():
            continue
        placed = registration.place("", station_easting, station_northing)
        if placed.on_sheet:
            return registration
    return None
