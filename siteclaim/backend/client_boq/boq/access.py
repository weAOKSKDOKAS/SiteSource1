"""BOQ — access evidence: everything that can be KNOWN about reaching a group of holes.

Bucket: **Evidence.** This module assembles; it never concludes.

THE LINE, AND IT IS ABSOLUTE
----------------------------
The access class (PS 7.01B: A road or manual · B needs a temporary platform · C helicopter only)
is worth real money — the bill prices 80 Class A rig moves against 11 Class B, and a platform is a
cost that lands on the rig-move item. **No document in the tender says which hole is which.** GI/210
has no class column and the drawing legend carries four symbols, none of which denotes a class. So
the classification is the estimator's judgement, made alone, on a hillside he has probably not
walked.

What this module does is put the evidence in front of him: where the cluster is, what the imagery
shows, how far from a road, what the drawing crop looks like. What it must **never** do is answer.
:attr:`ClusterEvidence.proposed_class` exists and is permanently ``""`` — it is here as a statement
that nothing writes it, in the same way :class:`DepartureProposal` has no status field. A machine
that says "this looks like Class B" would be believed, and it would be guessing from a photograph.

WHY A CREDENTIAL IS NEVER A BLOCKER, AND NEVER LEAVES THE SERVER
----------------------------------------------------------------
The Lands Department basemap and imagery are keyless and have the best rural New Territories
coverage there is, so the map works out of the box. Satellite stills, Street View and road distance
need a Google key. Two rules follow:

* an absent key makes one KIND of evidence unavailable and says so by name — it never stops the
  map, the cards, or the classification;
* a present key stays on the server. Every keyed link in this payload is a path back into **this**
  API, which fetches server-side. A URL with a key in it, handed to a browser, is a published
  credential no matter what the referrer policy says.
"""

from __future__ import annotations

import math
from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.groups import CLASS_MEANING, CLASSES, HoleGroup, cluster
from client_boq.boq.hk1980 import maps_link, provider_config, to_wgs84
from client_boq.boq.schedule import StationSchedule

# Evidence kinds, so a card can lay them out without matching on prose.
EVIDENCE_MAP = "map"                    # the keyless per-point map link
EVIDENCE_IMAGERY = "imagery"            # LandsD aerial imagery, in-app, keyless
EVIDENCE_DRAWING = "drawing"            # the georeferenced crop of the borehole details sheet
EVIDENCE_SATELLITE = "satellite"        # Google static satellite still
EVIDENCE_STREET_VIEW = "street_view"    # Google Street View still
EVIDENCE_ROAD_DISTANCE = "road_distance"  # Google Distance Matrix — metres by road, not by crow

EVIDENCE_ORDER = (EVIDENCE_IMAGERY, EVIDENCE_DRAWING, EVIDENCE_MAP, EVIDENCE_SATELLITE,
                  EVIDENCE_STREET_VIEW, EVIDENCE_ROAD_DISTANCE)

EVIDENCE_LABEL = {
    EVIDENCE_IMAGERY: "Aerial imagery",
    EVIDENCE_DRAWING: "Drawing crop",
    EVIDENCE_MAP: "Open in a map",
    EVIDENCE_SATELLITE: "Satellite still",
    EVIDENCE_STREET_VIEW: "Street View",
    EVIDENCE_ROAD_DISTANCE: "Distance by road",
}

NO_KEY = ("needs a Google Maps key. The map, the imagery and the drawing crop do not — this one "
          "kind of evidence is dark, and nothing else is affected.")


class Evidence(BaseModel):
    """One thing a person can look at, or the named reason they cannot."""

    kind: str
    label: str
    #: Where to get it. A path into this API when the source needs a credential, an external URL
    #: only when it needs none. Empty when unavailable.
    url: str = ""
    #: True when the URL is somebody else's site and opening it leaves the app.
    external: bool = False
    available: bool = True
    unavailable_reason: str = ""


class ClusterEvidence(BaseModel):
    """One proximity cluster, everything known about reaching it, and no verdict."""

    label: str
    stations: list[str] = Field(default_factory=list)
    holes: int = 0
    lat: float = 0.0
    lon: float = 0.0
    #: How far the furthest station sits from the centroid. A cluster 400 m across is not one place.
    spread_m: float = 0.0
    soil_m: float = 0.0
    rock_m: float = 0.0
    deepest_m: float = 0.0
    #: What a HUMAN has already decided, per class, plus "" for the undecided. Read, never written.
    decided: dict[str, int] = Field(default_factory=dict)
    #: PERMANENTLY EMPTY. Declared so that "nothing proposes a class" is a property of the type
    #: rather than a habit — see the module docstring.
    proposed_class: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def undecided(self) -> int:
        return self.decided.get("", 0)


