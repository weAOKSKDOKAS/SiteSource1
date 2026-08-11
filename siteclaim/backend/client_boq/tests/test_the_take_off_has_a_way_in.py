"""The station schedule's door: a pasted table becomes a proposed take-off.

`POST /site/schedule` has always accepted a `StationSchedule` and nothing in this application ever
produced one — no frontend call (`grep site/schedule` over `src/` returned nothing), no backend
constructor outside the class statement, zero rows in the demo database. The screen said "read it
off the borehole details drawing and save it first", an instruction the app gave no means of
following, and behind that dead end sat the bill-vs-drawing check, the access map, and the only
place in the whole application where a hole is given its class.

So this is the door, and the rule it is built on is the one `Station.unread` was added for:

    **A cell this cannot read is named, never filled in.**

Writing 0.0 into a soil cell that read "n/a" produces a hole that drills no soil — a confident,
specific, wrong number that flows into Σ soil and out again into a rate. Every test below is some
version of that sentence.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.boq import schedule_paste as paste

BASE = "/client-boq"
SET = "technopole-gi"

HEADER = ("Station\tEasting\tNorthing\tGround Level\tRockhead\tTentative Length\t"
          "Max Boring\tLength in Soil\tHard\tLength in Rock\tStandpipe\tPiezometer")


def _line(name, e, n, gl, rh, length, mx, soil, hard, rock, sp, pz) -> str:
    return "\t".join(str(v) for v in
                     (name, e, n, gl, rh, length, mx, soil, hard, rock, sp, pz))


CLEAN = "\n".join([
    HEADER,
    _line("CE19-ABH01", 834120.5, 817430.2, 34.90, 5.00, 34.90, 40.0, 29.90, 0.0, 5.00, "Y", "N"),
    _line("CE19-ABH02", 834180.0, 817500.0, 26.10, 3.20, 26.10, 30.0, 21.10, 0.0, 5.00, "N", "Y"),
])


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestItReadsAnOrdinaryPaste:

    def test_a_headed_tab_table_reads_every_column(self):
        report = paste.parse(CLEAN, set_id=SET, source_sheet="60740338/GI/210")
        assert report.header_found and report.delimiter == "tab"
        assert len(report.schedule.stations) == 2
        first = report.schedule.stations[0]
        assert first.station == "CE19-ABH01"
        assert first.easting == 834120.5 and first.northing == 817430.2
        assert first.soil_m == 29.90 and first.rock_m == 5.00
        assert first.standpipe is True and first.piezometer is False
        assert first.sheet == "60740338/GI/210"

    def test_the_sums_the_bill_is_checked_against_come_out(self):
        s = paste.parse(CLEAN).schedule
        assert s.soil_m() == 51.0 and s.rock_m() == 10.0
        assert s.hole_count() == 2 and s.standpipes() == 1 and s.piezometers() == 1

    def test_the_rows_satisfy_their_own_arithmetic_so_nothing_is_flagged(self):
        """29.90 + 5.00 = 34.90 and 21.10 + 5.00 = 26.10 — the four sums quoted in the module
        docstring as measured off the real sheet."""
        report = paste.parse(CLEAN)
        assert report.schedule.usable()
        assert report.schedule.problems() == []
        assert "Every cell was read" in report.headline()

    def test_commas_and_double_spaces_are_read_too(self):
        """A PDF table lands on the clipboard with runs of spaces; a CSV export lands with commas.
        Both are what the estimator actually has."""
        commas = "Station,Easting,Northing,Length in Soil,Length in Rock\nABH01,834120,817430,30,5"
        spaced = "Station   Easting   Northing   Length in Soil   Length in Rock\n" \
                 "ABH01     834120    817430     30               5"
        for text, name in ((commas, "comma"), (spaced, "spaces")):
            report = paste.parse(text)
            assert report.delimiter == name
            assert report.schedule.stations[0].soil_m == 30.0
            assert report.schedule.stations[0].rock_m == 5.0

    def test_a_unit_written_after_the_number_is_not_a_smudge(self):
        """"34.90 m" and "+8.15mPD" are how a person writes it down."""
        text = "Station\tGround Level\tLength in Soil\tLength in Rock\nABH01\t8.15mPD\t29.90 m\t5 m"
        s = paste.parse(text).schedule.stations[0]
        assert s.ground_level_mpd == 8.15 and s.soil_m == 29.90 and s.rock_m == 5.0
        assert s.unread == []

    def test_a_thousands_separator_survives(self):
        text = "Station\tEasting\tNorthing\nABH01\t834,120.50\t817,430.20"
        s = paste.parse(text).schedule.stations[0]
        assert s.easting == 834120.5 and s.northing == 817430.2


class TestACellItCannotReadIsNamedNeverFilledIn:

    def test_an_unreadable_soil_cell_is_marked_unread_and_not_zeroed(self):
        text = "Station\tLength in Soil\tLength in Rock\nABH01\tn/a\t5.0"
        s = paste.parse(text).schedule.stations[0]
        assert "soil_m" in s.unread
        assert s.soil_m == 0.0, "the model default — nothing was written into it"
        assert any("blank is not a zero" in n for n in s.notes)

    def test_a_cell_that_is_not_a_number_says_what_it_actually_said(self):
        """A blank and a smudge are different problems and get different sentences: one is a cell
        nobody filled in, the other is a cell nobody could make out."""
        text = "Station\tLength in Soil\tLength in Rock\nABH01\tapprox 30\t5.0"
        s = paste.parse(text).schedule.stations[0]
        assert "soil_m" in s.unread
        assert any("'approx 30' is not a number" in n for n in s.notes)

    def test_a_smudge_is_never_mistaken_for_a_blank(self):
        """`"***"` strips to the empty string under any key-normalising comparison, which would make
        it a blank. A row of asterisks is exactly the smudge this module exists to name."""
        text = "Station\tLength in Soil\tLength in Rock\nABH01\t***\t5.0"
        s = paste.parse(text).schedule.stations[0]
        assert "soil_m" in s.unread
        assert s.soil_m == 0.0, "the value is still the model's default — it was never written"

    def test_a_blank_depth_cell_is_unread_because_the_field_cannot_say_unknown(self):
        text = "Station\tLength in Soil\tLength in Rock\nABH01\t-\t5.0"
        s = paste.parse(text).schedule.stations[0]
        assert "soil_m" in s.unread

    def test_a_blank_optional_cell_is_simply_none_and_is_not_flagged(self):
        """`easting` is Optional on the model and already says "unknown" honestly. Marking it unread
        as well would cry wolf on every hole whose coordinates are on a different sheet."""
        text = "Station\tEasting\tLength in Soil\tLength in Rock\nABH01\t-\t30\t5"
        s = paste.parse(text).schedule.stations[0]
        assert s.easting is None and s.unread == []

    def test_an_unrecognised_tick_is_unread_not_a_no(self):
        """A "no" is a decision. An unreadable mark is not one, and 47 standpipes read as zero is
        an instrument nobody prices."""
        text = "Station\tLength in Soil\tLength in Rock\tStandpipe\nABH01\t30\t5\t?"
        s = paste.parse(text).schedule.stations[0]
        assert "standpipe" in s.unread and s.standpipe is False

    def test_a_real_tick_survives_being_punctuation(self):
        """"✓" strips to nothing under a key comparison, so a key-based reader marks every
        instrumented hole uninstrumented. That is the whole reason ticks compare on raw text."""
        text = "Station\tLength in Soil\tLength in Rock\tStandpipe\tPiezometer\nABH01\t30\t5\t✓\t—"
        s = paste.parse(text).schedule.stations[0]
        assert s.standpipe is True and s.piezometer is False and s.unread == []

    def test_the_schedule_refuses_while_a_cell_is_unread(self):
        text = "Station\tLength in Soil\tLength in Rock\nABH01\tn/a\t5.0"
        report = paste.parse(text)
        assert not report.schedule.usable()
        assert report.cells_unread() == 1
        assert "could not be read" in report.headline()
        assert "Nothing was guessed at" in report.headline()


class TestItDegradesRatherThanFails:

    def test_a_headerless_paste_is_read_in_the_printed_order_of_the_sheet(self):
        """The estimator pastes the rows without the header, which is most of the time. COLUMNS is
        in GI/210's printed order for exactly this."""
        body = "\n".join(CLEAN.split("\n")[1:])
        report = paste.parse(body)
        assert not report.header_found and report.mapping == {}
        s = report.schedule.stations[0]
        assert s.station == "CE19-ABH01" and s.soil_m == 29.90 and s.rock_m == 5.00

    def test_a_line_that_is_not_a_row_is_kept_and_named(self):
        text = CLEAN + "\n\nNotes: levels are in mPD"
        report = paste.parse(text)
        assert len(report.schedule.stations) == 2
        assert len(report.skipped_lines) == 1
        assert "Notes" in report.skipped_lines[0]
        assert "were not rows" in report.headline()

    def test_a_column_it_does_not_understand_is_named_never_dropped(self):
        text = ("Station\tLength in Soil\tLength in Rock\tRemarks\n"
                "ABH01\t30\t5\tadjacent to nullah")
        report = paste.parse(text)
        assert report.unmapped_columns == ["Remarks"]
        assert report.schedule.stations[0].soil_m == 30.0

    def test_a_column_the_paste_does_not_carry_is_named_too(self):
        text = "Station\tLength in Soil\tLength in Rock\nABH01\t30\t5"
        report = paste.parse(text)
        assert "easting" in report.missing_columns and "standpipe" in report.missing_columns
        assert "soil_m" not in report.missing_columns

    def test_empty_text_returns_an_empty_proposal_and_says_so(self):
        report = paste.parse("")
        assert report.schedule.stations == []
        assert "Nothing in that paste looked like a station row" in report.headline()

    def test_prose_pasted_by_accident_produces_no_stations(self):
        report = paste.parse("Every quantity in Bill No.2 comes from the borehole details drawing.")
        assert report.schedule.stations == []

    def test_a_short_row_is_read_as_far_as_it_goes(self):
        text = HEADER + "\nCE19-ABH01\t834120\t817430"
        s = paste.parse(text).schedule.stations[0]
        assert s.easting == 834120.0 and s.northing == 817430.0
        assert "soil_m" in s.unread and "rock_m" in s.unread


