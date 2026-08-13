"""The road distance: the judgement is a person's click, the number is arithmetic.

The access board's road-distance evidence was a deliberate stub whose keyed branch said "Pick the
road access point on the map and this measures to it." This is that picker. The split of labour
is the design's own: WHERE the site is entered from is a judgement (a named click, like a station
class's decided_by); HOW FAR each hole is from it is flat-earth metres over WGS84 — no model, no
key, no network, identical in DEMO.

What must not move: `proposed_class` stays permanently empty (the distance is evidence beside a
decision, never a classification), the no-key-no-point message keeps saying "a judgement, not a
lookup", and a point outside Hong Kong is refused by name — a mistyped coordinate would put every
distance on the tender quietly wrong.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    from api import app

    return TestClient(app)


def _seed_schedule(client):
    stations = [
        {"station": f"CE19-ABH{i:02d}", "easting": 826_000.0 + i * 20, "northing": 839_000.0,
         "soil_m": 30.0, "rock_m": 0.0, "length_m": 30.0,
         "standpipe": False, "piezometer": False}
        for i in range(6)
    ]
    schedule = {"set_id": SET, "source_sheet": "60740338/GI/210",
                "stations": stations, "trial_pits": []}
    assert client.post(f"{BASE}/site/schedule",
                       json={"set_id": SET, "schedule": schedule, "confirm": False},
                       headers={"X-CBOQ-Actor": "SW"}).status_code == 200


def _wgs(easting, northing):
    from client_boq.boq.hk1980 import to_wgs84

    return to_wgs84(easting, northing)


def _pick(client, *, easting=826_000.0, northing=839_000.0, label="Track head", point_id=""):
    lat, lon = _wgs(easting, northing)
    return client.post(f"{BASE}/site/road-point", headers={"X-CBOQ-Actor": "SW"},
                       json={"set_id": SET, "point_id": point_id, "label": label,
                             "lat": lat, "lon": lon})


class TestThePick:
    def test_a_click_persists_with_a_name_on_it(self, client):
        _seed_schedule(client)
        saved = _pick(client).json()
        assert saved["point_id"] == "road-1" and saved["picked_by"] == "SW"
        body = client.get(f"{BASE}/site/{SET}/road").json()
        assert len(body["points"]) == 1
        assert body["points"][0]["label"] == "Track head"

    def test_a_point_outside_hong_kong_is_refused_by_name(self, client):
        _seed_schedule(client)
        response = client.post(f"{BASE}/site/road-point", headers={"X-CBOQ-Actor": "SW"},
                               json={"set_id": SET, "label": "typo", "lat": 0.0, "lon": 0.0})
        assert response.status_code == 422
        assert "not in Hong Kong" in response.json()["detail"]
        assert "nothing was saved" in response.json()["detail"]

    def test_ids_are_assigned_without_overwriting(self, client):
        _seed_schedule(client)
        assert _pick(client).json()["point_id"] == "road-1"
        assert _pick(client, label="Gate").json()["point_id"] == "road-2"


class TestTheArithmetic:
    def test_a_station_a_kilometre_from_the_gate_measures_a_kilometre(self, client):
        _seed_schedule(client)
        _pick(client, easting=825_000.0, northing=839_000.0)  # 1,000 m west of ABH00
        body = client.get(f"{BASE}/site/{SET}/road").json()
        assert body["waiting_on"] == ""
        assert body["station_m"]["CE19-ABH00"] == pytest.approx(1_000.0, abs=6.0)
        assert body["station_m"]["CE19-ABH05"] == pytest.approx(1_100.0, abs=6.0)

    def test_the_nearest_of_several_points_wins(self, client):
        _seed_schedule(client)
        _pick(client, easting=825_000.0, northing=839_000.0, label="Far gate")
        _pick(client, easting=826_000.0, northing=839_050.0, label="Near gate")
        body = client.get(f"{BASE}/site/{SET}/road").json()
        assert body["station_m"]["CE19-ABH00"] == pytest.approx(50.0, abs=3.0)

    def test_no_point_is_a_named_wait_not_a_zero(self, client):
        _seed_schedule(client)
        body = client.get(f"{BASE}/site/{SET}/road").json()
        assert body["station_m"] == {}
        assert "no road-access point is picked yet" in body["waiting_on"]

    def test_no_schedule_is_the_usual_wait(self, client):
        body = client.get(f"{BASE}/site/{SET}/road").json()
        assert "has not been read yet" in body["waiting_on"]


class TestTheEvidenceLights:
    def _road_evidence(self, client):
        board = client.get(f"{BASE}/site/{SET}/access").json()
        return next(e for e in board["clusters"][0]["evidence"] if e["kind"] == "road_distance")

    def test_a_picked_point_makes_the_straight_line_available_with_no_key(self, client):
        _seed_schedule(client)
        dark = self._road_evidence(client)
        assert dark["available"] is False, "nothing picked — the stub's honesty is preserved"

        _pick(client, easting=825_500.0, northing=839_000.0)
        lit = self._road_evidence(client)
        assert lit["available"] is True
        assert "m straight line" in lit["note"]
        assert "Track head" in lit["note"]

    def test_the_distance_never_becomes_a_classification(self, client):
        _seed_schedule(client)
        _pick(client)
        board = client.get(f"{BASE}/site/{SET}/access").json()
        assert {c["proposed_class"] for c in board["clusters"]} == {""}


class TestDeletion:
    def test_removing_the_point_darkens_the_evidence_again(self, client):
        _seed_schedule(client)
        _pick(client)
        assert client.delete(f"{BASE}/site/{SET}/road-point/road-1").status_code == 200
        body = client.get(f"{BASE}/site/{SET}/road").json()
        assert body["station_m"] == {} and "no road-access point" in body["waiting_on"]

    def test_removing_what_was_never_picked_is_a_404(self, client):
        _seed_schedule(client)
        assert client.delete(f"{BASE}/site/{SET}/road-point/road-9").status_code == 404
