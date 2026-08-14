"""The nearest MAPPED road to each hole, from OpenStreetMap — a measurement, not a verdict.

WHAT THIS ANSWERS, and what it deliberately does not. "How far is this hole from the nearest
road anybody has mapped" is a measurement: given road geometry and a coordinate, the distance is
arithmetic and two people get the same number. "Where is this site entered from" and "is this
hole Class A or Class B" are judgements — the first is the human-picked access point in
`client_boq_road_points`, the second is the estimator's, and neither is inferred here. A hole
forty metres from a road it cannot be reached from is a real and ordinary thing on a hillside.

So this produces EVIDENCE beside a decision, never the decision:

* the distance is reported with the road's OSM id and its name, so it can be looked at;
* nothing writes an access class — `access.proposed_class` stays permanently empty;
* a road that is not in OpenStreetMap does not exist to this module, which is why the figure is
  always labelled "nearest MAPPED road" and never "nearest road".

WHY ONE QUERY FOR THE WHOLE SITE. Ninety-nine holes is ninety-nine round trips if asked hole by
hole, on a free volunteer-run endpoint with a published fair-use policy. One bounding-box query
returns every road in the area, and the per-hole nearest is then computed locally, exactly, from
the geometry — cheaper for them and faster for us.

NETWORK, so DEMO does not run it: Overpass is a real outbound call, and DEMO is offline by rule
(CLAUDE.md §6). In DEMO this reports honestly that it did not run rather than replaying a fixture
that would look like a measurement of the tender in front of you.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

#: The public endpoint. Overridable so an installation can point at its own instance — the fair-use
#: policy on the shared one is real, and a firm running this daily should host or mirror.
DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"

#: Which ways count as a road a rig could conceivably use. `track` and `service` are in on
#: purpose: on a New Territories GI site the access is usually exactly those, and leaving them out
#: would report a hole beside a farm track as 300 m from anything.
ROAD_CLASSES = (
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "service", "track", "living_street", "road",
)

#: Metres of padding around the site's own bounding box, so a road just outside it still counts.
BBOX_PAD_M = 600.0


class NearestRoad(BaseModel):
    """One hole and the closest mapped road to it."""

    station: str
    metres: float = 0.0
    #: OpenStreetMap way id, so the claim can be opened and checked.
    way_id: int = 0
    name: str = ""
    highway: str = ""
    #: The point ON the road that is nearest — what a line on the map would be drawn to.
    lat: float = 0.0
    lon: float = 0.0


class RoadReading(BaseModel):
    """What the query found, and everything it could not do — never an empty success."""

    nearest: list[NearestRoad] = Field(default_factory=list)
    #: Stations with coordinates that no mapped road came within reach of. Named, not dropped.
    unreached: list[str] = Field(default_factory=list)
    roads_seen: int = 0
    source: str = ""
    problems: list[str] = Field(default_factory=list)
    #: "" when it ran. Otherwise why it did not — no schedule, DEMO, network, nothing mapped.
    waiting_on: str = ""


def _metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Flat-earth metres between two WGS84 points. Fine over a site: Hong Kong is 50 km across."""
    mean_lat = math.radians((a[0] + b[0]) / 2)
    dy = (b[0] - a[0]) * 111_320.0
    dx = (b[1] - a[1]) * 111_320.0 * math.cos(mean_lat)
    return math.hypot(dx, dy)


def _nearest_on_segment(point: tuple[float, float], start: tuple[float, float],
                        end: tuple[float, float]) -> tuple[float, tuple[float, float]]:
    """Distance to a road SEGMENT and the closest point on it.

    Segment, not vertex: a straight 400 m run of road is two nodes, so measuring to the nearest
    NODE would report a hole beside its midpoint as 200 m away. Projected in local metres, which
    is what makes the perpendicular meaningful at this latitude.
    """
    mean_lat = math.radians(point[0])
    def xy(p: tuple[float, float]) -> tuple[float, float]:
        return (p[1] * 111_320.0 * math.cos(mean_lat), p[0] * 111_320.0)

    px, py = xy(point)
    ax, ay = xy(start)
    bx, by = xy(end)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return _metres_between(point, start), start
    # How far along the segment the perpendicular falls, clamped to its ends.
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    on = (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t)
    return _metres_between(point, on), on


