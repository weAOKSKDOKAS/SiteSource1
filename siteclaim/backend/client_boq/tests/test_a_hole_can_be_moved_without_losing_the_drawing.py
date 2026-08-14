"""Correcting where a hole is, without ever losing what the drawing said.

WHY A PERSON HAS TO BE ABLE TO MOVE ONE. A setting-out drawing mixes surveyed positions with
indicative ones and does not mark which is which. Forty metres is nothing on an A1 sheet and
everything on a hillside — a different approach road, possibly a different class of site, possibly
a platform that is or is not needed. Nothing in the tender resolves it, so it is the estimator's
judgement exactly as the class is, and it carries his name.

ONE DOOR, SO THE SCREENS CANNOT DISAGREE. The correction is applied inside
``store.load_station_schedule``, which the map, the proximity clusters, the road distances and the
georeferenced drawing crop all already come through. A correction that reached some of them and not
others would leave the app holding two positions for one hole, which is a worse failure than the
wrong coordinate it was meant to fix.

AND THE ROUND TRIP THAT WOULD HAVE QUIETLY EATEN THE DRAWING. Because the loader hands out the
CORRECTED schedule, an ordinary edit — read the schedule, retype one soil metre, save — would have
written the human's coordinate straight into the drawing's own record, and nothing would have been
left to say what the drawing said. ``save_station_schedule`` puts an unchanged correction back
before writing, so the pair is an involution. A payload carrying something DIFFERENT is a new
reading and is taken at face value, or the schedule editor could never move a hole at all.

UNDO RESTORES THE DRAWING, NOT A SECOND GUESS. Deleting the correction is the only honest undo:
anything else would be the app inventing a third coordinate.
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


@pytest.fixture
def scheduled(client):
    """Two holes as the drawing has them."""
    body = {
        "set_id": SET,
        "schedule": {"stations": [
            {"station": "BH1", "easting": 828100.0, "northing": 838200.0, "soil_m": 20.0},
            {"station": "BH2", "easting": 828300.0, "northing": 838400.0, "soil_m": 30.0},
        ]},
    }
    assert client.post(f"{BASE}/site/schedule", json=body).status_code == 200
    return body


def _stations(client) -> dict:
    return {s["station"]: s for s in client.get(f"{BASE}/site/{SET}/schedule").json()["stations"]}


def _as_payload(client) -> dict:
    """The schedule as the editor would send it back — the shape POST /site/schedule takes."""
    body = client.get(f"{BASE}/site/{SET}/schedule").json()
    return {"stations": body["stations"], "trial_pits": body["trial_pits"]}


class TestMovingAHole:
    def test_the_schedule_reads_the_corrected_position(self, client, scheduled):
        client.post(f"{BASE}/site/station/coords", headers={"X-CBOQ-Actor": "SW"}, json={
            "set_id": SET, "station": "BH1", "easting": 828140.0, "northing": 838225.0,
            "note": "scaled off GI/201"})
        assert _stations(client)["BH1"]["easting"] == pytest.approx(828140.0)
        assert _stations(client)["BH2"]["easting"] == pytest.approx(828300.0), "only that hole"

    def test_it_says_what_it_moved_from_and_how_far(self, client, scheduled):
        reply = client.post(f"{BASE}/site/station/coords", headers={"X-CBOQ-Actor": "SW"}, json={
            "set_id": SET, "station": "BH1", "easting": 828130.0, "northing": 838200.0}).json()
        assert reply["corrected"] is True and reply["by"] == "SW"
        assert reply["was_easting"] == pytest.approx(828100.0)
        assert reply["moved_m"] == pytest.approx(30.0)

    def test_the_map_pin_follows(self, client, scheduled):
        """The whole reason to make it editable: the point on the map has to move with it."""
        before = {p["station"]: p for p in client.get(f"{BASE}/site/{SET}/positions").json()["positions"]}
        client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "easting": 829100.0, "northing": 839200.0})
        after = {p["station"]: p for p in client.get(f"{BASE}/site/{SET}/positions").json()["positions"]}
        assert after["BH1"]["lat"] != pytest.approx(before["BH1"]["lat"])
        assert after["BH1"]["lon"] != pytest.approx(before["BH1"]["lon"])
        assert after["BH2"]["lat"] == pytest.approx(before["BH2"]["lat"])

    def test_a_second_correction_still_remembers_the_drawing(self, client, scheduled):
        """`was` is the DRAWING's, not the previous correction's — otherwise two edits lose it."""
        client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "easting": 828150.0, "northing": 838250.0})
        second = client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "easting": 828160.0, "northing": 838260.0}).json()
        assert second["was_easting"] == pytest.approx(828100.0)
        assert second["was_northing"] == pytest.approx(838200.0)


class TestTheDrawingSurvives:
    def test_a_round_trip_save_does_not_eat_it(self, client, scheduled):
        """Read the corrected schedule, change something else, save it back — the drawing's own
        coordinate must still be there afterwards."""
        client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "easting": 828140.0, "northing": 838225.0})
        current = _as_payload(client)
        current["stations"][0]["soil_m"] = 22.0            # an ordinary edit to something else
        assert client.post(f"{BASE}/site/schedule",
                           json={"set_id": SET, "schedule": current}).status_code == 200

        restored = client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "restore": True}).json()
        assert restored["easting"] == pytest.approx(828100.0), "the drawing, not the correction"
        assert _stations(client)["BH1"]["soil_m"] == pytest.approx(22.0), "the real edit stuck"

    def test_a_different_coordinate_in_the_payload_is_taken_at_face_value(self, client, scheduled):
        """Or the schedule editor could never move a hole — only the coords endpoint could."""
        client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "easting": 828140.0, "northing": 838225.0})
        current = _as_payload(client)
        current["stations"][0]["easting"] = 827000.0       # a NEW reading, not the standing one
        client.post(f"{BASE}/site/schedule", json={"set_id": SET, "schedule": current})

        back = client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "restore": True}).json()
        assert back["easting"] == pytest.approx(827000.0)


class TestUndo:
    def test_restoring_brings_back_the_drawing(self, client, scheduled):
        client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "easting": 828900.0, "northing": 838900.0})
        reply = client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH1", "restore": True}).json()
        assert reply["restored"] is True and reply["corrected"] is False
        assert reply["easting"] == pytest.approx(828100.0)
        assert _stations(client)["BH1"]["easting"] == pytest.approx(828100.0)

    def test_restoring_a_hole_nobody_moved_says_so_rather_than_pretending(self, client, scheduled):
        reply = client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH2", "restore": True}).json()
        assert reply["restored"] is False
        assert "had not been moved" in reply["note"]


class TestItRefusesRatherThanGuessing:
    def test_a_hole_that_is_not_in_the_schedule_is_a_404(self, client, scheduled):
        reply = client.post(f"{BASE}/site/station/coords", json={
            "set_id": SET, "station": "BH999", "easting": 1.0, "northing": 2.0})
        assert reply.status_code == 404
        assert "Nothing was written" in reply.json()["detail"]

    def test_no_schedule_at_all_says_read_the_drawing_first(self, client):
        reply = client.post(f"{BASE}/site/station/coords", json={
            "set_id": "nothing-here", "station": "BH1", "easting": 1.0, "northing": 2.0})
        assert reply.status_code == 404
        assert "read the borehole details drawing first" in reply.json()["detail"].lower()
