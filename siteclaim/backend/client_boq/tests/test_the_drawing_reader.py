"""Reading the take-off off the drawing — the half that was blocked on an artefact.

MEASURED ON THE REAL PACK, which is what unblocked it:

* The schedule sheets are flattened raster — A3 landscape, 48 images, **28 characters of text**
  (the title-block stamp). Zero station names appear in the text layer of any drawing.
* The one exception is the drawing REGISTER, `GI-COVER`, which carries 2,582 characters of real
  text listing every drawing against its title. **So the triage is free** — no thumbnails, no
  batched vision call to find the sheet, no metadata heuristics.
* At the API's own downscale ceiling the table is legible cell by cell, so **one call reads one
  sheet**. The row-band slicing that would have made this ten times more expensive is not needed.
* **There are TWO schedule sheets.** `GI/210` carries the engineering boreholes and a trial-pit
  table; `GI/310` carries the environmental holes, which are billed under Bills 3 and 5. A reader
  that finds the first and stops under-reads the tender, and every check downstream agrees with it,
  because they all measure what was read against what was read.
* **And the two sheets do not carry the same columns.** GI/310 is station, easting, northing and a
  TERMINATION REQUIREMENT written as a sentence — no ground level, no rockhead, and no soil/rock
  split at all. Pushing both through one shape produces environmental stations at `soil_m = 0.0`,
  indistinguishable from holes that genuinely drill nothing.
"""

from __future__ import annotations

import pytest

from client_boq.ingest import schedule_read as reader
from client_boq.ingest import schedule_sheets as sheets

#: The register, in the shape its text layer comes out in.
REGISTER = """
DRAWING REGISTER
60740338/GI/000   WORKING AREA OF GROUND INVESTIGATION SHEET 1
60740338/GI/020   WORKING AREA OF GROUND INVESTIGATION - COORDINATE
60740338/GI/021   WORKING AREA OF GROUND INVESTIGATION - COORDINATE
60740338/GI/100   GENERAL NOTES AND DETAILS
60740338/GI/200   PROPOSED SITE INVESTIGATION PLAN SHEET 1
60740338/GI/210   PROPOSED SITE INVESTIGATION - COORDINATE
60740338/GI/300   PROPOSED SITE INVESTIGATION PLAN (ENVIRONMENTAL) SHEET 1
60740338/GI/310   PROPOSED SITE INVESTIGATION PLAN (ENVIRONMENTAL) - COORDINATE
"""

FILES = [
    "DRG__60740338-GI-COVER.pdf", "DRG__60740338-GI-000.pdf", "DRG__60740338-GI-020.pdf",
    "DRG__60740338-GI-021.pdf", "DRG__60740338-GI-100.pdf", "DRG__60740338-GI-200.pdf",
    "DRG__60740338-GI-210.pdf", "DRG__60740338-GI-300.pdf", "DRG__60740338-GI-310.pdf",
]


class TestTheTriageIsFree:

    def test_it_finds_both_schedule_sheets(self):
        """The one that matters. Bills 3 and 5 are the environmental-borehole bills, so stopping
        at GI/210 is a take-off short by every hole on GI/310."""
        plan = sheets.plan(REGISTER, FILES)
        assert [s.number for s in plan.sheets] == ["GI/210", "GI/310"]
        assert plan.tier == sheets.TIER_REGISTER

    def test_it_keeps_which_sheet_is_which(self):
        plan = sheets.plan(REGISTER, FILES)
        kinds = {s.number: s.kind() for s in plan.sheets}
        assert kinds == {"GI/210": sheets.KIND_ENGINEERING, "GI/310": sheets.KIND_ENVIRONMENTAL}

    def test_the_working_area_sheets_are_excluded_and_named(self):
        """They end in the same word — "- COORDINATE" — and they are the site boundary, not the
        holes. Excluding them silently would be a rule nobody could see."""
        plan = sheets.plan(REGISTER, FILES)
        assert not any(s.number in {"GI/020", "GI/021"} for s in plan.sheets)
        assert len(plan.excluded) == 2
        assert all("WORKING AREA" in note for note in plan.excluded)

    def test_a_layout_plan_is_not_a_schedule(self):
        """GI/200 and GI/300 draw the same stations on a map. They carry no table."""
        plan = sheets.plan(REGISTER, FILES)
        assert not any(s.number in {"GI/200", "GI/300"} for s in plan.sheets)

    def test_each_sheet_is_matched_to_its_file(self):
        plan = sheets.plan(REGISTER, FILES)
        assert {s.number: s.filename for s in plan.sheets} == {
            "GI/210": "DRG__60740338-GI-210.pdf", "GI/310": "DRG__60740338-GI-310.pdf"}

    def test_the_headline_says_how_it_decided_and_what_it_passed_over(self):
        headline = sheets.plan(REGISTER, FILES).headline()
        assert "2 station-schedule sheet(s)" in headline
        assert "no sheet was opened to decide this and no model was asked" in headline
        assert "passed over" in headline

    def test_a_register_that_lists_a_drawing_twice_lists_one_drawing(self):
        doubled = REGISTER + "\n60740338/GI/210   PROPOSED SITE INVESTIGATION - COORDINATE"
        assert len(sheets.plan(doubled, FILES).sheets) == 2


