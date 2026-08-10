"""The access board: it assembles evidence, and it never proposes an access class.

The class is worth real money — the bill prices 80 Class A rig moves against 11 Class B, and a
Class B platform lands on the rig-move item — and NO DOCUMENT IN THE TENDER SAYS WHICH HOLE IS
WHICH. So a machine that answered would be guessing at something a person signs their name to, and
the guess would be believed. `proposed_class` exists on the type and is permanently empty; that is
the subject of the first class of tests here.

The second is the credential rule: an absent Google key makes ONE KIND of evidence dark and says so
by name, and never blocks the map, the clusters or the cards. A present key never leaves the
server — every keyed link is a path back into this API.
"""

import pytest
from fastapi.testclient import TestClient

from api import app
from client_boq.boq import access
from client_boq.boq.schedule import Station, StationSchedule

BASE = "/client-boq"
SET = "access-board-test"

# Two clusters ~2 km apart, plus a station with no coordinates. Fanling-ish eastings/northings so
# the conversion lands inside Hong Kong and the points are not refused.
NEAR = [
    Station(station="BH01", easting=832000.0, northing=838000.0, soil_m=20.0, rock_m=5.0,
            length_m=25.0, sheet="S1"),
    Station(station="BH02", easting=832100.0, northing=838050.0, soil_m=30.0, rock_m=10.0,
            length_m=40.0, sheet="S1"),
]
FAR = [
    Station(station="BH20", easting=834500.0, northing=840500.0, soil_m=15.0, rock_m=25.0,
            length_m=40.0, sheet="S2"),
]
NOWHERE = [Station(station="BH99", soil_m=10.0, rock_m=0.0, length_m=10.0)]


def _schedule(*groups) -> StationSchedule:
    return StationSchedule(stations=[s for group in groups for s in group])


@pytest.fixture()
def client():
    return TestClient(app)


class TestItNeverConcludes:
    def test_no_cluster_carries_a_proposed_class(self):
        board = access.board(_schedule(NEAR, FAR), set_id=SET)
        assert board.clusters, "there is something to have an opinion about"
        assert {c.proposed_class for c in board.clusters} == {""}

    def test_the_field_survives_serialisation_so_the_absence_is_visible(self):
        """A field that vanishes from the payload cannot state a policy. It stays, and it stays
        empty — the same shape as `DepartureProposal` having no status field at all."""
        dumped = access.board(_schedule(NEAR), set_id=SET).model_dump()
        assert dumped["clusters"][0]["proposed_class"] == ""

    def test_an_unclassed_cluster_says_a_human_decides_rather_than_guessing(self):
        board = access.board(_schedule(NEAR), set_id=SET, classes={})
        note = " ".join(board.clusters[0].notes)
        assert "no access class yet" in note
        assert "guessing" in note

    def test_it_reads_the_classes_people_have_already_set_and_writes_none(self):
        board = access.board(_schedule(NEAR, FAR), set_id=SET,
                             classes={"BH01": "A", "BH02": "B"})
        first = next(c for c in board.clusters if "BH01" in c.stations)
        assert first.decided["A"] == 1 and first.decided["B"] == 1
        assert first.decided[""] == 0
        assert first.proposed_class == ""


class TestItAssembles:
    def test_stations_within_the_radius_are_one_cluster_and_distant_ones_are_not(self):
        board = access.board(_schedule(NEAR, FAR), set_id=SET, radius_m=250.0)
        sizes = sorted(c.holes for c in board.clusters)
        assert sizes == [1, 2]

    def test_a_cluster_carries_its_centroid_its_spread_and_its_metres(self):
        cluster = access.board(_schedule(NEAR), set_id=SET).clusters[0]
        assert 22.0 < cluster.lat < 22.7 and 113.8 < cluster.lon < 114.5
        assert cluster.soil_m == 50.0 and cluster.rock_m == 15.0
        assert cluster.deepest_m == 40.0
        assert 0 < cluster.spread_m < 200, "the two holes are about 110 m apart"

    def test_a_station_with_no_coordinates_is_named_not_placed(self):
        """A pin invented at the centre of the others would be a lie with a marker on it."""
        board = access.board(_schedule(NEAR, NOWHERE), set_id=SET)
        assert board.unlocated == ["BH99"]
        assert all("BH99" not in c.stations for c in board.clusters)
        assert board.problems and "BH99" in board.problems[0]

    def test_a_chained_cluster_says_it_may_be_a_ridge_rather_than_a_place(self):
        """Single-link clustering chains: A near B near C can put A and C 2 km apart in one group.
        The card says so rather than presenting a ridge as one location."""
        chain = [
            Station(station=f"BH{n:02d}", easting=832000.0 + n * 200, northing=838000.0,
                    soil_m=10.0, rock_m=0.0, length_m=10.0)
            for n in range(12)
        ]
        cluster = access.board(StationSchedule(stations=chain), set_id=SET,
                               radius_m=250.0).clusters[0]
        assert cluster.holes == 12
        assert cluster.spread_m > 250.0
        assert any("ridge rather than a place" in n for n in cluster.notes)


