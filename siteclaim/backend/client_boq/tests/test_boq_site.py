"""The Site HTTP surface: the take-off, the class of every hole, and the groups.

The rule these defend: **the client's own bill is the check on the estimator's judgement, and the
app's job is to put the two side by side rather than to decide between them.**

Three places that shows up:

* **The schedule** reconciles row by row — a hole whose length is not its soil plus its rock has been
  misread, and it is named rather than repaired.
* **The derived quantities** are compared against the bill, and a divergence is reported as loudly as
  a match. On the reference contract GI/100's Table 1 says 52 permeability tests and the bill says
  54; nobody reading either document alone would notice.
* **The class counts** are the only external check there is on which holes are Class A. The client
  bills 80 and 11 and never says which, so the estimator's counts coming back to 80 and 11 is the
  whole of the verification.

There is no gate here on purpose. Site warns; the sweep is what blocks.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _station(name, soil, rock, *, e=826_000.0, n=839_000.0, standpipe=False, piezometer=False,
             length=None):
    return {"station": name, "easting": e, "northing": n, "soil_m": soil, "rock_m": rock,
            "length_m": soil + rock if length is None else length,
            "standpipe": standpipe, "piezometer": piezometer}


def _schedule(stations=None, pits=3):
    return {
        "set_id": SET, "source_sheet": "60740338/GI/210",
        "stations": stations if stations is not None else [
            _station(f"CE19-ABH{i:02d}", 30.0, 0.0, e=826_000.0 + i * 20,
                     standpipe=i < 3, piezometer=i < 4)
            for i in range(6)
        ],
        "trial_pits": [{"station": f"CE19-NTP{i:02d}", "depth_m": 3.0} for i in range(1, pits + 1)],
    }


def _save(client, schedule=None, confirm=False):
    body = {"set_id": SET, "schedule": schedule or _schedule(), "confirm": confirm}
    response = client.post(f"{BASE}/site/schedule", json=body, headers={"X-CBOQ-Actor": "SW"})
    assert response.status_code == 200, response.text
    return response.json()


class TestTheSchedule:
    def test_a_set_with_no_take_off_says_what_it_is_waiting_for(self, client):
        body = client.get(f"{BASE}/site/{SET}/schedule").json()
        assert body["stations"] == []
        assert "has not been read yet" in body["waiting_on"]

    def test_a_saved_schedule_comes_back_with_the_sums_the_bill_is_checked_against(self, client):
        _save(client)
        body = client.get(f"{BASE}/site/{SET}/schedule").json()
        assert body["totals"]["holes"] == 6 and body["totals"]["soil_m"] == 180.0
        assert body["totals"]["standpipes"] == 3 and body["totals"]["piezometers"] == 4
        # The identity behind the real bill: every standpipe and every piezometer gets one device.
        assert body["totals"]["instruments"] == 7

    def test_a_row_that_does_not_add_up_is_named_and_blocks_nothing_else(self, client):
        broken = _schedule([_station("CE19-ABH99", 20.0, 5.0, length=40.0)])
        saved = _save(client, broken)
        assert not saved["usable"]
        assert "CE19-ABH99" in saved["bad_rows"][0]
        # It is still readable — a misread row is a thing to fix on screen, not a locked door.
        assert client.get(f"{BASE}/site/{SET}/schedule").json()["stations"]

    def test_saving_leaves_it_unconfirmed_until_somebody_says_otherwise(self, client):
        assert _save(client)["meta"]["confirmed_by"] == ""

    def test_confirming_puts_a_name_on_it(self, client):
        assert _save(client, confirm=True)["meta"]["confirmed_by"] == "SW"

    def test_a_re_read_lands_unconfirmed_again(self, client):
        # The thing somebody checked is no longer the thing on the screen. Same rule the register
        # applies when an addendum rewrites a clause that had already been ruled on.
        _save(client, confirm=True)
        assert _save(client)["meta"]["confirmed_by"] == ""


class TestClassingAHole:
    def test_a_class_is_recorded_against_a_name(self, client):
        _save(client)
        body = client.post(f"{BASE}/site/class",
                           json={"set_id": SET, "station": "CE19-ABH00", "access_class": "A"},
                           headers={"X-CBOQ-Actor": "SW"}).json()
        assert body["decided_by"] == "SW" and body["counts"] == {"A": 1}
        assert client.get(f"{BASE}/site/{SET}/schedule").json()["classes"]["CE19-ABH00"][
            "access_class"] == "A"

    def test_class_c_says_it_has_nowhere_to_be_priced(self, client):
        _save(client)
        body = client.post(f"{BASE}/site/class",
                           json={"set_id": SET, "station": "CE19-ABH00", "access_class": "C"}).json()
        assert "helicopter" in body["note"] and "sweep" in body["note"]
        assert "priced at nothing" in body["note"]

    def test_a_class_the_specification_does_not_have_is_refused(self, client):
        _save(client)
        response = client.post(f"{BASE}/site/class",
                               json={"set_id": SET, "station": "CE19-ABH00", "access_class": "Z"})
        assert response.status_code == 422
        assert "PS 7.01B" in response.json()["detail"]

    def test_a_class_can_be_taken_back(self, client):
        _save(client)
        client.post(f"{BASE}/site/class",
                    json={"set_id": SET, "station": "CE19-ABH00", "access_class": "A"})
        body = client.post(f"{BASE}/site/class",
                           json={"set_id": SET, "station": "CE19-ABH00", "access_class": ""}).json()
        assert body["counts"] == {}


class TestGroups:
    def _group(self, label="Roadside", stations=("CE19-ABH00", "CE19-ABH01"), **extra):
        return {"label": label, "stations": list(stations), **extra}

    def test_a_group_takes_its_measured_facts_from_the_schedule(self, client):
        _save(client)
        body = client.post(f"{BASE}/site/group",
                           json={"set_id": SET, "group_id": "g1", "group": self._group()}).json()
        assert body["group"]["soil_m"] == 60.0, "summarised from the two stations, not typed"

    def test_a_group_says_what_it_still_needs(self, client):
        _save(client)
        body = client.post(f"{BASE}/site/group",
                           json={"set_id": SET, "group_id": "g1", "group": self._group()}).json()
        assert "access class" in body["ready"]

    def test_a_groups_class_follows_the_holes_in_it(self, client):
        # Classing a hole and grouping it are one act on the screen; the group should not ask again.
        _save(client)
        client.post(f"{BASE}/site/group",
                    json={"set_id": SET, "group_id": "g1", "group": self._group()})
        for station in ("CE19-ABH00", "CE19-ABH01"):
            client.post(f"{BASE}/site/class",
                        json={"set_id": SET, "station": station, "access_class": "A"})
        body = client.get(f"{BASE}/site/{SET}/groups").json()
        assert body["groups"][0]["access_class"] == "A"

    def test_outputs_are_inherited_from_the_library_and_marked_book(self, client):
        _save(client)
        client.post(f"{BASE}/site/group",
                    json={"set_id": SET, "group_id": "g1", "group": self._group()})
        body = client.get(f"{BASE}/site/{SET}/groups").json()
        assert body["groups"][0]["soil_output"] == 20.0
        assert body["sources"]["Roadside"]["soil_output"]["source"] == "book"

    def test_an_override_is_marked_yours_and_still_shows_the_books_number(self, client):
        _save(client)
        client.post(f"{BASE}/site/group", json={
            "set_id": SET, "group_id": "g1",
            "group": self._group(soil_output=9.0, overrides=["soil_output"])})
        source = client.get(f"{BASE}/site/{SET}/groups").json()["sources"]["Roadside"]["soil_output"]
        assert source["source"] == "yours" and source["value"] == 9.0
        assert source["book_value"] == 20.0

    def test_deleting_a_group_keeps_the_classes_its_holes_were_given(self, client):
        _save(client)
        client.post(f"{BASE}/site/group",
                    json={"set_id": SET, "group_id": "g1", "group": self._group()})
        client.post(f"{BASE}/site/class",
                    json={"set_id": SET, "station": "CE19-ABH00", "access_class": "A"})
        body = client.delete(f"{BASE}/site/{SET}/group/g1").json()
        assert body["deleted"] and "keep the class" in body["note"]
        classes = client.get(f"{BASE}/site/{SET}/schedule").json()["classes"]
        assert classes["CE19-ABH00"]["access_class"] == "A"
        assert classes["CE19-ABH00"]["group_id"] == ""

    def test_unassigned_holes_are_reported_before_anything_else(self, client):
        _save(client)
        client.post(f"{BASE}/site/group",
                    json={"set_id": SET, "group_id": "g1", "group": self._group()})
        body = client.get(f"{BASE}/site/{SET}/groups").json()
        assert body["unassigned"] == 2
        assert "no access class yet" in body["reconcile"][0]


class TestThePreviewUnderTheGroupsScreen:
    """One implementation of the day simulation, reached over HTTP — not a second one in TypeScript."""

    def _ready_group(self):
        return {"label": "Hillside", "stations": ["CE19-ABH00", "CE19-ABH01"],
                "access_class": "B", "rigs": 1}

    def test_a_group_that_is_not_ready_says_what_it_is_waiting_for_rather_than_guessing(self, client):
        _save(client)
        body = client.post(f"{BASE}/site/preview",
                           json={"set_id": SET, "group": {"label": "x", "stations": []}}).json()
        assert body["ready"] is False and "access class" in body["waiting_on"]

    def test_a_ready_group_comes_back_with_days_and_a_blend_but_no_money(self, client):
        _save(client)
        body = client.post(f"{BASE}/site/preview",
                           json={"set_id": SET, "group": self._ready_group()}).json()
        assert body["ready"] is True
        assert body["soil_m"] == 60.0 and body["drilling_days"] >= 3
        assert body["blended_m_per_day"] > 0
        assert "rate" not in body, "the rate needs the whole bill; this screen never prices"

    def test_by_default_the_blend_is_the_output_typed_because_nothing_decays(self, client):
        # RE-ANCHORED IN THE OPEN. This used to assert the blend came back BELOW the typed output,
        # because the default decay was 5% per 20 m. The data ruled that to zero — over 205 real
        # drilling-days the 20-40 m band is 20% faster, not slower — so with no decay asked for,
        # 60 m of soil at 20 m/day IS three days and the blend IS 20. Depth-independence is the
        # claim now, and it is asserted rather than assumed.
        _save(client)
        body = client.post(f"{BASE}/site/preview",
                           json={"set_id": SET, "group": self._ready_group()}).json()
        assert body["blended_m_per_day"] == 20.0

    def test_a_deliberate_decay_still_slows_the_blend_so_the_simulation_is_running(self, client):
        # The mechanism the old test pinned, kept: ask for decay and the blend drops. If these were
        # equal the simulation would not be running and this screen would be a division.
        _save(client)
        padded = {**self._ready_group(), "decay": 0.05, "overrides": ["decay"]}
        body = client.post(f"{BASE}/site/preview",
                           json={"set_id": SET, "group": padded}).json()
        assert body["blended_m_per_day"] < 20.0

    def test_the_preview_carries_the_band_the_rock_fraction_selects(self, client):
        # The production driver reaching the group path. Before this the group's speed came from
        # two flat norms and a depth curve, and its rock fraction changed nothing.
        _save(client)
        body = client.post(f"{BASE}/site/preview",
                           json={"set_id": SET, "group": self._ready_group()}).json()
        band = body["band"]
        assert band["rock_fraction"] >= 0.0
        assert band["band_label"] or band["problems"], "a band, or a stated reason there is none"
        if band["band_label"]:
            assert band["band_rate"] > 0 and band["expected_work_days"] > 0
            assert band["divergence"] is not None

    def test_more_rigs_shorten_the_programme(self, client):
        _save(client)
        one = client.post(f"{BASE}/site/preview",
                          json={"set_id": SET, "group": self._ready_group()}).json()
        two = client.post(f"{BASE}/site/preview",
                          json={"set_id": SET, "group": {**self._ready_group(), "rigs": 2}}).json()
        assert two["drilling_days"] < one["drilling_days"]

    def test_the_preview_says_where_each_output_came_from(self, client):
        _save(client)
        body = client.post(f"{BASE}/site/preview",
                           json={"set_id": SET, "group": self._ready_group()}).json()
        assert body["sources"]["soil_output"]["source"] == "book"


class TestGeoref:
    def test_a_sheet_with_no_grid_marks_says_exactly_what_it_needs(self, client):
        _save(client)
        body = client.get(f"{BASE}/site/{SET}/georef", params={"sheet": "GI/201"}).json()
        assert "two printed grid marks" in body["waiting_on"]
        assert "needs two grid marks" in body["problems"][0]

    def test_it_names_the_stations_it_could_place_once_the_marks_are_in(self, client):
        _save(client)
        body = client.get(f"{BASE}/site/{SET}/georef", params={"sheet": "GI/201"}).json()
        assert len(body["stations"]) == 6

    def test_georef_without_a_take_off_is_a_404_that_says_which_drawing(self, client):
        response = client.get(f"{BASE}/site/{SET}/georef", params={"sheet": "GI/201"})
        assert response.status_code == 404 and "GI/210" in response.json()["detail"]


class TestDerivedQuantities:
    def test_the_drawings_rules_produce_quantities_and_each_names_its_rule(self, client):
        _save(client)
        body = client.get(f"{BASE}/site/{SET}/derived").json()
        assert body["checked_against_a_bill"] is False
        assert body["derived"], "the general-notes rules alone already produce quantities"
        assert all(d["rule"] and d["source"] for d in body["derived"])

    def test_nothing_is_claimed_as_agreed_when_there_is_no_bill_to_check_against(self, client):
        _save(client)
        body = client.get(f"{BASE}/site/{SET}/derived").json()
        assert body["divergences"] == [] and body["confirmations"] == []
        assert len(body["unchecked"]) == len(body["derived"])

    def test_standing_time_recovers_the_five_hours_a_hole_the_real_bill_implies(self, client):
        _save(client)
        body = client.get(f"{BASE}/site/{SET}/derived").json()
        standing = next(d for d in body["derived"] if d["label"].startswith("Standing time"))
        assert standing["value"] == 30.0        # 6 holes × 5.0 h
        assert "455" in standing["source"]