class TestItDegradesRatherThanFails:

    def test_no_register_falls_back_to_the_filenames_and_says_it_is_weaker(self):
        plan = sheets.plan("", FILES)
        assert plan.tier == sheets.TIER_FILENAME
        assert "no drawing register in this pack" in plan.reason
        assert "can tell a station schedule from a working-area plan" in plan.reason

    def test_nothing_at_all_is_a_stated_nothing_not_an_empty_pack(self):
        plan = sheets.plan("", [])
        assert not plan.found()
        assert "is not a pack with no schedule in it" in plan.headline()

    def test_a_register_with_no_drawing_numbers_falls_through(self):
        plan = sheets.plan("This page intentionally blank", FILES)
        assert plan.tier == sheets.TIER_FILENAME

    def test_a_drawing_with_no_title_still_counts(self):
        """A drawing that exists and whose title could not be read is a fact. Dropping it would
        make the count wrong."""
        entries = sheets.parse_register("60740338/GI/210\n60740338/GI/310   SOMETHING")
        assert [e.number for e in entries] == ["GI/210", "GI/310"]


class TestTheColumnsMapOntoTheModel:

    @staticmethod
    def _row(**kw) -> reader.RawStation:
        base = {"station": "CE19-ABH19", "kind": "BH", "easting": 826337.69,
                "northing": 839177.88, "ground_level_mpd": 14.90, "rockhead_level_mpd": -15.00,
                "length_m": 34.90, "max_boring_m": 80.00, "soil_m": 29.90,
                "hard_above_rockhead_m": 0.0, "rock_m": 5.00, "standpipe": True,
                "piezometer": False}
        base.update(kw)
        return reader.RawStation(**base)

    def test_a_clean_row_reads_across(self):
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._row()]), set_id="t", sheet="GI/210")
        station = schedule.stations[0]
        assert station.station == "CE19-ABH19"
        assert station.easting == 826337.69 and station.northing == 839177.88
        assert station.soil_m == 29.90 and station.rock_m == 5.00
        assert station.max_boring_m == 80.00
        assert station.standpipe is True and station.piezometer is False
        assert station.unread == []

    def test_the_rows_own_arithmetic_is_the_first_check(self):
        """29.90 + 5.0 = 34.90, off the real sheet. The reader does not perform this and cannot
        influence it."""
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._row()]), set_id="t", sheet="GI/210")
        assert schedule.stations[0].reconciles()
        assert schedule.bad_rows() == []

    def test_a_misread_row_is_caught_by_its_own_stated_length(self):
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._row(soil_m=20.0)]), set_id="t", sheet="GI/210")
        assert schedule.bad_rows()

    def test_a_trial_pit_gets_its_own_three_depth_columns(self):
        """`TrialPit` already has depth_m, max_depth_m and depth_in_soil_m, which is exactly the
        printed table — so no judgement is needed and none is made."""
        pit = reader.RawStation(station="CE19-NTP01", kind="TP", easting=826100.0,
                                northing=838800.0, ground_level_mpd=11.20, depth_m=3.0,
                                max_depth_m=4.5, depth_in_soil_m=3.0)
        schedule = reader.to_schedule(
            reader.RawSchedule(trial_pits=[pit]), set_id="t", sheet="GI/210")
        assert schedule.stations == []
        assert len(schedule.trial_pits) == 1
        got = schedule.trial_pits[0]
        assert got.depth_m == 3.0 and got.max_depth_m == 4.5 and got.depth_in_soil_m == 3.0

    def test_a_pit_depth_never_lands_on_a_borehole_metre(self):
        """Pits are dug and boreholes are drilled; they are measured by different items. Putting
        pit metres into a drilling duration would inflate a rate with work no rig does."""
        pit = reader.RawStation(station="CE19-NTP01", kind="TP", depth_m=3.0, depth_in_soil_m=3.0)
        schedule = reader.to_schedule(
            reader.RawSchedule(trial_pits=[pit]), set_id="t", sheet="GI/210")
        assert schedule.soil_m() == 0.0 and schedule.rock_m() == 0.0

    def test_a_row_with_no_name_is_not_a_row(self):
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._row(station="  ")]), set_id="t", sheet="GI/210")
        assert schedule.stations == []


