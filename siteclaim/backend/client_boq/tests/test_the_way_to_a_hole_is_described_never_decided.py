"""A route note beside a hole: the engine measures, the model describes, the person still decides.

WHY THE NOTE IS WORTH HAVING. The map already shows a hole and the nearest mapped road, and the
gap between those two facts is where the money is — forty metres from a track is a two-minute walk
or a cliff. An estimator classing ninety-nine holes does that reasoning ninety-nine times from the
same evidence, which is exactly the work worth drafting.

WHY IT IS ALSO THE MOST DANGEROUS TEXT IN THE APP. A route description written from a road network
and a coordinate reads like local knowledge. It is not. It cannot see a locked gate, a collapsed
track, a stream with no crossing, or whose land it crosses — and those are precisely the facts that
decide the access class and therefore the rate.

So the split is enforced in the TYPES, not in the prompt:

* ``RawApproach`` has no field for a distance, a duration, a cost or an access class. A stage with
  nowhere to write a verdict cannot write one, and no later edit to a prompt can start collecting
  one — the same structural guard `DepartureProposal` and `RawConditionMapping` carry.
* every metre on the response is the engine's measurement, attached after the call, so a model
  writing "about 300 m" in its prose cannot contradict the number on screen.
* a road the model names that is not in the data it was given is REFUSED by name, because an
  invented road is the single most believable wrong answer this call can produce.
* an empty uncertainty list is replaced rather than printed. A model that returns nothing there
  has not become certain, and blank would read as "nothing to worry about".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.boq import approach as boq_approach
from client_boq.boq.roads import NearestRoad, roads_near

BASE = "/client-boq"
SET = "technopole-gi"


def _road(name: str, metres: float, way_id: int = 1, highway: str = "track") -> NearestRoad:
    return NearestRoad(station="BH1", metres=metres, way_id=way_id, name=name, highway=highway)


class TestTheModelHasNowhereToPutAVerdict:
    def test_it_cannot_name_a_class_a_cost_or_a_distance(self):
        """Structural. A prompt can be edited; a missing field cannot be filled."""
        fields = set(boq_approach.RawApproach.model_fields)
        assert fields == {"summary", "approach_road", "last_stretch", "steps", "uncertainties"}
        for forbidden in ("access_class", "class", "metres", "distance_m", "cost", "days",
                          "transport", "confidence"):
            assert forbidden not in fields

    def test_the_prompt_forbids_a_number_in_any_field(self):
        assert "NEVER give a distance, a duration, a cost, or an access class" in \
            boq_approach.SYSTEM
        assert "Never write as if the class" in boq_approach.SYSTEM

    def test_the_measured_figures_are_the_engines_and_arrive_after(self):
        roads = [_road("Castle Peak Road", 41.0, way_id=7), _road("", 180.0, way_id=9)]
        context = boq_approach.context_for("BH1", roads)
        note = boq_approach.validate(
            boq_approach.RawApproach(summary="x", uncertainties=["y"]), "BH1", context)
        assert note.nearest_road_m == pytest.approx(41.0)
        assert note.nearest_road_way_id == 7
        assert len(note.roads_considered) == 2


class TestAnInventedRoadIsRefusedByName:
    def test_a_road_not_in_the_data_is_stripped_and_reported(self):
        context = boq_approach.context_for("BH1", [_road("Fan Kam Road", 60.0)])
        note = boq_approach.validate(
            boq_approach.RawApproach(approach_road="Lok Ma Chau Loop Access Road",
                                     uncertainties=["gradient unknown"]),
            "BH1", context)
        assert note.approach_road == ""
        assert any("REFUSED" in line and "Lok Ma Chau" in line for line in note.checked)

    def test_a_road_that_was_measured_survives(self):
        context = boq_approach.context_for("BH1", [_road("Fan Kam Road", 60.0)])
        note = boq_approach.validate(
            boq_approach.RawApproach(approach_road="Fan Kam Road", uncertainties=["gate?"]),
            "BH1", context)
        assert note.approach_road == "Fan Kam Road"
        assert note.checked == []

    def test_naming_it_by_osm_id_also_survives(self):
        context = boq_approach.context_for("BH1", [_road("", 60.0, way_id=41552217)])
        note = boq_approach.validate(
            boq_approach.RawApproach(approach_road="OSM way 41552217", uncertainties=["gate?"]),
            "BH1", context)
        assert note.approach_road == "OSM way 41552217"


class TestSilenceAboutRiskIsNotConfidence:
    def test_an_empty_uncertainty_list_is_replaced_not_printed(self):
        note = boq_approach.validate(
            boq_approach.RawApproach(summary="drive up"), "BH1", [])
        assert len(note.uncertainties) == 1
        assert "straight-line distance is not a walk" in note.uncertainties[0]
        assert any("SUPPLIED" in line for line in note.checked)

    def test_real_uncertainties_are_kept_verbatim(self):
        note = boq_approach.validate(
            boq_approach.RawApproach(uncertainties=["  the track may be gated  ", "", "slope"]),
            "BH1", [])
        assert note.uncertainties == ["the track may be gated", "slope"]
        assert note.checked == []


class TestTheRoadContextIsMeasuredAndBounded:
    def test_roads_near_returns_one_row_per_way_nearest_first(self):
        ways = [
            {"id": 1, "tags": {"highway": "track", "name": "Far track"},
             "geometry": [{"lat": 22.500, "lon": 114.100}, {"lat": 22.501, "lon": 114.100}]},
            {"id": 2, "tags": {"highway": "residential", "name": "Near road"},
             "geometry": [{"lat": 22.4901, "lon": 114.080}, {"lat": 22.4901, "lon": 114.081}]},
        ]
        rows = roads_near("BH1", (22.4900, 114.0805), ways)
        assert [r.way_id for r in rows] == [2, 1], "nearest first"
        assert len({r.way_id for r in rows}) == 2, "one row per way, not per segment"

    def test_context_drops_what_is_out_of_reach(self):
        roads = [_road("near", 50.0, 1), _road("far", 5_000.0, 2)]
        assert [r.way_id for r in boq_approach.context_for("BH1", roads)] == [1]

    def test_context_is_capped_so_the_prompt_stays_readable(self):
        roads = [_road(f"r{i}", float(i), i) for i in range(1, 40)]
        assert len(boq_approach.context_for("BH1", roads)) == boq_approach.CONTEXT_ROADS

    def test_the_prompt_carries_only_measured_roads(self):
        text = boq_approach.prompt_for("BH1", boq_approach.context_for(
            "BH1", [_road("Fan Kam Road", 61.4, 7, "unclassified")]))
        assert "Fan Kam Road" in text and "OSM way 7" in text and "61.4 m" in text

    def test_no_roads_says_so_rather_than_looking_like_an_empty_list(self):
        assert "no mapped road within reach" in boq_approach.prompt_for("BH1", [])


class TestTheEndpoint:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch) -> TestClient:
        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
        from api import app
        return TestClient(app)

    @pytest.fixture
    def scheduled(self, client):
        client.post(f"{BASE}/site/schedule", json={"set_id": SET, "schedule": {"stations": [
            {"station": "BH1", "easting": 828100.0, "northing": 838200.0, "soil_m": 20.0},
            {"station": "BH2", "soil_m": 30.0},
        ]}})

    def test_demo_says_no_distance_below_was_measured(self, client, scheduled):
        """DEMO is offline by rule, so the prose comes from the fixture and the MEASUREMENTS do
        not — and the response must not let the two read as one thing."""
        body = client.get(f"{BASE}/site/{SET}/approach/BH1").json()
        assert body["summary"], "the drafted prose is still shown"
        assert "demo mode is offline" in body["waiting_on"]
        assert "no distance below has been measured" in body["waiting_on"]
        assert body["nearest_road_m"] is None

    def test_demo_also_refuses_the_fixtures_own_road_name(self, client, scheduled):
        """A pleasing accident that is worth pinning: with no road data measured, the fixture's
        road is not in the evidence either, and the same guard strips it. The guard does not
        know it is in demo mode — it only knows what was measured."""
        body = client.get(f"{BASE}/site/{SET}/approach/BH1").json()
        assert body["approach_road"] == ""
        assert any("REFUSED" in line for line in body["checked"])

    def test_a_hole_with_no_coordinates_says_correct_them_first(self, client, scheduled):
        body = client.get(f"{BASE}/site/{SET}/approach/BH2").json()
        assert "carries no easting and northing" in body["waiting_on"]
        assert "Correct its coordinates" in body["waiting_on"]
        assert body["summary"] == "", "no route is drafted for a hole with no position"

    def test_a_hole_that_is_not_in_the_schedule_is_a_404(self, client, scheduled):
        assert client.get(f"{BASE}/site/{SET}/approach/BH999").status_code == 404

    def test_no_schedule_at_all_is_a_waiting_state_not_an_error(self, client):
        body = client.get(f"{BASE}/site/nothing-here/approach/BH1").json()
        assert "has not been read yet" in body["waiting_on"]

    def test_it_follows_a_corrected_coordinate(self, client, scheduled):
        """The note is about where the hole IS, so moving the hole must move the note's subject."""
        assert client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH2", "easting": 828500.0, "northing": 838600.0,
        }).status_code == 200
        body = client.get(f"{BASE}/site/{SET}/approach/BH2").json()
        assert "carries no easting" not in body["waiting_on"]
        assert body["summary"], "it can be described now that it has a position"
