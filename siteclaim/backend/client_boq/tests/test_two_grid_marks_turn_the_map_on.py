"""Two typed grid marks turn the map on — and stay honest about everything they cannot place.

The georef math shipped complete and inert: `SheetRegistration` was built and tested, MapCrop was
built with an honest null state, and nothing persisted a registration — so the Holes screen showed
"NO GRID MARKS ON THIS SHEET YET" on all 91 tiles and the access board's drawing evidence stayed
dark forever. These tests pin the closure: one table, a writer that names a mistyped coordinate
the moment it is typed, and a reader that assigns every located station to the sheet that
CONTAINS it — never nearest-match, never a tile of the wrong place.

The seam that made this more than plumbing: `Station.sheet` is the SCHEDULE sheet the row was
read from (GI/210), while registrations are of the SITE-PLAN sheets (GI/201…). The two name
families never intersect, so membership is computed by coordinates (`georef.sheet_for`), and the
access board takes `located_stations` — names would have lit nothing, silently.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"
SHEET = "60740338/GI/201"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    from api import app

    return TestClient(app)


def _station(name, *, e, n):
    return {"station": name, "easting": e, "northing": n, "soil_m": 30.0, "rock_m": 0.0,
            "length_m": 30.0, "standpipe": False, "piezometer": False}


def _seed(client, *, far_station=False):
    """A schedule of six holes near 826,000 E / 839,000 N, and the drawing part they live in."""
    stations = [_station(f"CE19-ABH{i:02d}", e=826_000.0 + i * 20, n=839_000.0)
                for i in range(6)]
    if far_station:
        stations.append(_station("CE19-ABH99", e=900_000.0, n=839_000.0))
    schedule = {"set_id": SET, "source_sheet": "60740338/GI/210",
                "stations": stations, "trial_pits": []}
    assert client.post(f"{BASE}/site/schedule",
                       json={"set_id": SET, "schedule": schedule, "confirm": False},
                       headers={"X-CBOQ-Actor": "SW"}).status_code == 200

    from client_boq import models, store
    part = models.PartSpec(n=9, abbr="DRG", title="Drawings", start=1, end=10,
                           category="drawings")
    conn = store.get_conn()
    try:
        store.save_parts(conn, SET, [part])
    finally:
        conn.close()
    return part.part_id


def _marks():
    """Printed grid crosses at 10% and 90% of the page — a 1,000 m sheet holding the six holes."""
    return [
        {"easting": 826_000.0, "northing": 839_050.0, "x": 0.1, "y": 0.1,
         "label": "826000E 839050N"},
        {"easting": 826_800.0, "northing": 838_250.0, "x": 0.9, "y": 0.9,
         "label": "826800E 838250N"},
    ]


def _register(client, part_id, *, marks=None, confirm=False, page=3):
    return client.post(f"{BASE}/site/registration", headers={"X-CBOQ-Actor": "SW"},
                       json={"set_id": SET, "confirm": confirm,
                             "registration": {"sheet": SHEET, "part_id": part_id,
                                              "page": page, "marks": marks or _marks()}})


class TestTheRegistrationPersists:
    def test_two_marks_place_every_hole_on_the_sheet(self, client):
        part_id = _seed(client)
        saved = _register(client, part_id).json()
        assert saved["usable"] is True and saved["problems"] == []

        body = client.get(f"{BASE}/site/{SET}/georef").json()
        assert body["waiting_on"] == ""
        assert body["unplaced"] == []
        assert len(body["crops"]) == 6
        crop = body["crops"]["CE19-ABH00"]
        assert crop["sheet"] == SHEET and crop["part_id"] == part_id and crop["page"] == 3
        box = crop["box"]
        assert 0.0 <= box["x0"] < box["x1"] <= 1.0
        assert body["sheets"][0]["stations_on"] == 6

    def test_a_mistyped_mark_is_named_and_crops_nothing(self, client):
        """Stored problems-visible, zero crops — georef refuses to approximate and the endpoint
        does not help it. The 2% isotropy check is what catches the typo."""
        part_id = _seed(client)
        bad = _marks()
        bad[1]["northing"] = 838_600.0  # down-scale now ~562 m/page vs 1,000 across
        saved = _register(client, part_id, marks=bad).json()
        assert saved["usable"] is False and saved["problems"]

        body = client.get(f"{BASE}/site/{SET}/georef").json()
        assert body["crops"] == {}
        assert body["sheets"][0]["problems"]
        assert "two printed grid marks" in body["waiting_on"], (
            "a stored-but-broken registration is not a usable one")

    def test_a_station_off_every_registered_sheet_stays_named(self, client):
        part_id = _seed(client, far_station=True)
        _register(client, part_id)
        body = client.get(f"{BASE}/site/{SET}/georef").json()
        assert body["unplaced"] == ["CE19-ABH99"], "never a tile of the wrong place"
        assert "CE19-ABH99" not in body["crops"]


class TestConfirmIsAnActWithANameOnIt:
    def test_confirm_records_who_and_an_edit_clears_it(self, client):
        part_id = _seed(client)
        assert _register(client, part_id, confirm=True).json()["confirmed_by"] == "SW"
        assert client.get(f"{BASE}/site/{SET}/georef").json()["sheets"][0]["confirmed_by"] == "SW"

        _register(client, part_id, confirm=False)  # an edited mark re-saves unconfirmed
        assert client.get(f"{BASE}/site/{SET}/georef").json()["sheets"][0]["confirmed_by"] == ""

    def test_confirming_a_broken_registration_is_refused_not_absorbed(self, client):
        part_id = _seed(client)
        bad = _marks()
        bad[1]["easting"] = 826_000.0  # both marks on one grid line — no scale to read
        saved = _register(client, part_id, marks=bad, confirm=True).json()
        assert saved["problems"] and saved["confirmed_by"] == ""


class TestTheWriterValidatesWhereTheSheetLives:
    def test_an_unknown_part_is_a_404_naming_it(self, client):
        _seed(client)
        response = _register(client, "99-nope")
        assert response.status_code == 404 and "99-nope" in response.json()["detail"]

    def test_a_page_outside_the_part_is_refused_with_the_bounds(self, client):
        part_id = _seed(client)
        response = _register(client, part_id, page=99)
        assert response.status_code == 422
        assert "1–10" in response.json()["detail"]


class TestTheAccessBoardLightsByCoordinates:
    def test_the_drawing_evidence_goes_from_dark_to_available(self, client):
        part_id = _seed(client)

        def drawing_evidence():
            board = client.get(f"{BASE}/site/{SET}/access").json()
            cluster = board["clusters"][0]
            return next(e for e in cluster["evidence"] if e["kind"] == "drawing")

        before = drawing_evidence()
        assert before["available"] is False
        assert "no grid marks" in before["unavailable_reason"]

        _register(client, part_id)
        after = drawing_evidence()
        assert after["available"] is True, (
            "membership is by coordinates — the schedule sheet (GI/210) and the registered "
            "site-plan sheet (GI/201) never share a name")


class TestDeletion:
    def test_deleting_a_registration_darkens_the_map_again(self, client):
        part_id = _seed(client)
        _register(client, part_id)
        from urllib.parse import quote
        assert client.delete(
            f"{BASE}/site/{SET}/registration?sheet={quote(SHEET, safe='')}").status_code == 200
        assert client.get(f"{BASE}/site/{SET}/georef").json()["crops"] == {}

    def test_deleting_what_was_never_registered_is_a_404(self, client):
        _seed(client)
        assert client.delete(f"{BASE}/site/{SET}/registration?sheet=GI/999").status_code == 404