class TestTheMeasurementOutranksTheModel:
    """Repo trap 9, on the newest reader. A `None` is a cell nobody read, and it must never become
    a zero — `soil_m` and its two siblings are plain floats with no way to say "unknown"."""

    def test_an_unread_depth_is_marked_not_zeroed(self):
        row = reader.RawStation(station="CE19-ABH23", soil_m=None, rock_m=0.0,
                                hard_above_rockhead_m=0.0, length_m=30.0,
                                standpipe=False, piezometer=False)
        station = reader.to_schedule(
            reader.RawSchedule(boreholes=[row]), set_id="t", sheet="GI/210").stations[0]
        assert "soil_m" in station.unread
        assert station.soil_m == 0.0, "the model's default — nothing was written into it"

    def test_an_unread_tick_is_not_a_no(self):
        """47 standpipes and 68 piezometers read as uninstrumented is what this prevents."""
        row = reader.RawStation(station="CE19-ABH02", soil_m=30.0, rock_m=0.0,
                                hard_above_rockhead_m=0.0, standpipe=None, piezometer=False)
        station = reader.to_schedule(
            reader.RawSchedule(boreholes=[row]), set_id="t", sheet="GI/210").stations[0]
        assert "standpipe" in station.unread and station.standpipe is False
        assert "piezometer" not in station.unread

    def test_the_schedule_refuses_while_a_cell_is_unread(self):
        row = reader.RawStation(station="CE19-ABH23", soil_m=None, rock_m=0.0,
                                hard_above_rockhead_m=0.0, standpipe=False, piezometer=False)
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[row]), set_id="t", sheet="GI/210")
        assert not schedule.usable()
        assert schedule.unread_rows()

    def test_an_optional_field_models_absence_itself_and_needs_no_mark(self):
        row = reader.RawStation(station="CE19-ABH02", easting=None, soil_m=30.0, rock_m=0.0,
                                hard_above_rockhead_m=0.0, standpipe=False, piezometer=False)
        station = reader.to_schedule(
            reader.RawSchedule(boreholes=[row]), set_id="t", sheet="GI/210").stations[0]
        assert station.easting is None and "easting" not in station.unread

    def test_the_output_type_cannot_settle_anything(self):
        """Structural, like `DepartureProposal` having no status. A reader that can grade itself is
        a reader whose grade somebody will eventually believe."""
        fields = set(reader.RawSchedule.model_fields) | set(reader.RawStation.model_fields)
        assert not fields & {"confirmed", "confirmed_by", "usable", "checked", "confidence"}


class TestTheEnvironmentalSheetIsADifferentShape:
    """GI/310 is station, easting, northing and a sentence. Four columns and no soil/rock split."""

    @staticmethod
    def _environmental() -> reader.RawStation:
        return reader.RawStation(
            station="CE19-AEDH17A", kind="BH", easting=826789.98, northing=839105.13,
            termination="~6M BELOW EXISTING GROUND LEVEL OR +11MPD, WHICHEVER IS LOWER")

    def test_the_missing_columns_are_unread_not_zero(self):
        station = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._environmental()]),
            set_id="t", sheet="GI/310").stations[0]
        for field in reader.DEPTH_FIELDS:
            assert field in station.unread
        assert station.ground_level_mpd is None and station.rockhead_level_mpd is None

    def test_the_termination_rule_is_kept_verbatim_and_never_made_a_number(self):
        """It is a driller's instruction. Turning it into a metre would be the reader deciding
        something the drawing left to site."""
        station = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._environmental()]),
            set_id="t", sheet="GI/310").stations[0]
        assert any("WHICHEVER IS LOWER" in note for note in station.notes)
        assert station.soil_m == 0.0 and station.rock_m == 0.0

    def test_it_says_the_sheet_does_not_carry_the_split(self):
        station = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._environmental()]),
            set_id="t", sheet="GI/310").stations[0]
        assert any("not on the sheet is not a blank cell" in note for note in station.notes)

    def test_those_stations_cannot_pass_for_holes_that_drill_nothing(self):
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[self._environmental()]), set_id="t", sheet="GI/310")
        assert not schedule.usable()
        assert schedule.unread_rows()