class AccessBoard(BaseModel):
    """Every cluster, and what the board as a whole could not do."""

    clusters: list[ClusterEvidence] = Field(default_factory=list)
    radius_m: float = 0.0
    unlocated: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    providers: dict = Field(default_factory=dict)


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def _metres_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Flat-earth distance in metres. Fine over a cluster: Hong Kong is 50 km across."""
    mean_lat = math.radians((a[0] + b[0]) / 2)
    dy = (b[0] - a[0]) * 111_320.0
    dx = (b[1] - a[1]) * 111_320.0 * math.cos(mean_lat)
    return math.hypot(dx, dy)


def _evidence_for(set_id: str, label: str, lat: float, lon: float, *, has_drawing: bool,
                  providers: dict) -> list[Evidence]:
    google = providers.get("google", {})
    keyed = bool(google.get("key_present"))
    ref = f"/client-boq/site/{set_id}/access/still?lat={lat:.6f}&lon={lon:.6f}"
    items = [
        Evidence(kind=EVIDENCE_IMAGERY, label=EVIDENCE_LABEL[EVIDENCE_IMAGERY],
                 url="", available=True,
                 unavailable_reason=""),
        Evidence(kind=EVIDENCE_DRAWING, label=EVIDENCE_LABEL[EVIDENCE_DRAWING],
                 available=has_drawing,
                 unavailable_reason=("" if has_drawing else
                                     "this sheet has no grid marks yet — read the coordinates "
                                     "beside any two grid crosses and every station on it "
                                     "follows by arithmetic")),
        Evidence(kind=EVIDENCE_MAP, label=EVIDENCE_LABEL[EVIDENCE_MAP],
                 url=maps_link(lat, lon), external=True, available=True),
        Evidence(kind=EVIDENCE_SATELLITE, label=EVIDENCE_LABEL[EVIDENCE_SATELLITE],
                 url=f"{ref}&kind=satellite" if keyed else "", available=keyed,
                 unavailable_reason="" if keyed else f"Satellite stills {NO_KEY}"),
        Evidence(kind=EVIDENCE_STREET_VIEW, label=EVIDENCE_LABEL[EVIDENCE_STREET_VIEW],
                 url=f"{ref}&kind=street_view" if keyed else "", available=keyed,
                 unavailable_reason="" if keyed else f"Street View {NO_KEY}"),
        Evidence(kind=EVIDENCE_ROAD_DISTANCE, label=EVIDENCE_LABEL[EVIDENCE_ROAD_DISTANCE],
                 url="", available=False,
                 unavailable_reason=("Road distance needs a Google key AND a road to measure to. "
                                     "Neither the origin nor the destination is chosen yet — the "
                                     "nearest road is a judgement, not a lookup."
                                     if not keyed else
                                     "Pick the road access point on the map and this measures to "
                                     "it. Until somebody picks one there is nothing to measure.")),
    ]
    # `label` is used as-is by the card, and the imagery one is in-app, so it carries no URL. The
    # ordering is the declaration's, not the dict's.
    order = {kind: n for n, kind in enumerate(EVIDENCE_ORDER)}
    return sorted(items, key=lambda e: order.get(e.kind, 99))


def board(schedule: StationSchedule, *, set_id: str, radius_m: float = 250.0,
          classes: Optional[dict[str, str]] = None,
          located_sheets: Optional[set[str]] = None,
          located_stations: Optional[set[str]] = None) -> AccessBoard:
    """Assemble the access board: the proximity clusters, and the evidence for each.

    ``classes`` is what people have ALREADY decided, station → class, read only so a card can show
    how much of itself is still open. Nothing here writes one.

    ``located_stations`` is the set of stations that land on a registered, usable site-plan sheet
    — computed by COORDINATES (``georef.sheet_for``), not by name. ``located_sheets`` matches on
    ``Station.sheet``, which is the SCHEDULE sheet the row was read from (GI/210), a different
    family from the site-plan sheets registrations are of (GI/201…) — so name intersection alone
    never lights the drawing evidence. Both are kept: names for a caller that genuinely registered
    the schedule sheet, coordinates for the real case.
    """
    decided_by_station = classes or {}
    out = AccessBoard(radius_m=radius_m, providers=provider_config())
    proposals: list[HoleGroup] = cluster(schedule, radius_m=radius_m)
    index = schedule.index()

    for group in proposals:
        points: list[tuple[float, float]] = []
        for name in group.stations:
            station = index.get(name)
            if station is None or station.easting is None or station.northing is None:
                continue
            points.append(to_wgs84(station.easting, station.northing))

        if not points:
            # `cluster` puts every coordinate-less station in one group of its own rather than
            # dropping them. They have no place on a map, and saying so is the whole of the honest
            # answer — a cluster invented at the centre of the others would be a lie with a pin in it.
            out.unlocated.extend(group.stations)
            continue

        lat, lon = _centroid(points)
        spread = max((_metres_between((lat, lon), p) for p in points), default=0.0)
        decided: dict[str, int] = {"": 0, **{name: 0 for name in CLASSES}}
        for name in group.stations:
            decided[decided_by_station.get(name, "") or ""] = (
                decided.get(decided_by_station.get(name, "") or "", 0) + 1)

        sheets = {index[n].sheet for n in group.stations if n in index and index[n].sheet}
        has_drawing = (bool(located_sheets and sheets & located_sheets)
                       or bool(located_stations and set(group.stations) & located_stations))

        item = ClusterEvidence(
            label=group.label, stations=list(group.stations), holes=group.hole_count,
            lat=round(lat, 7), lon=round(lon, 7), spread_m=round(spread, 1),
            soil_m=group.soil_m, rock_m=group.rock_m, deepest_m=group.deepest_m,
            decided=decided,
            evidence=_evidence_for(set_id, group.label, lat, lon,
                                   has_drawing=has_drawing, providers=out.providers),
        )
        if spread > radius_m:
            item.notes.append(
                f"the stations in this cluster are up to {spread:,.0f} m from its centre, which is "
                f"further than the {radius_m:g} m that grouped them — single-link clustering "
                f"chains, so this may be a ridge rather than a place. Worth splitting.")
        if item.undecided:
            item.notes.append(
                f"{item.undecided} of {item.holes} hole(s) here have no access class yet. Nothing "
                f"on this card proposes one: {CLASS_MEANING['B']} is a judgement about ground "
                f"nobody has stood on, and a machine reading a photograph would be guessing.")
        out.clusters.append(item)

    if out.unlocated:
        out.problems.append(
            f"{len(out.unlocated)} station(s) have no coordinates on the schedule, so they are on "
            f"no cluster and no map: {', '.join(sorted(out.unlocated)[:8])}"
            f"{' …' if len(out.unlocated) > 8 else ''}")
    return out