def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """The query, as a string, so it can be read and tested without a network call.

    `out geom` returns each way's geometry inline — one response carries everything needed to
    measure against, with no second round trip to resolve node ids.
    """
    south, west, north, east = bbox
    classes = "|".join(ROAD_CLASSES)
    return (
        "[out:json][timeout:60];"
        f'way["highway"~"^({classes})$"]({south:.6f},{west:.6f},{north:.6f},{east:.6f});'
        "out geom;"
    )


def bbox_for(points: list[tuple[float, float]], pad_m: float = BBOX_PAD_M
             ) -> Optional[tuple[float, float, float, float]]:
    """The site's bounding box in WGS84, padded, or None when there is nothing to bound."""
    if not points:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    pad_lat = pad_m / 111_320.0
    mean_lat = math.radians(sum(lats) / len(lats))
    pad_lon = pad_m / (111_320.0 * max(math.cos(mean_lat), 0.1))
    return (min(lats) - pad_lat, min(lons) - pad_lon,
            max(lats) + pad_lat, max(lons) + pad_lon)


def nearest_roads(stations: dict[str, tuple[float, float]], ways: list[dict]) -> RoadReading:
    """PURE: given stations and road geometry, the nearest road to each. No network, no model.

    Separated from the fetch so the arithmetic is testable without touching OpenStreetMap — the
    same split the rest of this package uses, and the reason a road measurement can be asserted
    exactly rather than approximately.
    """
    reading = RoadReading(roads_seen=len(ways))
    for station, point in stations.items():
        best: Optional[NearestRoad] = None
        for way in ways:
            geometry = way.get("geometry") or []
            for i in range(len(geometry) - 1):
                a = (geometry[i]["lat"], geometry[i]["lon"])
                b = (geometry[i + 1]["lat"], geometry[i + 1]["lon"])
                metres, on = _nearest_on_segment(point, a, b)
                if best is None or metres < best.metres:
                    tags = way.get("tags") or {}
                    best = NearestRoad(
                        station=station, metres=round(metres, 1),
                        way_id=int(way.get("id") or 0),
                        name=tags.get("name") or tags.get("name:en") or "",
                        highway=tags.get("highway") or "",
                        lat=round(on[0], 7), lon=round(on[1], 7))
        if best is None:
            reading.unreached.append(station)
        else:
            reading.nearest.append(best)
    reading.nearest.sort(key=lambda r: r.station)
    if reading.unreached:
        reading.problems.append(
            f"{len(reading.unreached)} hole(s) had no mapped road anywhere in the area searched: "
            + ", ".join(sorted(reading.unreached)[:8])
            + (" …" if len(reading.unreached) > 8 else ""))
    return reading


def roads_near(station: str, point: tuple[float, float], ways: list[dict]) -> list[NearestRoad]:
    """PURE: every mapped road near ONE hole, nearest first — one row per way, not per segment.

    :func:`nearest_roads` answers "which road is closest to each hole", which is the measurement
    the map draws. This answers "what roads are around this hole", which is the context a route
    description needs: the closest way is often not the one you drive in on, and a note written
    from the single nearest road cannot say "come in off the named road and take the track".

    Still only arithmetic, and still no verdict — the caller decides how many of these are worth
    showing and to whom.
    """
    out: list[NearestRoad] = []
    for way in ways:
        geometry = way.get("geometry") or []
        best: Optional[NearestRoad] = None
        for i in range(len(geometry) - 1):
            a = (geometry[i]["lat"], geometry[i]["lon"])
            b = (geometry[i + 1]["lat"], geometry[i + 1]["lon"])
            metres, on = _nearest_on_segment(point, a, b)
            if best is None or metres < best.metres:
                tags = way.get("tags") or {}
                best = NearestRoad(
                    station=station, metres=round(metres, 1),
                    way_id=int(way.get("id") or 0),
                    name=tags.get("name") or tags.get("name:en") or "",
                    highway=tags.get("highway") or "",
                    lat=round(on[0], 7), lon=round(on[1], 7))
        if best is not None:
            out.append(best)
    out.sort(key=lambda r: r.metres)
    return out


def fetch_ways(bbox: tuple[float, float, float, float], *,
               endpoint: str = DEFAULT_ENDPOINT, timeout: float = 60.0) -> list[dict]:
    """One bounding-box query to Overpass. Raises on anything that is not a usable answer."""
    import httpx

    reply = httpx.post(endpoint, data={"data": overpass_query(bbox)}, timeout=timeout,
                       headers={"User-Agent": "SiteSource/1.0 (tender estimating; contact: "
                                              "the operator of this installation)"})
    reply.raise_for_status()
    payload = reply.json()
    return [e for e in payload.get("elements", []) if e.get("type") == "way"]