class TestBothSheetsBecomeOneTakeOff:

    @staticmethod
    def _report(sheet: str, *stations: reader.RawStation) -> reader.ReadReport:
        return reader.ReadReport(
            schedule=reader.to_schedule(reader.RawSchedule(boreholes=list(stations)),
                                        set_id="t", sheet=sheet),
            sheet=sheet, read=True)

    def test_the_holes_from_both_sheets_are_in_it(self):
        merged = reader.merge([
            self._report("GI/210", reader.RawStation(station="CE19-ABH02", soil_m=30.0,
                                                     rock_m=0.0, hard_above_rockhead_m=0.0,
                                                     standpipe=True, piezometer=False)),
            self._report("GI/310", reader.RawStation(station="CE19-AEDH17A",
                                                     termination="~6M BELOW GROUND")),
        ], set_id="t")
        assert [s.station for s in merged.stations] == ["CE19-ABH02", "CE19-AEDH17A"]

    def test_each_hole_keeps_the_sheet_it_came_from(self):
        """A hole's provenance is how somebody checks it."""
        merged = reader.merge([
            self._report("GI/210", reader.RawStation(station="CE19-ABH02", soil_m=30.0,
                                                     rock_m=0.0, hard_above_rockhead_m=0.0,
                                                     standpipe=True, piezometer=False)),
            self._report("GI/310", reader.RawStation(station="CE19-AEDH17A",
                                                     termination="~6M BELOW GROUND")),
        ], set_id="t")
        assert {s.station: s.sheet for s in merged.stations} == {
            "CE19-ABH02": "GI/210", "CE19-AEDH17A": "GI/310"}
        assert merged.source_sheet == "GI/210 + GI/310"

    def test_a_sheet_that_could_not_be_read_is_named_on_the_take_off(self):
        """The take-off is then short by every hole on it, and saying so is the only thing that
        distinguishes that from a pack with fewer holes."""
        merged = reader.merge([
            self._report("GI/210", reader.RawStation(station="CE19-ABH02", soil_m=30.0,
                                                     rock_m=0.0, hard_above_rockhead_m=0.0,
                                                     standpipe=True, piezometer=False)),
            reader.ReadReport(sheet="GI/310", read=False, problem="the render came back empty"),
        ], set_id="t")
        assert any("GI/310 was NOT read" in note for note in merged.notes)

    def test_a_name_on_two_sheets_is_reported_and_not_resolved(self):
        """Two sheets claiming one station is a fact about the pack, not something to fix here."""
        merged = reader.merge([
            self._report("GI/210", reader.RawStation(station="CE19-ABH02", soil_m=30.0,
                                                     rock_m=0.0, hard_above_rockhead_m=0.0,
                                                     standpipe=False, piezometer=False)),
            self._report("GI/310", reader.RawStation(station="CE19-ABH02",
                                                     termination="~6M BELOW GROUND")),
        ], set_id="t")
        assert merged.duplicate_names()

    def test_the_merged_take_off_arrives_unconfirmed(self):
        merged = reader.merge([self._report("GI/210")], set_id="t")
        assert merged.confirmed_by == ""
        assert any("a proposal, not a confirmed take-off" in note for note in merged.notes)


class TestItNeverRaisesAndNeverInventsARead:

    def test_an_unrenderable_sheet_is_reported_as_unread(self):
        report = reader.read_sheet(b"not a pdf at all", set_id="t", sheet="GI/210")
        assert report.read is False
        assert report.problem
        assert report.schedule.stations == []

    def test_the_headline_never_calls_an_unread_sheet_empty(self):
        report = reader.read_sheet(b"not a pdf at all", set_id="t", sheet="GI/210")
        assert "was not read" in report.headline()

    def test_a_reader_that_returned_no_rows_says_so(self):
        report = reader.ReadReport(sheet="GI/210", read=True)
        assert "nobody has managed to read" in report.headline()
        assert "empty schedule" in report.headline()


class TestTheHttpSurface:

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
        from api import app

        return TestClient(app)

    def test_the_route_is_registered(self, client):
        assert "/client-boq/site/schedule/read" in client.app.openapi()["paths"]

    def test_a_drawing_it_cannot_identify_is_reported_not_guessed_at(self, client):
        response = client.post(
            "/client-boq/site/schedule/read",
            data={"set_id": "technopole-gi"},
            files=[("files", ("notes.txt", b"hello", "text/plain"))])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["triage"]["tier"] == "none"
        assert "not a pack with no schedule in it" in body["headline"]
        assert body["schedule"]["stations"] == []

    def test_it_saves_nothing(self, client):
        before = client.get("/client-boq/site/technopole-gi/schedule").json()
        client.post("/client-boq/site/schedule/read",
                    data={"set_id": "technopole-gi"},
                    files=[("files", ("notes.txt", b"hello", "text/plain"))])
        after = client.get("/client-boq/site/technopole-gi/schedule").json()
        assert before["stations"] == after["stations"] == []


# =================================================================================================
# The first live run: one sheet worked, the large one did not
# =================================================================================================
#
# GI/310 (9 rows, 5 columns) read correctly and in full — real coordinates, the four columns that
# sheet does not carry marked `unread` on all nine rows, the termination requirement verbatim,
# `usable: false` for the right reason. GI/210 (91 rows, 12 columns) failed outright:
#
#     reading the drawing failed (ValidationError: Invalid JSON: EOF while parsing
#     a value at line 1 column 0 [input_value='', input_type=str])
#
# THE ARITHMETIC SETTLES IT. Serialising this module's own output type for 91 boreholes and 21
# trial pits is 36,885 characters — roughly 9,200-10,250 output tokens. `DEFAULT_MAX_TOKENS` is
# 8,000 and this call passed no budget at all. GI/310's answer needs ~991. That is the entire
# difference between the two sheets, and it is measured rather than inferred.
#
# Three things compounded, and each is now closed:
#   * a vision call is FORCED to a VISION_CAPABLE provider, which excludes DeepSeek — so
#     `DEEPSEEK_MIN_MAX_TOKENS`, the floor that exists for exactly this failure, could never apply;
#   * `_anthropic_complete` had no truncation guard, unlike the other two providers;
#   * `complete_json`'s corrective retry re-sent the identical budget, so it failed identically.

