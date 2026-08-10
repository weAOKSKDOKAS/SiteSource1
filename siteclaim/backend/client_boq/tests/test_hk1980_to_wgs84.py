"""HK1980 Grid → WGS84, verified against its own anchors — no pyproj, no network.

Four independent anchors, because a coordinate transform that is wrong by a constant looks right
on every relative check:

1. **The projection origin inverts exactly.** (FE, FN) must give back EPSG:2326's own latitude and
   longitude of origin — analytic, no series error to hide behind.
2. **Round-trip.** forward(inverse(E, N)) returns the grid coordinate to sub-millimetre.
3. **Two published sources agree.** The EPSG:1825 translation this module carries and the Survey &
   Mapping Office's independent rule of thumb (*WGS84 ≈ HK80 lat −5.5″, lon +8.8″*) must land
   within ~1″ of each other. If either constant set were misremembered, they would not.
4. **Scale.** 1,000 m on the grid is 1,000 m on the ground to within 0.5%.
"""

import math

import pytest

from client_boq.boq import hk1980 as hk
from client_boq.boq.schedule import Station, StationSchedule


# -- the anchors -------------------------------------------------------------------------------
def test_the_projection_origin_inverts_exactly():
    lat, lon = hk.grid_to_hk80(hk.FALSE_EASTING, hk.FALSE_NORTHING)
    assert lat == pytest.approx(22.0 + 18.0 / 60.0 + 43.68 / 3600.0, abs=1e-9)
    assert lon == pytest.approx(114.0 + 10.0 / 60.0 + 42.80 / 3600.0, abs=1e-9)


@pytest.mark.parametrize("easting,northing", [
    (836694.05, 819069.80),          # the origin
    (824000.0, 836500.0),            # NW New Territories (the reference site's corner of HK)
    (816000.0, 815000.0),            # west
    (842000.0, 812000.0),            # Kowloon-ish
])
def test_the_grid_round_trips_to_sub_millimetre(easting, northing):
    lat, lon = hk.grid_to_hk80(easting, northing)
    e2, n2 = hk.hk80_to_grid(lat, lon)
    assert e2 == pytest.approx(easting, abs=1e-3)
    assert n2 == pytest.approx(northing, abs=1e-3)


def test_the_two_published_sources_agree_on_the_datum_shift():
    """EPSG:1825 (carried here) against the SMO rule of thumb (−5.5″, +8.8″) — independent
    publications of the same physical shift. Tolerance ±1.2″ (~35 m), the rule of thumb's own
    territory-wide slack; total shift ≈ 300 m either way."""
    wlat, wlon = hk.hk80_to_wgs84(22.32, 114.17)
    dlat_arcsec = (wlat - 22.32) * 3600.0
    dlon_arcsec = (wlon - 114.17) * 3600.0

    assert dlat_arcsec == pytest.approx(-5.5, abs=1.2)
    assert dlon_arcsec == pytest.approx(+8.8, abs=1.2)


def test_a_kilometre_on_the_grid_is_a_kilometre_on_the_ground():
    lat_a, lon_a = hk.to_wgs84(824000.0, 836500.0)
    lat_b, lon_b = hk.to_wgs84(825000.0, 836500.0)
    radius = 6371000.0
    dlat = math.radians(lat_b - lat_a)
    dlon = math.radians(lon_b - lon_a)
    d = 2 * radius * math.asin(math.sqrt(
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat_a)) * math.cos(math.radians(lat_b)) * math.sin(dlon / 2) ** 2))
    assert d == pytest.approx(1000.0, rel=0.005)


def test_hong_kong_grid_coordinates_land_in_hong_kong():
    for easting, northing in ((824000, 836500), (836694, 819070), (845000, 810000)):
        lat, lon = hk.to_wgs84(easting, northing)
        assert hk.in_hong_kong(lat, lon), (easting, northing, lat, lon)


# -- the schedule surface ----------------------------------------------------------------------------
def _schedule(*stations) -> StationSchedule:
    return StationSchedule(stations=list(stations))


def test_positions_convert_every_located_station():
    placed, problems = hk.positions(_schedule(
        Station(station="BH-01", easting=824000.0, northing=836500.0, soil_m=30.0, rock_m=5.0,
                total_m=35.0),
        Station(station="BH-02", easting=824100.0, northing=836400.0, soil_m=20.0, rock_m=0.0,
                total_m=20.0),
    ))
    assert [p.station for p in placed] == ["BH-01", "BH-02"]
    assert problems == []
    assert all(p.in_hong_kong for p in placed)
    assert placed[0].maps_url.startswith("https://www.google.com/maps/search/?api=1&query=22.")


def test_a_station_without_coordinates_is_named_not_dropped():
    placed, problems = hk.positions(_schedule(
        Station(station="BH-03", soil_m=10.0, rock_m=0.0, total_m=10.0)))
    assert placed == []
    assert problems == ["BH-03: no coordinates on the schedule"]


def test_a_coordinate_that_converts_outside_hong_kong_is_refused_and_named():
    """A wrong point plotted confidently on satellite imagery is exactly the picture somebody
    trusts — so it never reaches the map."""
    placed, problems = hk.positions(_schedule(
        Station(station="BH-04", easting=99999.0, northing=99999.0, soil_m=1.0, rock_m=0.0,
                total_m=1.0)))
    assert placed == []
    assert len(problems) == 1 and "outside Hong Kong" in problems[0]
    assert "BH-04" in problems[0]


# -- the provider seam -------------------------------------------------------------------------------
def test_the_landsd_basemap_is_on_with_no_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    config = hk.provider_config()
    assert config["basemap"]["requires_key"] is False
    assert "geodata.gov.hk" in config["basemap"]["imagery_tiles"]
    assert config["google"]["key_present"] is False
    assert config["google"]["street_view"] is False


def test_a_google_key_lights_the_key_dependent_calls(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "k-123")
    config = hk.provider_config()
    assert config["google"]["key_present"] is True
    assert config["google"]["static_maps"] and config["google"]["distance_matrix"]


def test_tile_urls_are_env_overridable(monkeypatch):
    monkeypatch.setenv("LANDSD_IMAGERY_TILES", "https://mirror.example/{z}/{x}/{y}.png")
    assert hk.provider_config()["basemap"]["imagery_tiles"].startswith("https://mirror.example/")


# -- the endpoint ------------------------------------------------------------------------------------
def test_the_positions_endpoint_serves_the_map(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    client = TestClient(app)
    body = client.get("/client-boq/site/never-read/positions").json()
    assert body["positions"] == [] and "waiting_on" in body
    assert body["providers"]["basemap"]["provider"] == "landsd"
