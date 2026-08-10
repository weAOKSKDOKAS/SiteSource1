"""BOQ — HK1980 Grid to WGS84, arithmetically, with no dependency.

Bucket: **Deterministic.** The station schedule carries HK1980 Grid coordinates (EPSG:2326); a web
map, a satellite tile and a Google Maps link all speak WGS84 (EPSG:4326). This module is that
conversion and nothing else — pure arithmetic, ~1 m accuracy, no network, no key.

WHY IN-REPO RATHER THAN pyproj
------------------------------
`requirements.txt` is a pinned, verified-green set and pyproj is a heavy C wheel. The transform
itself is two textbook steps over published constants, small enough to own and test:

1. **Inverse Transverse Mercator** (grid → HK1980 geodetic), Snyder's series on the International
   1924 ellipsoid with EPSG:2326's own parameters. Sub-millimetre over Hong Kong's extent.
2. **Datum shift** HK1980 → WGS84: the published EPSG:1825 geocentric translation
   (−162.619, −276.959, −161.764 m), ~1 m accuracy — which is the accuracy of the officially
   published transformation itself, not a shortcut.

The Survey & Mapping Office publishes an independent approximation — *WGS84 ≈ HK80 latitude −5.5″,
longitude +8.8″* — and the test suite checks this module's datum shift lands on it. Two independent
published sources agreeing is the verification; if either constant set were misremembered they
would not.

CONSTANTS (all published; provenance beside each)
-------------------------------------------------
EPSG:2326 Hong Kong 1980 Grid — Transverse Mercator:
    latitude of origin   22°18′43.68″N        false northing 819069.80 m
    longitude of origin 114°10′42.80″E        false easting  836694.05 m
    scale factor 1.0 · ellipsoid International 1924 (a = 6378388 m, 1/f = 297)
EPSG:1825 Hong Kong 1980 → WGS84: dX −162.619, dY −276.959, dZ −161.764 (m).
"""

from __future__ import annotations

import math
import os
from typing import Optional

from pydantic import BaseModel

# --- ellipsoids -------------------------------------------------------------
INTL1924_A = 6378388.0
INTL1924_F = 1.0 / 297.0
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563

# --- EPSG:2326 projection parameters ---------------------------------------
LAT0 = math.radians(22.0 + 18.0 / 60.0 + 43.68 / 3600.0)     # 22°18′43.68″N
LON0 = math.radians(114.0 + 10.0 / 60.0 + 42.80 / 3600.0)    # 114°10′42.80″E
K0 = 1.0
FALSE_EASTING = 836694.05
FALSE_NORTHING = 819069.80

# --- EPSG:1825 geocentric translation, HK1980 -> WGS84 ----------------------
DX, DY, DZ = -162.619, -276.959, -161.764

# Hong Kong's own extent, generously margined. A converted point outside this box is a wrong
# coordinate (or a wrong constant), and saying so beats plotting it in the sea off Taiwan.
HK_LAT_MIN, HK_LAT_MAX = 22.1, 22.6
HK_LON_MIN, HK_LON_MAX = 113.8, 114.5


def _meridian_arc(a: float, e2: float, lat: float) -> float:
    """Snyder 3-21: the meridian distance from the equator to ``lat``."""
    e4, e6 = e2 * e2, e2 * e2 * e2
    return a * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lat)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
                - (35 * e6 / 3072) * math.sin(6 * lat))


def grid_to_hk80(easting: float, northing: float) -> tuple[float, float]:
    """EPSG:2326 grid metres → HK1980 geodetic (lat, lon) in degrees. Snyder's inverse TM."""
    a, f = INTL1924_A, INTL1924_F
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    m = _meridian_arc(a, e2, LAT0) + (northing - FALSE_NORTHING) / K0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256))
    foot = (mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))

    sin_f, cos_f, tan_f = math.sin(foot), math.cos(foot), math.tan(foot)
    c1 = ep2 * cos_f * cos_f
    t1 = tan_f * tan_f
    n1 = a / math.sqrt(1 - e2 * sin_f * sin_f)
    r1 = a * (1 - e2) / (1 - e2 * sin_f * sin_f) ** 1.5
    d = (easting - FALSE_EASTING) / (n1 * K0)

    lat = foot - (n1 * tan_f / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ep2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * ep2 - 3 * c1 * c1) * d ** 6 / 720)
    lon = LON0 + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * ep2 + 24 * t1 * t1) * d ** 5 / 120) / cos_f
    return math.degrees(lat), math.degrees(lon)


def hk80_to_grid(lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """HK1980 geodetic degrees → EPSG:2326 grid metres. The forward map, kept for the round-trip
    test and for anything that later needs to plot a WGS84 point back onto a drawing."""
    a, f = INTL1924_A, INTL1924_F
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)

    sin_l, cos_l, tan_l = math.sin(lat), math.cos(lat), math.tan(lat)
    n_ = a / math.sqrt(1 - e2 * sin_l * sin_l)
    t = tan_l * tan_l
    c = ep2 * cos_l * cos_l
    a_ = (lon - LON0) * cos_l

    m = _meridian_arc(a, e2, lat)
    m0 = _meridian_arc(a, e2, LAT0)
    x = K0 * n_ * (a_ + (1 - t + c) * a_ ** 3 / 6
                   + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * a_ ** 5 / 120)
    y = K0 * (m - m0 + n_ * tan_l * (a_ ** 2 / 2
                                     + (5 - t + 9 * c + 4 * c * c) * a_ ** 4 / 24
                                     + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * a_ ** 6 / 720))
    return FALSE_EASTING + x, FALSE_NORTHING + y