class TestASheetTooBigForOneAnswer:
    """The fix is not a bigger constant. A bigger constant is a higher ceiling."""

    class _Truncates:
        """A client whose first answer never fits, and whose slices always do."""

        def __init__(self, rows_per_band: int = 3):
            self.calls: list[str] = []
            self.rows_per_band = rows_per_band

        def complete_json(self, *, user: str, **_kw):
            from pipeline.llm_client import CompletionTruncated

            self.calls.append(user)
            if "THIS IMAGE IS A SLICE" not in user:
                raise CompletionTruncated("the answer stopped mid-JSON")
            index = len(self.calls)
            base = (index - 2) * self.rows_per_band
            return reader.RawSchedule(boreholes=[
                reader.RawStation(station=f"CE19-ABH{base + n:02d}", soil_m=30.0, rock_m=0.0,
                                  hard_above_rockhead_m=0.0, length_m=30.0,
                                  standpipe=False, piezometer=False)
                for n in range(self.rows_per_band)])

    class _Fits:
        def __init__(self):
            self.calls: list[str] = []

        def complete_json(self, *, user: str, **_kw):
            self.calls.append(user)
            return reader.RawSchedule(boreholes=[
                reader.RawStation(station="CE19-ABH02", soil_m=30.0, rock_m=0.0,
                                  hard_above_rockhead_m=0.0, length_m=30.0,
                                  standpipe=False, piezometer=False)])

    @staticmethod
    def _sheet_pdf() -> bytes:
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=1191, height=842)
        page.insert_text((60, 40), "PROPOSED GI STATION EASTING NORTHING SOIL ROCK", fontsize=11)
        for n in range(40):
            page.insert_text((60, 90 + n * 18), f"CE19-ABH{n:02d} 825184.31 838917.94 30.00 0.00",
                             fontsize=9)
        data = doc.tobytes()
        doc.close()
        return data

    def test_a_sheet_that_fits_still_costs_exactly_one_call(self):
        """GI/310 read correctly before this change and must keep costing what it cost."""
        client = self._Fits()
        report = reader.read_sheet(self._sheet_pdf(), set_id="t", sheet="GI/310", client=client)
        assert report.read and report.bands == 1
        assert len(client.calls) == 1
        assert "THIS IMAGE IS A SLICE" not in client.calls[0]

    def test_a_truncated_answer_falls_back_to_slices(self):
        client = self._Truncates()
        report = reader.read_sheet(self._sheet_pdf(), set_id="t", sheet="GI/210", client=client,
                                   bands_on_truncation=4)
        assert report.read is True
        assert report.bands == 4
        assert len(client.calls) == 5, "one whole-sheet attempt, then one per slice"
        assert len(report.schedule.stations) == 12

    def test_every_slice_is_told_it_is_a_slice_and_where_the_header_is(self):
        client = self._Truncates()
        reader.read_sheet(self._sheet_pdf(), set_id="t", sheet="GI/210", client=client,
                          bands_on_truncation=4)
        for call in client.calls[1:]:
            assert "THIS IMAGE IS A SLICE" in call
            assert "column headings are reproduced at the top" in call
            assert "expect the first and last of them to also appear" in call

    def test_the_take_off_says_it_was_read_in_slices(self):
        client = self._Truncates()
        report = reader.read_sheet(self._sheet_pdf(), set_id="t", sheet="GI/210", client=client,
                                   bands_on_truncation=4)
        assert any("read in 4 slices" in note for note in report.schedule.notes)
        assert "one call could not hold the whole sheet" in report.headline()

    def test_a_row_read_twice_by_the_overlap_survives_once(self):
        """Bands overlap on purpose so no row is cut in half. The duplicate is an artefact of how
        the sheet was cut, not a fact about the pack, so it is dropped here rather than reported."""
        both = reader.RawSchedule(boreholes=[
            reader.RawStation(station="CE19-ABH07", soil_m=30.0, rock_m=0.0,
                              hard_above_rockhead_m=0.0, standpipe=False, piezometer=False)])
        merged = reader._merge_raw([both, both, both])
        assert [r.station for r in merged.boreholes] == ["CE19-ABH07"]

    def test_a_station_on_two_different_sheets_is_still_reported(self):
        """De-duplicating within a sheet must not silence the cross-sheet check."""
        one = reader.ReadReport(
            schedule=reader.to_schedule(reader.RawSchedule(boreholes=[
                reader.RawStation(station="CE19-ABH02", soil_m=30.0, rock_m=0.0,
                                  hard_above_rockhead_m=0.0, standpipe=False, piezometer=False)]),
                set_id="t", sheet="GI/210"), sheet="GI/210", read=True)
        two = reader.ReadReport(
            schedule=reader.to_schedule(reader.RawSchedule(boreholes=[
                reader.RawStation(station="CE19-ABH02", termination="~6M BELOW GROUND")]),
                set_id="t", sheet="GI/310"), sheet="GI/310", read=True)
        assert reader.merge([one, two], set_id="t").duplicate_names()