class TestTheCredentialRule:
    def test_without_a_key_three_kinds_are_dark_and_three_are_not(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
        cluster = access.board(_schedule(NEAR), set_id=SET).clusters[0]
        by_kind = {e.kind: e for e in cluster.evidence}

        assert by_kind[access.EVIDENCE_IMAGERY].available, "keyless Lands Department tiles"
        assert by_kind[access.EVIDENCE_MAP].available and by_kind[access.EVIDENCE_MAP].external
        for kind in (access.EVIDENCE_SATELLITE, access.EVIDENCE_STREET_VIEW):
            assert not by_kind[kind].available
            assert "Google Maps key" in by_kind[kind].unavailable_reason
            assert "nothing else is affected" in by_kind[kind].unavailable_reason
            assert by_kind[kind].url == "", "no URL at all, rather than a broken one"

    def test_with_a_key_the_still_links_point_back_into_this_api(self, monkeypatch):
        """The key stays on the server. A URL with a credential in it, handed to a page, is a
        published credential whatever the referrer policy says."""
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-not-real")
        cluster = access.board(_schedule(NEAR), set_id=SET).clusters[0]
        by_kind = {e.kind: e for e in cluster.evidence}

        for kind in (access.EVIDENCE_SATELLITE, access.EVIDENCE_STREET_VIEW):
            assert by_kind[kind].available
            assert by_kind[kind].url.startswith(f"/client-boq/site/{SET}/access/still")
            assert not by_kind[kind].external
            assert "test-key-not-real" not in by_kind[kind].url

    def test_the_drawing_crop_says_what_it_is_waiting_for(self):
        cluster = access.board(_schedule(NEAR), set_id=SET, located_sheets=set()).clusters[0]
        drawing = next(e for e in cluster.evidence if e.kind == access.EVIDENCE_DRAWING)
        assert not drawing.available
        assert "grid marks" in drawing.unavailable_reason

        located = access.board(_schedule(NEAR), set_id=SET, located_sheets={"S1"}).clusters[0]
        assert next(e for e in located.evidence
                    if e.kind == access.EVIDENCE_DRAWING).available

    def test_road_distance_is_honest_that_it_needs_a_destination_somebody_picks(self):
        cluster = access.board(_schedule(NEAR), set_id=SET).clusters[0]
        road = next(e for e in cluster.evidence if e.kind == access.EVIDENCE_ROAD_DISTANCE)
        assert not road.available
        assert "judgement, not a lookup" in road.unavailable_reason

    def test_the_evidence_is_in_the_declared_order_on_every_cluster(self):
        for cluster in access.board(_schedule(NEAR, FAR), set_id=SET).clusters:
            kinds = [e.kind for e in cluster.evidence]
            assert kinds == [k for k in access.EVIDENCE_ORDER if k in kinds]
            assert set(kinds) == set(access.EVIDENCE_ORDER), "every kind is stated, dark or not"


class TestOverHttp:
    def test_a_set_with_no_schedule_says_what_it_is_waiting_for(self, client):
        body = client.get(f"{BASE}/site/nothing-here-yet/access").json()
        assert body["clusters"] == []
        assert "schedule has not been read" in body["waiting_on"]
        assert body["providers"]["basemap"]["requires_key"] is False

    def test_the_still_proxy_refuses_without_a_key_and_names_the_missing_thing(
        self, client, monkeypatch,
    ):
        monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
        reply = client.get(f"{BASE}/site/{SET}/access/still?lat=22.5&lon=114.1")
        assert reply.status_code == 503
        assert "GOOGLE_MAPS_API_KEY" in reply.json()["detail"]
        assert "unaffected" in reply.json()["detail"]

    def test_the_still_proxy_refuses_a_point_outside_hong_kong(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-not-real")
        reply = client.get(f"{BASE}/site/{SET}/access/still?lat=51.5&lon=-0.12")
        assert reply.status_code == 400
        assert "outside Hong Kong" in reply.json()["detail"]

    def test_the_still_proxy_refuses_an_unknown_kind(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key-not-real")
        reply = client.get(f"{BASE}/site/{SET}/access/still?lat=22.5&lon=114.1&kind=whatever")
        assert reply.status_code == 400

    def test_both_routes_are_registered(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert f"{BASE}/site/{{set_id}}/access" in paths
        assert f"{BASE}/site/{{set_id}}/access/still" in paths