def _geodetic_to_xyz(lat_deg: float, lon_deg: float, a: float, f: float) -> tuple[float, float, float]:
    e2 = f * (2 - f)
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    n_ = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return (n_ * math.cos(lat) * math.cos(lon),
            n_ * math.cos(lat) * math.sin(lon),
            n_ * (1 - e2) * math.sin(lat))


def _xyz_to_geodetic(x: float, y: float, z: float, a: float, f: float) -> tuple[float, float]:
    e2 = f * (2 - f)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(6):                                   # converges to <1e-12 rad in 3-4 passes
        n_ = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * n_ * math.sin(lat), p)
    return math.degrees(lat), math.degrees(math.atan2(y, x))


def hk80_to_wgs84(lat_deg: float, lon_deg: float) -> tuple[float, float]:
    """The EPSG:1825 datum shift, at ellipsoid height zero — ~1 m, the published accuracy."""
    x, y, z = _geodetic_to_xyz(lat_deg, lon_deg, INTL1924_A, INTL1924_F)
    return _xyz_to_geodetic(x + DX, y + DY, z + DZ, WGS84_A, WGS84_F)


def to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """HK1980 Grid metres → WGS84 (lat, lon) degrees. The one call everything else uses."""
    return hk80_to_wgs84(*grid_to_hk80(easting, northing))


def in_hong_kong(lat: float, lon: float) -> bool:
    return HK_LAT_MIN <= lat <= HK_LAT_MAX and HK_LON_MIN <= lon <= HK_LON_MAX


def maps_link(lat: float, lon: float) -> str:
    """The keyless per-point Google Maps link — opens the map app centred on the point."""
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


class StationPosition(BaseModel):
    """One station, in both worlds, with the evidence links a key-free client can use now."""

    station: str
    easting: float
    northing: float
    lat: float
    lon: float
    in_hong_kong: bool
    maps_url: str


def positions(schedule) -> tuple[list[StationPosition], list[str]]:
    """Every located station in WGS84, and the ones that could not be placed — named, not dropped.

    A converted point OUTSIDE Hong Kong is refused into the list and reported instead: a wrong
    coordinate plotted confidently on a satellite map is exactly the kind of picture somebody
    trusts.
    """
    out: list[StationPosition] = []
    problems: list[str] = []
    for station in schedule.stations:
        if station.easting is None or station.northing is None:
            problems.append(f"{station.station}: no coordinates on the schedule")
            continue
        lat, lon = to_wgs84(station.easting, station.northing)
        ok = in_hong_kong(lat, lon)
        if not ok:
            problems.append(
                f"{station.station}: ({station.easting:,.1f}, {station.northing:,.1f}) converts "
                f"to ({lat:.5f}, {lon:.5f}), which is outside Hong Kong — the schedule's "
                f"coordinate is wrong, not the map")
            continue
        out.append(StationPosition(
            station=station.station, easting=station.easting, northing=station.northing,
            lat=round(lat, 7), lon=round(lon, 7), in_hong_kong=True,
            maps_url=maps_link(lat, lon)))
    return out, problems


# ---------------------------------------------------------------------------
# The provider seam — what the map surface may call, given what is configured.
# ---------------------------------------------------------------------------
# The Lands Department basemap is free, keyless and the best rural-NT coverage, so it is the
# default and needs nothing. Everything Google is behind GOOGLE_MAPS_API_KEY: absent, the surface
# says that evidence type is unavailable — it never blocks the map on a credential.
LANDSD_IMAGERY_TILES = "https://mapapi.geodata.gov.hk/gs/api/v1.0.0/xyz/imagery/wgs84/{z}/{x}/{y}.png"
LANDSD_BASEMAP_TILES = "https://mapapi.geodata.gov.hk/gs/api/v1.0.0/xyz/basemap/wgs84/{z}/{x}/{y}.png"
LANDSD_LABEL_TILES = "https://mapapi.geodata.gov.hk/gs/api/v1.0.0/xyz/label/hk/en/wgs84/{z}/{x}/{y}.png"
LANDSD_ATTRIBUTION = "© Map information from Lands Department, HKSAR Government"


def provider_config() -> dict:
    """What the Site map may use right now. Tile URLs are env-overridable so a moved endpoint is a
    config fix, not a code change."""
    google_key = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    return {
        "basemap": {
            "provider": "landsd",
            "imagery_tiles": os.getenv("LANDSD_IMAGERY_TILES", LANDSD_IMAGERY_TILES),
            "basemap_tiles": os.getenv("LANDSD_BASEMAP_TILES", LANDSD_BASEMAP_TILES),
            "label_tiles": os.getenv("LANDSD_LABEL_TILES", LANDSD_LABEL_TILES),
            "attribution": LANDSD_ATTRIBUTION,
            "requires_key": False,
        },
        # Key-dependent evidence, lit only when a key exists. The card's copy for the absent
        # state lives with the card; this only states the fact.
        "google": {
            "key_present": bool(google_key),
            "static_maps": bool(google_key),
            "street_view": bool(google_key),
            "distance_matrix": bool(google_key),
        },
    }