class TestAPartialReadIsAReadAndSaysSo:
    """The degrade-not-fail rule, actually honoured: today one failure zeroes 91 rows."""

    class _OneBandFails:
        def __init__(self, bad: int = 3):
            self.calls = 0
            self.bad = bad

        def complete_json(self, *, user: str, **_kw):
            from pipeline.llm_client import CompletionTruncated

            self.calls += 1
            if "THIS IMAGE IS A SLICE" not in user:
                raise CompletionTruncated("the answer stopped mid-JSON")
            index = self.calls - 1          # 1-based slice number
            if index == self.bad:
                raise RuntimeError("the model returned nothing for this slice")
            return reader.RawSchedule(boreholes=[
                reader.RawStation(station=f"CE19-ABH{index:02d}", soil_m=30.0, rock_m=0.0,
                                  hard_above_rockhead_m=0.0, length_m=30.0,
                                  standpipe=False, piezometer=False)])

    def _report(self, bad: int = 3) -> reader.ReadReport:
        return reader.read_sheet(TestASheetTooBigForOneAnswer._sheet_pdf(), set_id="t",
                                 sheet="GI/210", client=self._OneBandFails(bad),
                                 bands_on_truncation=4)

    def test_the_slices_that_worked_are_kept(self):
        report = self._report()
        assert report.read is True
        assert len(report.schedule.stations) == 3, "three of four slices came back"

    def test_the_slice_that_failed_is_named(self):
        report = self._report()
        assert report.partial()
        assert len(report.bands_failed) == 1
        assert "slice 3 of 4 failed" in report.bands_failed[0]

    def test_every_slice_is_attempted_even_after_one_fails(self):
        """Abandoning the rest at the first error gives back the whole point of slicing."""
        client = self._OneBandFails(bad=2)
        reader.read_sheet(TestASheetTooBigForOneAnswer._sheet_pdf(), set_id="t", sheet="GI/210",
                          client=client, bands_on_truncation=4)
        assert client.calls == 5

    def test_the_headline_refuses_to_call_the_total_the_sheets_total(self):
        headline = self._report().headline()
        assert "ONLY PARTLY READ" in headline
        assert "no total on it is the sheet's total" in headline

    def test_the_warning_travels_on_the_take_off_not_only_in_the_report(self):
        """A screen may show the schedule and not the per-sheet report. The note goes with the
        thing that gets saved."""
        merged = reader.merge([self._report()], set_id="t")
        assert any("only PARTLY read" in note for note in merged.notes)
        assert any("no total on this take-off is that sheet's total" in note
                   for note in merged.notes)

    def test_a_sheet_where_every_slice_fails_is_unread_not_empty(self):
        class _AllFail:
            def complete_json(self, *, user: str, **_kw):
                from pipeline.llm_client import CompletionTruncated

                raise CompletionTruncated("nothing fits")

        report = reader.read_sheet(TestASheetTooBigForOneAnswer._sheet_pdf(), set_id="t",
                                   sheet="GI/210", client=_AllFail(), bands_on_truncation=4)
        assert report.read is False
        assert "none of its 4 slices could be read" in report.problem

    def test_a_failure_that_is_not_a_truncation_is_not_sliced(self):
        """Slicing a sheet the model refused, or could not see, would be four refusals instead of
        one — and the message would stop naming the real reason."""
        class _Refuses:
            def __init__(self):
                self.calls = 0

            def complete_json(self, **_kw):
                self.calls += 1
                raise RuntimeError("the request was rejected")

        client = _Refuses()
        report = reader.read_sheet(TestASheetTooBigForOneAnswer._sheet_pdf(), set_id="t",
                                   sheet="GI/210", client=client, bands_on_truncation=4)
        assert client.calls == 1
        assert report.read is False
        assert "the request was rejected" in report.problem


