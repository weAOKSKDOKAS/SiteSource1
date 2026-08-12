"""Capturing one real tender as a committable demo — and what must never come with it.

The point of a capture is that testing the product stops costing API credit and a `curl` per step.
The point of THIS file is that the capture stays honest in two directions at once:

* it is **the real run, not a tidied one** — the arithmetic mismatches, the unread cells and the
  partial coverage come across untouched, because a demo where everything is clean hides the
  surfaces that took longest to build;
* and it carries **nothing that would be dishonest or unsafe to replay** — no contact details, no
  operator's name, no key, no token.

The second is checked over the SERIALISED bundle rather than per column, and that is the whole
design of `offences()`: a register, a letter and an outputs row are all JSON text, so an address
inside one of those blobs would pass any rule written about column names. Measured on this
installation: `db/sitesource.db` holds a real `enquiry_email` for 1,365 of 1,423 firms and
`fixtures/out/outbox.json` carries composed enquiries addressed to them.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from client_boq import demo_capture, models


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "cap.db"
    sqlite3.connect(str(path)).close()
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    models.init_tables(connection)
    yield connection
    connection.close()


def _a_tender(conn, set_id="nd-2025-04", actor="Siu Wai Lam"):
    """A tender with the shapes that matter: a person's name, and a flawed reading."""
    conn.execute(
        "INSERT INTO client_boq_document_sets (set_id, name, slug, status) VALUES (?,?,?,?)",
        (set_id, "San Tin Technopole Phase 2", set_id, "reviewed"))
    conn.execute(
        "INSERT INTO client_boq_set_meta (set_id, owner_id, last_touched_by) VALUES (?,?,?)",
        (set_id, actor, actor))
    conn.execute(
        "INSERT INTO client_boq_manifests (set_id, approved, tier) VALUES (?,?,?)", (set_id, 1, 3))
    conn.commit()
    return set_id


class TestTheCaptureIsTheRealRun:
    def test_it_carries_the_tender_across(self, conn):
        set_id = _a_tender(conn)
        bundle = demo_capture.export_set(conn, set_id)
        assert bundle["set_id"] == set_id
        assert "client_boq_document_sets" in bundle["tables"]
        assert bundle["tables"]["client_boq_document_sets"][0]["name"] == \
            "San Tin Technopole Phase 2"

    def test_it_does_not_repair_anything(self, conn):
        """A take-off with unread cells and failing rows is the artifact worth having. Nothing in
        the capture path sorts, completes or corrects — it copies rows."""
        set_id = _a_tender(conn)
        schedule = {"stations": [
            {"station": "CE19-ABH19", "soil_m": 20.0, "rock_m": 5.0, "length_m": 34.9,
             "unread": ["rock_m"]}]}
        conn.execute(
            "INSERT INTO client_boq_station_schedules (set_id, schedule_json) VALUES (?,?)",
            (set_id, json.dumps(schedule)))
        conn.commit()
        out = demo_capture.export_set(conn, set_id)
        got = json.loads(out["tables"]["client_boq_station_schedules"][0]["schedule_json"])
        assert got == schedule, "the capture changed a reading it was only meant to copy"
        assert got["stations"][0]["unread"] == ["rock_m"]

    def test_a_round_trip_is_byte_identical(self, conn, tmp_path):
        set_id = _a_tender(conn)
        bundle = demo_capture.export_set(conn, set_id)

        other = sqlite3.connect(str(tmp_path / "replay.db"))
        other.row_factory = sqlite3.Row
        try:
            demo_capture.load_bundle(other, bundle)
            replayed = demo_capture.export_set(other, set_id)
        finally:
            other.close()
        assert replayed == bundle

    def test_loading_twice_does_not_double_anything(self, conn, tmp_path):
        set_id = _a_tender(conn)
        bundle = demo_capture.export_set(conn, set_id)
        other = sqlite3.connect(str(tmp_path / "replay.db"))
        try:
            demo_capture.load_bundle(other, bundle)
            demo_capture.load_bundle(other, bundle)
            n = other.execute(
                "SELECT COUNT(*) FROM client_boq_document_sets WHERE set_id = ?",
                (set_id,)).fetchone()[0]
        finally:
            other.close()
        assert n == 1

    def test_a_bundle_from_a_newer_schema_still_loads(self, conn, tmp_path):
        """An extra column is dropped rather than failing the whole load — otherwise a capture
        taken after one migration cannot be opened before it."""
        bundle = {"version": demo_capture.BUNDLE_VERSION, "set_id": "s", "tables": {
            "client_boq_document_sets": [
                {"set_id": "s", "name": "n", "slug": "s", "status": "reviewed",
                 "a_column_from_the_future": "x"}]}}
        other = sqlite3.connect(str(tmp_path / "old.db"))
        try:
            demo_capture.load_bundle(other, bundle)
            assert other.execute("SELECT name FROM client_boq_document_sets").fetchone()[0] == "n"
        finally:
            other.close()

    def test_a_bundle_of_the_wrong_version_is_refused(self, tmp_path):
        other = sqlite3.connect(str(tmp_path / "x.db"))
        try:
            with pytest.raises(ValueError, match="version"):
                demo_capture.load_bundle(other, {"version": 99, "set_id": "s", "tables": {}})
        finally:
            other.close()

    def test_it_refuses_to_write_a_table_that_is_not_a_tenders(self, tmp_path):
        """The library tables — criteria, rates, the costing model — are an installation's, not one
        tender's. A demo that shipped them would overwrite somebody's edited criteria library."""
        other = sqlite3.connect(str(tmp_path / "x.db"))
        try:
            with pytest.raises(ValueError, match="not a tender table"):
                demo_capture.load_bundle(other, {
                    "version": demo_capture.BUNDLE_VERSION, "set_id": "s",
                    "tables": {"client_boq_criteria": [{"set_id": "s"}]}})
        finally:
            other.close()

    def test_the_library_tables_are_not_in_the_capture_list(self):
        for table in ("client_boq_criteria", "client_boq_rates", "client_boq_settings",
                      "client_boq_team_members", "client_boq_threshold_rules",
                      "client_boq_costing_models"):
            assert table not in demo_capture.TENDER_TABLES, (
                f"{table} is an installation's library, not one tender's work")


