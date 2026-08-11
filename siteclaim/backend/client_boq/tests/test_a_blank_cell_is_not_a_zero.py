"""The take-off's honesty checks — the three things arithmetic could not see.

`bad_rows()` was the only check on a station schedule, and it is the narrowest one. It needs a
`length_m` to check against, and a row that fails it is at least a row somebody READ.

Three failures slipped underneath it, and every one of them is the shape a MACHINE reader produces:

* **A cell nobody could read.** `soil_m`, `rock_m` and `hard_above_rockhead_m` are plain floats
  defaulting to `0.0`, so a blank arrives as the same value as a printed `0.00`. And `rock_m == 0`
  is ordinary — a soil-only hole — so nothing downstream can infer "zero means unread".
* **A row that measures nothing.** `Station(station="CE19-ABH42")` is `soil 0 + rock 0 = 0` and
  `length_m is None`, and `reconciles()` short-circuits to `True` on exactly that. It passed every
  honesty check in the module while contributing nothing to any total.
* **A name read twice.** `index()` is keyed on the station name, so the second one silently
  overwrites the first and the schedule gets shorter than the sheet. A model transcribing 91 rows
  off a picture is precisely the thing that repeats a name.

None of the three repairs anything. Each is a sentence naming a station, which is what the rest of
this module already does with a row that fails its arithmetic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.boq import schedule as boq_schedule

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _station(name: str, **kw) -> boq_schedule.Station:
    """A hole that reads cleanly, unless the caller breaks one thing about it on purpose."""
    row = {"station": name, "easting": 834000.0, "northing": 817000.0,
           "ground_level_mpd": 30.0, "length_m": 35.0, "soil_m": 30.0, "rock_m": 5.0}
    row.update(kw)
    return boq_schedule.Station(**row)


def _schedule(*stations: boq_schedule.Station) -> boq_schedule.StationSchedule:
    return boq_schedule.StationSchedule(set_id="probe", source_sheet="60740338/GI/210",
                                        stations=list(stations))


class TestTheBaselineStillHolds:
    """Nothing here may change what a clean schedule, or a broken row, already did."""

    def test_a_clean_schedule_is_usable_and_names_nothing(self):
        clean = _schedule(_station("CE19-ABH01"), _station("CE19-ABH02"))
        assert clean.usable()
        assert clean.problems() == []
        assert clean.soil_m() == 60.0 and clean.rock_m() == 10.0

    def test_a_row_that_fails_its_own_arithmetic_is_still_the_first_thing_named(self):
        broken = _schedule(_station("CE19-ABH01"), _station("CE19-ABH99", length_m=40.0))
        assert not broken.usable()
        assert len(broken.bad_rows()) == 1
        assert "CE19-ABH99" in broken.bad_rows()[0]
        # It is a misread row, not an unread cell and not an empty one.
        assert broken.unread_rows() == [] and broken.empty_rows() == []

    def test_a_soil_only_hole_is_ordinary_and_is_never_flagged(self):
        """`rock_m == 0` is the common case, not a defect. This is the line the empty-row check
        must not cross — if it flagged every zero it would flag most of a real sheet."""
        soil_only = _schedule(_station("CE19-ABH01", length_m=30.0, soil_m=30.0, rock_m=0.0))
        assert soil_only.usable()
        assert soil_only.empty_rows() == []


class TestACellNobodyCouldRead:

    def test_an_unread_cell_is_named_in_the_estimators_words(self):
        s = _schedule(_station("CE19-ABH07", soil_m=0.0, length_m=None, unread=["soil_m"]))
        assert not s.usable()
        note = s.unread_rows()[0]
        assert "CE19-ABH07" in note
        assert "the length in soil" in note, "the field NAME is not what a person reads"
        assert "A blank is not a zero" in note

    def test_it_is_invisible_to_the_arithmetic_check_which_is_why_it_exists(self):
        """soil unread → 0.0, rock 5.0, no stated length. `reconciles()` has nothing to compare
        against and returns True. Without `unread` this row is indistinguishable from a hole that
        genuinely drills five metres of rock and no soil."""
        s = _station("CE19-ABH07", soil_m=0.0, length_m=None, unread=["soil_m"])
        assert s.reconciles() and s.discrepancy() is None
        assert s.unread_note() is not None

    def test_several_unread_cells_are_all_named_on_one_line(self):
        s = _station("CE19-ABH07", easting=None, northing=None,
                     unread=["easting", "northing"])
        note = s.unread_note() or ""
        assert "the easting" in note and "the northing" in note

    def test_a_field_name_with_no_plain_english_falls_back_to_itself(self):
        """An unknown key must still appear. Dropping it would be the silent loss the whole
        mechanism exists to prevent."""
        s = _station("CE19-ABH07", unread=["some_future_column"])
        assert "some_future_column" in (s.unread_note() or "")

    def test_a_typed_schedule_carries_no_unread_marks_and_is_unaffected(self):
        """Somebody who types a row has read every cell of it. The default must be empty, or every
        hand-entered schedule would be refused."""
        assert boq_schedule.Station().unread == []
        assert _schedule(_station("CE19-ABH01")).unread_rows() == []


class TestARowThatMeasuresNothing:

    def test_a_station_that_is_only_a_name_passes_every_arithmetic_check(self):
        """The exact defect. Kept as its own assertion because it is the reason the check exists,
        and if `reconciles` ever starts catching it this test should be the one that says so."""
        bare = boq_schedule.Station(station="CE19-ABH42")
        assert bare.reconciles(), "length_m is None short-circuits to True"
        assert bare.discrepancy() is None
        assert bare.total_m == 0.0
        assert bare.measures_nothing()

    def test_it_is_named_and_the_schedule_refuses(self):
        s = _schedule(_station("CE19-ABH01"), boq_schedule.Station(station="CE19-ABH42"))
        assert not s.usable()
        assert len(s.empty_rows()) == 1
        assert "CE19-ABH42" in s.empty_rows()[0]
        assert "adds nothing to either total" in s.empty_rows()[0]

    def test_the_totals_confirm_it_contributed_nothing(self):
        """The row is invisible to `soil_m()`/`rock_m()` — which is why nothing else would notice
        that the schedule is one hole short of the sheet."""
        one = _schedule(_station("CE19-ABH01"))
        two = _schedule(_station("CE19-ABH01"), boq_schedule.Station(station="CE19-ABH42"))
        assert one.soil_m() == two.soil_m() and one.rock_m() == two.rock_m()
        assert two.hole_count() == 2, "it still counts as a hole, and that is the second problem"

    def test_a_row_whose_metres_are_marked_unread_is_not_named_twice(self):
        """`unread_rows` has already said it, and more precisely. Two sentences about one row is
        how a screen stops being read."""
        s = _schedule(_station("CE19-ABH07", soil_m=0.0, rock_m=0.0, length_m=None,
                               unread=["soil_m", "rock_m"]))
        assert s.empty_rows() == []
        assert len(s.unread_rows()) == 1
        assert not s.usable(), "still refused — just refused once"

    def test_a_row_unread_somewhere_else_still_gets_its_empty_note(self):
        """The easting being unread accounts for nothing about the missing metres."""
        s = _schedule(_station("CE19-ABH07", soil_m=0.0, rock_m=0.0, length_m=None,
                               easting=None, unread=["easting"]))
        assert len(s.empty_rows()) == 1
        assert len(s.unread_rows()) == 1

    def test_a_row_stating_zero_length_explicitly_is_also_caught(self):
        """`length_m=0` with soil 0 and rock 0 satisfies the arithmetic perfectly — 0 + 0 = 0 —
        so the arithmetic check waves it through."""
        zero = _station("CE19-ABH42", length_m=0.0, soil_m=0.0, rock_m=0.0)
        assert zero.reconciles() and zero.discrepancy() is None
        assert zero.measures_nothing()


class TestANameReadTwice:

    def test_the_index_silently_drops_the_first_of_a_pair(self):
        """Established first, because the check is only worth having if this is true."""
        s = _schedule(_station("CE19-ABH01", soil_m=30.0),
                      _station("CE19-ABH01", soil_m=25.0))
        assert len(s.stations) == 2
        assert len(s.index()) == 1, "keyed on the name — the second overwrites the first"
        assert s.index()["CE19-ABH01"].soil_m == 25.0

    def test_the_duplicate_is_named_and_the_schedule_refuses(self):
        s = _schedule(_station("CE19-ABH01"), _station("CE19-ABH02"), _station("CE19-ABH01"))
        assert not s.usable()
        assert len(s.duplicate_names()) == 1
        note = s.duplicate_names()[0]
        assert "CE19-ABH01" in note and "appears 2 times" in note
        assert "only the last one survives" in note

    def test_distinct_names_are_never_flagged(self):
        s = _schedule(_station("CE19-ABH01"), _station("CE19-ABH02"), _station("CE19-ABH03"))
        assert s.duplicate_names() == [] and s.usable()

    def test_three_of_the_same_name_report_the_real_count(self):
        s = _schedule(*[_station("CE19-ABH01") for _ in range(3)])
        assert "appears 3 times" in s.duplicate_names()[0]


class TestItReportsAndNeverRepairs:
    """Same rule as everywhere else in this module: name it, never fix it, never drop it."""

    def test_no_check_mutates_the_schedule(self):
        s = _schedule(_station("CE19-ABH01", soil_m=0.0, unread=["soil_m"]),
                      boq_schedule.Station(station="CE19-ABH42"),
                      _station("CE19-ABH01"))
        before = s.model_dump()
        s.problems(); s.usable(); s.bad_rows(); s.unread_rows()
        s.empty_rows(); s.duplicate_names()
        assert s.model_dump() == before

    def test_problems_carries_every_check_at_once(self):
        """One list, so a screen can print the whole story without knowing the check names."""
        s = _schedule(_station("CE19-ABH01", length_m=99.0),               # bad arithmetic
                      _station("CE19-ABH02", soil_m=0.0, unread=["soil_m"]),  # unread cell
                      boq_schedule.Station(station="CE19-ABH42"),          # measures nothing
                      _station("CE19-ABH01"))                             # duplicate name
        problems = s.problems()
        assert len(problems) == len(s.bad_rows()) + len(s.unread_rows()) \
            + len(s.empty_rows()) + len(s.duplicate_names())
        assert len(problems) >= 4
        assert not s.usable()

    def test_an_empty_schedule_is_not_usable_and_complains_about_nothing(self):
        """There is no row to name, so there is no sentence to write. The absence is the message,
        and the screen already has its own words for it."""
        empty = boq_schedule.StationSchedule(set_id="probe")
        assert not empty.usable()
        assert empty.problems() == []


class TestTheHttpSurfaceCarriesThem:

    def test_the_get_names_all_four_checks(self, client):
        body = _post_and_get(client, SET, [
            {"station": "CE19-ABH01", "length_m": 35.0, "soil_m": 30.0, "rock_m": 5.0},
            {"station": "CE19-ABH02", "soil_m": 0.0, "rock_m": 5.0, "unread": ["soil_m"]},
            {"station": "CE19-ABH03"},
            {"station": "CE19-ABH01", "length_m": 35.0, "soil_m": 30.0, "rock_m": 5.0},
        ])
        assert body["unread_rows"] and "the length in soil" in body["unread_rows"][0]
        assert body["empty_rows"] and "CE19-ABH03" in body["empty_rows"][0]
        assert body["duplicate_names"] and "CE19-ABH01" in body["duplicate_names"][0]
        assert body["usable"] is False
        assert len(body["problems"]) >= 3

    def test_a_set_with_no_schedule_still_answers_with_every_key(self, client):
        """The empty payload and the full one must have the same shape, or a screen reading
        `problems` has to special-case the state it is most likely to be in."""
        body = client.get(f"{BASE}/site/no-such-set-at-all/schedule").json()
        for key in ("bad_rows", "unread_rows", "empty_rows", "duplicate_names", "problems"):
            assert body[key] == []
        assert body["usable"] is False

    def test_the_post_answers_with_the_same_checks_it_will_answer_the_get_with(self, client):
        """A save that comes back clean and a re-read that comes back broken would be the worst
        possible pair, so the writer reports exactly what the reader will."""
        rows = [{"station": "CE19-ABH01", "soil_m": 0.0, "unread": ["soil_m", "rock_m"]}]
        saved = client.post(f"{BASE}/site/schedule", json={
            "set_id": SET, "schedule": {"set_id": SET, "stations": rows},
            "source_sheet": "60740338/GI/210"}).json()
        got = client.get(f"{BASE}/site/{SET}/schedule").json()
        for key in ("bad_rows", "unread_rows", "empty_rows", "duplicate_names", "problems"):
            assert saved[key] == got[key]
        assert saved["usable"] == got["usable"] is False


def _post_and_get(client, set_id: str, rows: list) -> dict:
    saved = client.post(f"{BASE}/site/schedule", json={
        "set_id": set_id, "schedule": {"set_id": set_id, "stations": rows},
        "source_sheet": "60740338/GI/210"})
    assert saved.status_code == 200, saved.text
    return client.get(f"{BASE}/site/{set_id}/schedule").json()
