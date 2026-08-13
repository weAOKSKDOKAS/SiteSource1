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
            {"version": demo_capture.BUNDLE_VERSION, "set_id": "s", "tables": {}}),
            encoding="utf-8")
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
        commit without looking.

        RE-ANCHORED 2026-08-12, disclosed. This used an email address as its unsafe payload, and an
        address is now REDACTED rather than refused — the first real export found one printed in
        the tender pack itself, where "remove it at source" would have meant editing the documents.
        So the payload is a credential, which redaction deliberately does not touch: an address can
        appear innocently in a tender and a key cannot appear innocently anywhere. The redact-then-
        refuse behaviour is pinned by TestTheSweepStillRunsAfterRedaction.
        """
        db = tmp_path / "live.db"
        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("SITESOURCE_DB", str(db))
        conn = sqlite3.connect(str(db))
        models.init_tables(conn)
        _a_tender(conn)
        conn.execute("INSERT INTO client_boq_letters (set_id, letter_json) VALUES (?,?)",
                     ("nd-2025-04", json.dumps({"n": "sk-ant-api03-AbCdEfGhIjKlMnOpQr"})))
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


class TestAnAddressPrintedInTheTenderIsRedactedNotRefused:
    """The first real export refused, and "remove it at source" did not apply.

    `ce19.aecom-atkinsrealis.jv@aecom.com` is PRINTED IN THE PACK — the consultant's address block
    on the Letter of Undertaking in `SCT/I-ND_2025_04-SCT_APP-0.pdf` — and reached
    `client_boq_review_registers` as part of the clause text that was read. It is document content,
    not operational data, so editing the tender to satisfy an export would damage the one property
    the capture exists for: being the real run.

    Two constraints, both tested below: the redaction touches the ADDRESS and not the clause around
    it, and the refusal sweep still runs AFTERWARDS so anything redaction did not handle still
    stops the export.
    """

    REAL = "ce19.aecom-atkinsrealis.jv@aecom.com"

    def _register(self, conn, text, set_id="nd-2025-04"):
        conn.execute(
            "INSERT INTO client_boq_review_registers (set_id, register_json) VALUES (?,?)",
            (set_id, json.dumps({"items": [{"cited_text": text}]})))
        conn.commit()
        return demo_capture.export_set(conn, set_id)

    def _text_back(self, bundle):
        row = bundle["tables"]["client_boq_review_registers"][0]["register_json"]
        return json.loads(row)["items"][0]["cited_text"]

    def test_the_address_goes(self, conn):
        _a_tender(conn)
        bundle = self._register(conn, f"Address the Undertaking to {self.REAL} before tender close.")
        out, report = demo_capture.redact_addresses(bundle)
        assert self.REAL not in json.dumps(out)
        assert report["emails"] == 1
        assert report["addresses"] == [self.REAL]

    def test_the_clause_stays(self, conn):
        """The words either side, and the punctuation. Redaction is a substitution, not a cut."""
        _a_tender(conn)
        sentence = f"Address the Undertaking to {self.REAL}. Clause 12 then applies."
        out, _ = demo_capture.redact_addresses(self._register(conn, sentence))
        assert self._text_back(out) == (
            "Address the Undertaking to [email redacted]. Clause 12 then applies.")

    def test_the_full_stop_is_not_eaten(self, conn):
        """The defect this was written against. The pattern's tail was `[\\w.]+`, which is greedy
        over dots, so the match ran to "…@aecom.com." and substituting took the sentence's full
        stop with it — cutting the clause, which is the thing that must not happen."""
        _a_tender(conn)
        out, _ = demo_capture.redact_addresses(
            self._register(conn, f"Write to {self.REAL}. Then wait."))
        assert self._text_back(out).endswith("[email redacted]. Then wait.")

    def test_several_addresses_in_one_clause_all_go_and_are_counted(self, conn):
        _a_tender(conn)
        out, report = demo_capture.redact_addresses(self._register(
            conn, f"Copy {self.REAL} and also qs.dept@some-consultant.com.hk on every notice."))
        assert "@" not in self._text_back(out)
        assert report["emails"] == 2
        assert self._text_back(out) == (
            "Copy [email redacted] and also [email redacted] on every notice.")

    def test_a_placeholder_address_is_left_exactly_as_printed(self, conn):
        """One rule for what counts as a real address, shared by the redactor and the sweep — so a
        letter template reading you@example.com is neither redacted nor refused."""
        _a_tender(conn)
        out, report = demo_capture.redact_addresses(
            self._register(conn, "Send to client@example.com for the demo."))
        assert self._text_back(out) == "Send to client@example.com for the demo."
        assert report["emails"] == 0

    def test_the_bundle_says_it_was_redacted(self, conn):
        """Not silent in the FILE either. Somebody opening the JSON a year from now should be able
        to tell it was processed without knowing this tool exists."""
        _a_tender(conn)
        out, _ = demo_capture.redact_addresses(self._register(conn, f"To {self.REAL}."))
        assert out["redactions"]["emails"] == 1
        assert out["redactions"]["by_table"] == {"client_boq_review_registers": 1}
        assert "clause is untouched" in out["redactions"]["note"]

    def test_a_clean_capture_gains_no_note(self, conn):
        """An unconditional note would make every capture look like it had something removed."""
        _a_tender(conn)
        out, report = demo_capture.redact_addresses(demo_capture.export_set(conn, "nd-2025-04"))
        assert "redactions" not in out and report["emails"] == 0

    def test_the_redacted_bundle_still_loads(self, conn, tmp_path):
        """`load_bundle` must ignore the note rather than choke on an unknown top-level key."""
        _a_tender(conn)
        out, _ = demo_capture.redact_addresses(self._register(conn, f"To {self.REAL}."))
        other = sqlite3.connect(str(tmp_path / "replay.db"))
        try:
            demo_capture.load_bundle(other, out)
            got = other.execute(
                "SELECT register_json FROM client_boq_review_registers").fetchone()[0]
        finally:
            other.close()
        assert "[email redacted]" in got


class TestTheSweepStillRunsAfterRedaction:
    def test_a_redacted_capture_passes_the_sweep(self, conn):
        _a_tender(conn)
        conn.execute(
            "INSERT INTO client_boq_review_registers (set_id, register_json) VALUES (?,?)",
            ("nd-2025-04", json.dumps({"t": "to ce19.aecom-atkinsrealis.jv@aecom.com now"})))
        conn.commit()
        raw = demo_capture.export_set(conn, "nd-2025-04")
        assert demo_capture.offences(raw), "the unredacted capture should still be refused"
        out, _ = demo_capture.redact_addresses(raw)
        assert demo_capture.offences(out) == []

    def test_a_key_is_still_refused_after_redaction(self, conn):
        """Redaction handles addresses ONLY. A credential cannot appear innocently in a tender, so
        masking one would hide a real problem rather than solve it."""
        _a_tender(conn)
        conn.execute("INSERT INTO client_boq_letters (set_id, letter_json) VALUES (?,?)",
                     ("nd-2025-04", json.dumps({"n": "key sk-ant-api03-AbCdEfGhIjKlMnOp"})))
        conn.commit()
        out, _ = demo_capture.redact_addresses(demo_capture.export_set(conn, "nd-2025-04"))
        assert any("API key" in n for n in demo_capture.offences(out))

    def test_the_cli_redacts_then_sweeps_and_says_how_many(self, tmp_path, monkeypatch, capsys):
        """The order end to end, through the command an operator actually runs."""
        db = tmp_path / "live.db"
        sqlite3.connect(str(db)).close()
        conn = sqlite3.connect(str(db))
        models.init_tables(conn)
        _a_tender(conn)
        conn.execute(
            "INSERT INTO client_boq_review_registers (set_id, register_json) VALUES (?,?)",
            ("nd-2025-04", json.dumps({"t": "to ce19.aecom-atkinsrealis.jv@aecom.com before close"})))
        conn.commit()
        conn.close()
        monkeypatch.setenv("SITESOURCE_DB", str(db))

        out = tmp_path / "demo_tender.json"
        assert demo_capture.main(["export", "--set-id", "nd-2025-04", "--out", str(out)]) == 0
        printed = capsys.readouterr().out
        assert "redacted 1 email address" in printed
        assert "ce19.aecom-atkinsrealis.jv@aecom.com" in printed, "it must say WHAT it removed"
        written = json.loads(out.read_text(encoding="utf-8"))
        assert "aecom.com" not in json.dumps(written)
        assert "before close" in json.dumps(written), "the clause survived"

    def test_the_cli_still_refuses_what_redaction_does_not_handle(
            self, tmp_path, monkeypatch, capsys):
        db = tmp_path / "live.db"
        sqlite3.connect(str(db)).close()
        conn = sqlite3.connect(str(db))
        models.init_tables(conn)
        _a_tender(conn)
        conn.execute("INSERT INTO client_boq_letters (set_id, letter_json) VALUES (?,?)",
                     ("nd-2025-04", json.dumps({"n": "ya29.A0ARrdaM-longtokenvalue"})))
        conn.commit()
        conn.close()
        monkeypatch.setenv("SITESOURCE_DB", str(db))

        out = tmp_path / "demo_tender.json"
        assert demo_capture.main(["export", "--set-id", "nd-2025-04", "--out", str(out)]) == 2
        assert not out.exists()
        err = capsys.readouterr().err
        assert "OAuth" in err
        assert "redacted automatically" in err, "it must not still say 'remove it at source'"