class TestTheBudgetIsAskedForRatherThanDefaulted:

    def test_the_reader_asks_for_more_than_the_default(self):
        """The measured need is ~9,200-10,250 output tokens for 91 rows; the default is 8,000."""
        from pipeline.llm_client import DEFAULT_MAX_TOKENS

        assert reader.READ_MAX_TOKENS > DEFAULT_MAX_TOKENS
        assert reader.READ_MAX_TOKENS >= 10_250, "the real sheet's answer must fit"

    def test_the_budget_actually_reaches_the_call(self):
        seen: dict = {}

        class _Records:
            def complete_json(self, **kw):
                seen.update(kw)
                return reader.RawSchedule()

        reader.read_sheet(TestASheetTooBigForOneAnswer._sheet_pdf(), set_id="t", sheet="GI/210",
                          client=_Records())
        assert seen["max_tokens"] == reader.READ_MAX_TOKENS

    def test_a_vision_call_can_never_reach_the_deepseek_floor(self):
        """Why the existing guard could not help: `_route` forces any request carrying images onto
        a VISION_CAPABLE provider, and DeepSeek is not in that set."""
        from pipeline.llm_client import VISION_CAPABLE

        assert "deepseek" not in VISION_CAPABLE


# =================================================================================================
# The second live run: GI/310 stable, GI/210 failing two different ways
# =================================================================================================
#
# FINDING B, and it is the one that destroyed correct work. Slices 3 and 4 did NOT truncate — they
# came back as complete JSON and failed validation, ~47 and ~21 errors, every one of them:
#
#     boreholes.0.termination
#       Input should be a valid string [type=string_type, input_value=None, input_type=NoneType]
#
# GI/210's boreholes have no termination column; it exists only on GI/310. So the model correctly
# found nothing to put there and returned null, and a plain `str` field rejected it. A default makes
# a field safe to OMIT and does nothing when the key is present holding null.
#
# Then pydantic validates the payload as ONE object, so rejecting one row's `termination` discarded
# every field on every row in that slice — including the ground level, the rockhead and the
# soil/rock split the model plainly had read.
#
# Measured: `station`, `kind` AND `termination` all rejected null. Three fields, not one.
#
# FINDING A is not what the shape suggests, and this is why the constant was NOT raised again.
# The message that fired only fires on EMPTY text, and slices 3 and 4 wrote complete JSON on the
# same model, the same budget and the same prompt shape. So the answer is demonstrably writable:
# something other than the answer consumed slices 1 and 2. Raising the ceiling would buy more of
# whatever that is. The guard now reports where the tokens went instead of guessing.

class TestAColumnThatIsNotOnTheSheet:
    """Finding B. The principle this module already enforced for the depth columns, one field late."""

    def test_every_text_field_accepts_null(self):
        """All three rejected it. Any of them could have destroyed a slice."""
        for field in ("station", "kind", "termination"):
            row = reader.RawStation.model_validate({field: None})
            assert getattr(row, field) is None

    def test_the_exact_live_payload_validates(self):
        got = reader.RawSchedule.model_validate(
            {"boreholes": [{"station": "CE19-ABH02", "easting": 825184.31, "soil_m": 30.0,
                            "termination": None}]})
        assert len(got.boreholes) == 1
        assert got.boreholes[0].soil_m == 30.0

    def test_a_borehole_with_no_termination_column_still_maps(self):
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[reader.RawStation(
                station="CE19-ABH02", soil_m=30.0, rock_m=0.0, hard_above_rockhead_m=0.0,
                length_m=30.0, standpipe=True, piezometer=False, termination=None)]),
            set_id="t", sheet="GI/210")
        station = schedule.stations[0]
        assert station.soil_m == 30.0 and station.unread == []
        assert not any("termination" in note for note in station.notes)

    def test_the_environmental_sheet_still_keeps_its_sentence(self):
        """Making the field optional must not lose the one sheet that carries it."""
        schedule = reader.to_schedule(
            reader.RawSchedule(boreholes=[reader.RawStation(
                station="CE19-AEDH17A",
                termination="~6M BELOW EXISTING GROUND LEVEL OR +11MPD, WHICHEVER IS LOWER")]),
            set_id="t", sheet="GI/310")
        assert any("WHICHEVER IS LOWER" in note for note in schedule.stations[0].notes)