class TestTrialPitsGoToTheirOwnList:

    def test_a_pit_is_routed_by_its_name(self):
        text = HEADER + "\n" + _line("CE19-NTP01", 834000, 817000, 30.0, "", 3.0, "", 3.0, 0, 0,
                                     "", "")
        report = paste.parse(text)
        assert report.schedule.stations == []
        assert len(report.schedule.trial_pits) == 1
        assert report.schedule.trial_pits[0].depth_m == 3.0

    def test_a_borehole_is_not_routed_to_the_pits(self):
        report = paste.parse(CLEAN)
        assert report.schedule.trial_pits == [] and len(report.schedule.stations) == 2


class TestItNeverSaves:

    def test_parse_touches_no_store(self, client):
        """The proposal is returned and the set stays exactly as empty as it was. Saving is a
        separate call a person makes — the same shape every other machine-derived thing here has."""
        before = client.get(f"{BASE}/site/{SET}/schedule").json()
        assert before["stations"] == []
        parsed = client.post(f"{BASE}/site/schedule/parse",
                             json={"set_id": SET, "text": CLEAN,
                                   "source_sheet": "60740338/GI/210"}).json()
        assert len(parsed["schedule"]["stations"]) == 2
        after = client.get(f"{BASE}/site/{SET}/schedule").json()
        assert after["stations"] == [], "parsing must not have written anything"

    def test_the_parsed_proposal_can_be_saved_through_the_existing_writer(self, client):
        """The whole point: parse, look, then save. The endpoint the app never called."""
        parsed = client.post(f"{BASE}/site/schedule/parse",
                             json={"set_id": SET, "text": CLEAN,
                                   "source_sheet": "60740338/GI/210"}).json()
        saved = client.post(f"{BASE}/site/schedule",
                            json={"set_id": SET, "schedule": parsed["schedule"],
                                  "source_sheet": "60740338/GI/210"},
                            headers={"X-CBOQ-Actor": "SW"})
        assert saved.status_code == 200, saved.text
        got = client.get(f"{BASE}/site/{SET}/schedule").json()
        assert len(got["stations"]) == 2
        assert got["totals"]["soil_m"] == 51.0
        assert got["usable"] is True

    def test_it_arrives_unconfirmed_because_a_machine_read_it(self, client):
        """`confirm` is a person saying they checked it. A parse cannot say that on their behalf,
        and the request the parser produces carries no way to."""
        parsed = client.post(f"{BASE}/site/schedule/parse",
                             json={"set_id": SET, "text": CLEAN}).json()
        assert "confirm" not in parsed
        client.post(f"{BASE}/site/schedule",
                    json={"set_id": SET, "schedule": parsed["schedule"]})
        got = client.get(f"{BASE}/site/{SET}/schedule").json()
        assert got["meta"]["confirmed_by"] == ""


class TestTheHttpSurface:

    def test_it_reports_every_check_the_saved_schedule_will_report(self, client):
        """What the screen shows before saving must be what it shows after, or the paste box is a
        different opinion from the take-off it produced."""
        text = "Station\tLength in Soil\tLength in Rock\nABH01\tn/a\t5.0\nABH01\t30\t5"
        body = client.post(f"{BASE}/site/schedule/parse",
                           json={"set_id": SET, "text": text}).json()
        assert body["usable"] is False
        assert body["unread_rows"] and body["duplicate_names"]
        assert body["cells_unread"] == 1
        assert len(body["problems"]) == len(body["bad_rows"]) + len(body["unread_rows"]) \
            + len(body["empty_rows"]) + len(body["duplicate_names"])

    def test_it_says_how_it_read_the_paste(self, client):
        body = client.post(f"{BASE}/site/schedule/parse",
                           json={"set_id": SET, "text": CLEAN}).json()
        assert body["header_found"] is True and body["delimiter"] == "tab"
        assert body["mapping"]["soil_m"] == "Length in Soil"
        assert body["totals"]["soil_m"] == 51.0

    def test_the_route_is_registered(self, client):
        assert "/client-boq/site/schedule/parse" in client.app.openapi()["paths"]