class TestNothingUnsafeShips:
    def test_an_operators_name_becomes_a_placeholder(self, conn):
        set_id = _a_tender(conn, actor="Siu Wai Lam")
        bundle = demo_capture.export_set(conn, set_id)
        meta = bundle["tables"]["client_boq_set_meta"][0]
        assert meta["owner_id"] == demo_capture.PLACEHOLDER_ACTOR
        assert meta["last_touched_by"] == demo_capture.PLACEHOLDER_ACTOR
        assert "Siu Wai Lam" not in json.dumps(bundle)

    def test_an_absent_name_stays_absent(self, conn):
        """"Nobody approved this" and "somebody did and we removed their name" are different
        facts, and the gates read the first as unapproved. Redaction must not create approval."""
        set_id = _a_tender(conn, actor="")
        meta = demo_capture.export_set(conn, set_id)["tables"]["client_boq_set_meta"][0]
        assert meta["owner_id"] == ""

    def test_an_email_address_in_a_blob_is_caught(self, conn):
        """The check that matters. A register is JSON text, so an address inside one would pass
        every rule written about column names."""
        set_id = _a_tender(conn)
        conn.execute(
            "INSERT INTO client_boq_review_registers (set_id, register_json) VALUES (?,?)",
            (set_id, json.dumps({"items": [{"note": "chased cscecdct@cohl.com about clause 12"}]})))
        conn.commit()
        bad = demo_capture.offences(demo_capture.export_set(conn, set_id))
        assert any("email address" in note and "cscecdct@cohl.com" in note for note in bad)

    def test_a_placeholder_address_is_allowed_through(self, conn):
        """A letter template reading you@example.com must not fail the sweep, or the sweep gets
        turned off."""
        set_id = _a_tender(conn)
        conn.execute("INSERT INTO client_boq_letters (set_id, letter_json) VALUES (?,?)",
                     (set_id, json.dumps({"to": "client@example.com"})))
        conn.commit()
        assert demo_capture.offences(demo_capture.export_set(conn, set_id)) == []

    def test_something_shaped_like_a_key_is_caught(self, conn):
        set_id = _a_tender(conn)
        conn.execute("INSERT INTO client_boq_letters (set_id, letter_json) VALUES (?,?)",
                     (set_id, json.dumps({"note": "key sk-ant-api03-AbCdEfGhIjKlMnOp"})))
        conn.commit()
        bad = demo_capture.offences(demo_capture.export_set(conn, set_id))
        assert any("API key" in note for note in bad)

    def test_a_google_token_is_caught(self, conn):
        set_id = _a_tender(conn)
        conn.execute("INSERT INTO client_boq_letters (set_id, letter_json) VALUES (?,?)",
                     (set_id, json.dumps({"t": "ya29.A0ARrdaM-longtokenvalue", "x": 1})))
        conn.commit()
        assert any("OAuth" in n for n in
                   demo_capture.offences(demo_capture.export_set(conn, set_id)))

    def test_a_clean_capture_reports_nothing(self, conn):
        set_id = _a_tender(conn)
        assert demo_capture.offences(demo_capture.export_set(conn, set_id)) == []

    def test_the_sweep_is_not_vacuous(self):
        """A check that cannot fail passes for the wrong reason."""
        assert demo_capture.offences(
            {"tables": {"x": [{"v": "someone@a-real-firm.com.hk"}]}})


