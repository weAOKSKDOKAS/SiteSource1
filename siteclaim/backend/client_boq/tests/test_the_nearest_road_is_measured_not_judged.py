"""The nearest MAPPED road: arithmetic anybody can check, and never a class of site.

The distinction this file exists to hold. "How far is this hole from the nearest road anybody has
mapped" is a MEASUREMENT — geometry and a coordinate, same answer for two people. "Which class of
site is this hole" is a JUDGEMENT worth real money (80 Class A moves against 11 Class B, and a
Class B platform on the rig-move item), and a hole forty metres from a road it cannot be reached
from is an ordinary thing on a hillside. So the measurement is evidence beside the decision and
the decision stays a person's: `proposed_class` is still permanently empty afterwards.

The arithmetic is pinned exactly because it is separable — `nearest_roads` takes geometry and
returns distances with no network in it, which is what lets a road measurement be asserted to the
metre rather than approximately.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.boq import roads

BASE = "/client-boq"
SET = "technopole-gi"

#: One straight east-west road at latitude 22.4900, spanning the site. Two nodes,
#: which is the case that matters: measuring to the nearest NODE would report a hole beside its
#: midpoint as hundreds of metres away.
ROAD = {
    "type": "way", "id": 42,
    "tags": {"highway": "track", "name": "Kam Pok Track"},
    "geometry": [{"lat": 22.4900, "lon": 114.0700}, {"lat": 22.4900, "lon": 114.0900}],
}


class TestTheArithmetic:
    def test_the_distance_is_perpendicular_to_the_segment_not_to_a_node(self):
        """A hole beside the MIDDLE of a long straight road is metres away, not hundreds."""
        # 22.4900 → 22.4891 is ~100 m of latitude; the hole sits mid-span.
        holes = {"MID": (22.4891, 114.0800)}
        reading = roads.nearest_roads(holes, [ROAD])
        assert len(reading.nearest) == 1
        near = reading.nearest[0]
        assert near.metres == pytest.approx(100.0, abs=3.0)
        assert near.way_id == 42 and near.name == "Kam Pok Track"
        # And the point returned is ON the road, level with the hole.
        assert near.lat == pytest.approx(22.4900, abs=1e-4)
        assert near.lon == pytest.approx(114.0800, abs=1e-4)

    def test_past_the_end_of_a_road_measures_to_its_end_not_beyond_it(self):
        """The projection is clamped: a hole off the end of a segment is measured to the end."""
        holes = {"EAST": (22.4900, 114.0950)}          # ~515 m east of the road's end
        near = roads.nearest_roads(holes, [ROAD]).nearest[0]
        assert near.metres == pytest.approx(515.0, abs=15.0)
        assert near.lon == pytest.approx(114.0900, abs=1e-4), "clamped to the eastern node"

    def test_the_nearest_of_several_roads_wins(self):
        far = {**ROAD, "id": 7, "tags": {"highway": "primary", "name": "Far Road"},
               "geometry": [{"lat": 22.4800, "lon": 114.0700},
                            {"lat": 22.4800, "lon": 114.0900}]}
        near = roads.nearest_roads({"MID": (22.4891, 114.0800)}, [far, ROAD]).nearest[0]
        assert near.way_id == 42 and near.name == "Kam Pok Track"

    def test_a_hole_no_road_reaches_is_named_not_dropped(self):
        reading = roads.nearest_roads({"NOWHERE": (22.4891, 114.0800)}, [])
        assert reading.nearest == []
        assert reading.unreached == ["NOWHERE"]
        assert "no mapped road" in reading.problems[0]

    def test_every_hole_gets_an_answer_or_a_name(self):
        holes = {f"H{i}": (22.4891, 114.0700 + i * 0.001) for i in range(20)}
        reading = roads.nearest_roads(holes, [ROAD])
        assert len(reading.nearest) + len(reading.unreached) == 20


class TestTheQueryIsOneCallAndReadable:
    def test_the_bounding_box_pads_the_site(self):
        box = roads.bbox_for([(22.4900, 114.0800), (22.4910, 114.0810)])
        assert box is not None
        south, west, north, east = box
        assert south < 22.4900 and north > 22.4910
        assert west < 114.0800 and east > 114.0810

    def test_no_points_is_no_box_rather_than_the_whole_world(self):
        assert roads.bbox_for([]) is None

    def test_the_query_asks_for_geometry_in_one_go(self):
        """`out geom` returns each way's shape inline — one response carries everything needed,
        with no second round trip to resolve node ids, and no per-hole query at all."""
        query = roads.overpass_query((22.48, 114.07, 22.50, 114.09))
        assert "out geom" in query
        assert query.count("way[") == 1, "one bounding-box query for the whole site"
        assert "track" in query and "primary" in query


class TestItMeasuresAndDoesNotConclude:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch) -> TestClient:
        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
        from api import app

        return TestClient(app)

    def _seed(self, client):
        stations = [{"station": f"CE19-ABH{i:02d}", "easting": 826_000.0 + i * 20,
                     "northing": 839_000.0, "soil_m": 30.0, "rock_m": 0.0, "length_m": 30.0,
                     "standpipe": False, "piezometer": False} for i in range(4)]
        assert client.post(f"{BASE}/site/schedule", headers={"X-CBOQ-Actor": "SW"},
                           json={"set_id": SET, "confirm": False,
                                 "schedule": {"set_id": SET, "source_sheet": "GI/210",
                                              "stations": stations, "trial_pits": []}}
                           ).status_code == 200

    def test_demo_says_it_did_not_run_rather_than_replaying_a_fixture(self, client):
        """Overpass is a live call and DEMO is offline by rule. A fixture here would read as a
        measurement of the tender in front of you, which is the one thing it would not be."""
        self._seed(client)
        body = client.get(f"{BASE}/site/{SET}/roads").json()
        assert body["nearest"] == []
        assert "demo mode is offline" in body["waiting_on"]
        assert "live" in body["waiting_on"]

    def test_no_schedule_is_the_usual_named_wait(self, client):
        body = client.get(f"{BASE}/site/{SET}/roads").json()
        assert "has not been read yet" in body["waiting_on"]

    def test_measuring_never_writes_a_class(self, client):
        self._seed(client)
        client.get(f"{BASE}/site/{SET}/roads")
        board = client.get(f"{BASE}/site/{SET}/access").json()
        assert {c["proposed_class"] for c in board["clusters"]} == {""}, (
            "a distance is evidence beside the decision, never the decision")
