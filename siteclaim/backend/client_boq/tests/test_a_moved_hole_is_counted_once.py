"""A hole moved between groups is counted exactly once — and keeps its class.

Membership authority is the group's OWN station list (`group_json`); the per-station `group_id`
on `client_boq_station_classes` is a secondary link. Saving a group re-linked its members but
never un-linked a station that LEFT — so after a move (or an ungroup) the old link survived, and
anything trusting it would double-count the hole. The save now clears links that point at the
saved group from stations no longer in it. The class is untouched throughout: classifying a hole
and deciding which spread works it are two different acts.
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


def _save_group(client, group_id: str, label: str, stations: list[str]):
    return client.post(f"{BASE}/site/group", headers={"X-CBOQ-Actor": "SW"},
                       json={"set_id": SET, "group_id": group_id,
                             "group": {"label": label, "stations": stations}})


def _links(client=None):
    from client_boq import store

    conn = store.get_conn()
    try:
        return {name: dict(row) for name, row in store.load_station_classes(conn, SET).items()}
    finally:
        conn.close()


class TestTheStaleLinkIsCleared:
    def test_a_station_that_leaves_a_group_stops_pointing_at_it(self, client):
        assert _save_group(client, "hillside", "Hillside", ["S1", "S2"]).status_code == 200
        assert _links()["S2"]["group_id"] == "hillside"

        assert _save_group(client, "hillside", "Hillside", ["S1"]).status_code == 200
        links = _links()
        assert links["S1"]["group_id"] == "hillside"
        assert links["S2"]["group_id"] == "", "the departed hole no longer points at the group"

    def test_the_departed_hole_keeps_its_class(self, client):
        _save_group(client, "hillside", "Hillside", ["S1", "S2"])
        assert client.post(f"{BASE}/site/class", headers={"X-CBOQ-Actor": "SW"},
                           json={"set_id": SET, "station": "S2",
                                 "access_class": "B"}).status_code == 200
        _save_group(client, "hillside", "Hillside", ["S1"])
        row = _links()["S2"]
        assert row["access_class"] == "B" and row["group_id"] == ""

    def test_a_move_lands_the_hole_in_exactly_one_group(self, client):
        """The UI's two-write move, end to end: source loses it, target gains it, and the
        per-station link follows the target."""
        _save_group(client, "hillside", "Hillside", ["S1", "S2"])
        _save_group(client, "roadside", "Roadside", ["S3"])

        _save_group(client, "hillside", "Hillside", ["S1"])
        _save_group(client, "roadside", "Roadside", ["S3", "S2"])

        assert _links()["S2"]["group_id"] == "roadside"

    def test_another_groups_link_is_never_touched(self, client):
        """The clear targets ONLY stations pointing at the saved group — saving Hillside must
        not un-link Roadside's members."""
        _save_group(client, "hillside", "Hillside", ["S1"])
        _save_group(client, "roadside", "Roadside", ["S3"])
        _save_group(client, "hillside", "Hillside", ["S1", "S4"])
        assert _links()["S3"]["group_id"] == "roadside"