class TestLoadingIsGatedOnTheMode:
    def test_it_refuses_outside_demo(self, tmp_path, monkeypatch, capsys):
        """A captured tender in the live shelf is exactly the mixing the demo/live design exists to
        prevent — and it would be silent, because the rows are perfectly valid."""
        from pipeline import llm_client

        path = tmp_path / "bundle.json"
        path.write_text(json.dumps(
            {"version": demo_capture.BUNDLE_VERSION, "set_id": "s", "tables": {}}))
        llm_client.set_demo_mode(False)
        try:
            code = demo_capture.main(["load", "--path", str(path)])
        finally:
            llm_client.set_demo_mode(None)
        assert code == 2
        assert "refusing" in capsys.readouterr().err

    def test_a_missing_capture_says_where_it_looked(self, tmp_path, monkeypatch, capsys):
        from pipeline import llm_client

        llm_client.set_demo_mode(True)
        try:
            code = demo_capture.main(["load", "--path", str(tmp_path / "nothing.json")])
        finally:
            llm_client.set_demo_mode(None)
        assert code == 1
        err = capsys.readouterr().err
        assert "no capture at" in err and "export" in err

    def test_export_refuses_to_write_something_unsafe(self, tmp_path, monkeypatch, capsys):
        """The refusal is at WRITE time, so an unsafe capture never reaches a file somebody might
        commit without looking."""
        db = tmp_path / "live.db"
        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("SITESOURCE_DB", str(db))
        conn = sqlite3.connect(str(db))
        models.init_tables(conn)
        _a_tender(conn)
        conn.execute("INSERT INTO client_boq_letters (set_id, letter_json) VALUES (?,?)",
                     ("nd-2025-04", json.dumps({"to": "buyer@a-real-firm.com.hk"})))
        conn.commit()
        conn.close()

        out = tmp_path / "demo_tender.json"
        code = demo_capture.main(
            ["export", "--set-id", "nd-2025-04", "--out", str(out)])
        assert code == 2
        assert not out.exists(), "an unsafe capture reached a file"
        assert "must not ship" in capsys.readouterr().err

    def test_an_unknown_set_says_so_rather_than_writing_an_empty_bundle(
            self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "live.db"
        sqlite3.connect(str(db)).close()
        conn = sqlite3.connect(str(db))
        models.init_tables(conn)
        conn.close()
        monkeypatch.setenv("SITESOURCE_DB", str(db))
        out = tmp_path / "demo_tender.json"
        assert demo_capture.main(["export", "--set-id", "not-a-set", "--out", str(out)]) == 1
        assert not out.exists()
        assert "no rows for set" in capsys.readouterr().err