class TestOneBadCellCannotTakeTheSliceWithIt:
    """The structural half. Even with the three fields fixed, ANY future mismatch would have
    discarded a whole band — so the reader's output type is now the most tolerant thing here."""

    def test_a_null_in_one_row_no_longer_discards_the_others(self):
        payload = {"boreholes": [
            {"station": f"CE19-ABH{n:02d}", "easting": 825184.31, "soil_m": 30.0}
            for n in range(23)]}
        payload["boreholes"][11]["termination"] = None
        assert len(reader.RawSchedule.model_validate(payload).boreholes) == 23

    def test_an_unreadable_cell_degrades_to_that_cell(self):
        """"n/a" in a numeric column is exactly what `None` means here — not read. It must cost
        one cell, not one row and not one slice."""
        got = reader.RawSchedule.model_validate(
            {"boreholes": [{"station": "CE19-ABH02", "soil_m": "n/a", "rock_m": "5.00"}]})
        assert got.boreholes[0].soil_m is None
        assert got.boreholes[0].rock_m == 5.0

    def test_a_number_written_with_a_thousands_separator_is_still_a_number(self):
        got = reader.RawSchedule.model_validate(
            {"boreholes": [{"station": "X", "easting": "825,184.31"}]})
        assert got.boreholes[0].easting == 825184.31

    def test_a_row_that_is_not_a_row_is_named_rather_than_fatal(self):
        payload = {"boreholes": [{"station": "CE19-ABH02", "soil_m": 30.0}, "not a row at all"]}
        got = reader.RawSchedule.model_validate(payload)
        assert len(got.boreholes) == 1
        assert got.unusable_rows == ["not a row at all"]

    def test_the_dropped_rows_reach_the_take_off(self):
        """No silent drops. A slice that lost four rows is a different thing from one that read
        four fewer, and only the take-off's own notes can say which."""
        schedule = reader.to_schedule(
            reader.RawSchedule.model_validate(
                {"boreholes": [{"station": "CE19-ABH02", "soil_m": 30.0}, 42]}),
            set_id="t", sheet="GI/210")
        assert any("could not be made into a station" in note for note in schedule.notes)

    def test_they_survive_the_merge_across_slices(self):
        one = reader.RawSchedule.model_validate({"boreholes": [{"station": "A"}, "junk one"]})
        two = reader.RawSchedule.model_validate({"boreholes": [{"station": "B"}, "junk two"]})
        merged = reader._merge_raw([one, two])
        assert merged.unusable_rows == ["junk one", "junk two"]


class TestTheAskIsSmallerAndTheBandsAreNotDoubled:
    """Finding A's two changes that are measurements rather than guesses."""

    def test_the_reader_asks_the_model_to_omit_empty_fields(self):
        """Measured: 329 chars per row with every key, 255 without the empty ones — 22% of a
        91-row answer, for no information at all."""
        assert "OMIT any field you have no value for" in reader.INSTRUCTION
        assert "means exactly what null means" in reader.INSTRUCTION

    def test_an_omitted_field_still_means_not_read(self):
        """The instruction is only safe because the two are identical to the mapper."""
        omitted = reader.RawSchedule.model_validate({"boreholes": [{"station": "X"}]})
        explicit = reader.RawSchedule.model_validate(
            {"boreholes": [{"station": "X", "soil_m": None, "rock_m": None,
                            "hard_above_rockhead_m": None}]})
        assert (reader.to_schedule(omitted, set_id="t", sheet="s").stations[0].unread
                == reader.to_schedule(explicit, set_id="t", sheet="s").stations[0].unread)

    def test_the_first_band_does_not_carry_its_own_header_twice(self):
        """Band 0's body IS the head of the sheet. Composing the header strip above it printed the
        table's heading twice and repeated the first rows under themselves."""
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=1191, height=842)
        page.insert_text((60, 40), "HEADERROW EASTING NORTHING", fontsize=11)
        for n in range(40):
            page.insert_text((60, 90 + n * 18), f"CE19-ABH{n:02d} 825184.31 838917.94", fontsize=9)
        data = doc.tobytes()
        doc.close()

        from client_boq.ingest import pdfops

        first = pdfops.render_band(data, 1, 0, 4)
        second = pdfops.render_band(data, 1, 1, 4)
        assert first and second
        assert len(first) < len(second), "band 0 is no longer the tallest image of the four"

    def test_a_middle_band_still_gets_the_header(self):
        """The fix must not take the column names away from the bands that need them."""
        import fitz

        from client_boq.ingest import pdfops

        doc = fitz.open()
        page = doc.new_page(width=1191, height=842)
        page.insert_text((60, 40), "HEADERROW EASTING NORTHING", fontsize=11)
        for n in range(40):
            page.insert_text((60, 90 + n * 18), f"CE19-ABH{n:02d} 825184.31 838917.94", fontsize=9)
        rect = page.rect
        data = doc.tobytes()
        doc.close()

        source = fitz.open(stream=data, filetype="pdf")
        height = rect.height
        overlap, step = height * pdfops.BAND_OVERLAP_SHARE, height / 4
        top = max(rect.y0, rect.y0 + 2 * step - overlap)
        header = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + height * pdfops.BAND_HEADER_SHARE)
        body = fitz.Rect(rect.x0, top, rect.x1, min(rect.y1, rect.y0 + 3 * step + overlap))
        composed = fitz.open()
        target = composed.new_page(width=rect.width, height=header.height + body.height)
        target.show_pdf_page(fitz.Rect(0, 0, rect.width, header.height), source, 0, clip=header)
        target.show_pdf_page(
            fitz.Rect(0, header.height, rect.width, header.height + body.height),
            source, 0, clip=body)
        assert "HEADERROW" in target.get_text()
        composed.close()
        source.close()
