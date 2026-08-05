"""Uploading a folder that is already organised.

The rule these defend: **the client's own folder tree is information, and the app must not throw it
away.** A tender package arrives sorted — `ND202504 / TA #2 / BQ / bill.xlsx` and forty siblings.
Somebody already did the splitting; re-doing it would be work done twice and worse, because the app
would replace a real organisation with an inferred one.

Three specific failures these pin:

* **Two files of the same name in different folders.** `save_upload` flattens to a basename, so
  `TA #1/BQ/BQ.pdf` and `TA #2/BQ/BQ.pdf` both became `docs/BQ.pdf` — the addendum's bill silently
  overwriting the original. That one loses a document rather than merely looking wrong.
* **Re-cutting a file that was never joined.** A part spanning a whole PDF used to be sliced anyway,
  round-tripping untouched bytes through PyMuPDF.
* **Non-PDFs disappearing.** A workbook was written to disk and then absent from everything on
  screen. A file may be un-read; it may not be un-mentioned.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip("fitz")

from client_boq import store
from client_boq.ingest import folder as folder_mod
from client_boq.ingest import run as ingest_run
from client_boq.ingest.folder import FolderUpload, plan_folder
from client_boq.tests._bqfixture import build_bill_workbook
from pathlib import Path

from pipeline.workspace import Workspace

BASE = "/client-boq"


def _pdf(pages: int = 3, text: str = "page") -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        doc.new_page().insert_text((72, 100), f"{text} {i}", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _up(path: str, data: bytes = b"", content_type: str = "") -> FolderUpload:
    return FolderUpload(relative_path=path, content_type=content_type, data=data or _pdf())


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestThePlan:
    def test_every_pdf_becomes_its_own_part(self):
        plan = plan_folder([
            _up("ND202504/BQ/bill.pdf"),
            _up("ND202504/DRG/GI-210.pdf"),
            _up("ND202504/PS/spec.pdf"),
        ], set_id="nd-2025-04")
        assert len(plan.manifest.parts) == 3

    def test_a_part_spans_its_whole_file_and_points_at_it(self):
        plan = plan_folder([_up("TA #2/BQ/bill.pdf", _pdf(7))], set_id="s")
        part = plan.manifest.parts[0]
        assert part.start == 1 and part.end == 7
        assert part.source_doc == "TA #2/BQ/bill.pdf"

    def test_the_path_is_the_title_so_the_screen_reads_like_the_folder(self):
        plan = plan_folder([_up("ND202504/TA #2/BQ/bill.pdf")], set_id="s")
        assert plan.manifest.parts[0].title == "ND202504/TA #2/BQ/bill.pdf"

    def test_parts_are_ordered_by_path(self):
        plan = plan_folder([
            _up("z-last/doc.pdf"), _up("a-first/doc.pdf"), _up("m-middle/doc.pdf"),
        ], set_id="s")
        assert [p.title for p in plan.manifest.parts] == [
            "a-first/doc.pdf", "m-middle/doc.pdf", "z-last/doc.pdf"]

    def test_two_files_of_one_name_get_distinct_ids(self):
        # `part_id` is built from the slug. Two parts sharing an id would have the second overwrite
        # the first in the parts table — the same loss as the filesystem collision, one layer down.
        plan = plan_folder([
            _up("TA #1/BQ/BQ.pdf"), _up("TA #2/BQ/BQ.pdf"),
        ], set_id="s")
        ids = [p.part_id for p in plan.manifest.parts]
        assert len(set(ids)) == 2, ids

    def test_there_is_no_binder_so_coverage_is_not_claimed(self):
        plan = plan_folder([_up("a/doc.pdf")], set_id="s")
        assert plan.manifest.source_doc == "" and plan.manifest.pages == 0

    def test_it_arrives_approved_and_says_that_was_automatic(self):
        plan = plan_folder([_up("a/doc.pdf")], set_id="s")
        assert plan.manifest.approved is True
        assert plan.manifest.tier == folder_mod.TIER_FOLDER
        assert "nothing was split" in plan.manifest.tier_reason

    def test_a_category_is_proposed_from_the_path(self):
        plan = plan_folder([
            _up("ND202504/DRG/GI-210.pdf"), _up("ND202504/BQ/bill.pdf"),
            _up("ND202504/misc/notes.pdf"),
        ], set_id="s")
        by_title = {p.title: p.category for p in plan.manifest.parts}
        assert by_title["ND202504/DRG/GI-210.pdf"] == "drawings"
        assert by_title["ND202504/BQ/bill.pdf"] == "pricing"
        # "other" is an honest answer — a wrong category is worse than none, because the
        # downstream prompts address the category rather than the title.
        assert by_title["ND202504/misc/notes.pdf"] == "other"

    def test_an_empty_folder_says_so(self):
        assert "empty" in " ".join(plan_folder([], set_id="s").problems)


class TestThingsTheRealPackageTaught:
    """Both of these looked fine against invented fixtures and were wrong on 441 real files."""

    def test_the_tag_comes_from_the_folder_not_the_filename(self):
        # Every file on the reference package is named `I-ND_2025_04-…`, so initials of the
        # FILENAME gave "IN20" for all 203 parts and every folder on disk read `NN_IN20`.
        plan = plan_folder([
            _up("ND202504 Contract Dcos/ACC/I-ND_2025_04-ACC-0.pdf"),
            _up("ND202504 Contract Dcos/DRG/I-ND_2025_04-DRG-0.pdf"),
            _up("ND202504 Contract Dcos/S/PS/PS25/I-ND_2025_04-S_PS25-0.pdf"),
        ], set_id="s")
        assert [p.abbr for p in plan.manifest.parts] == ["ACC", "DRG", "PS25"]
        assert [p.part_id for p in plan.manifest.parts] == ["01-acc", "02-drg", "03-ps25"]

    def test_the_tag_is_the_folder_verbatim_not_its_initials(self):
        # `abbreviate` takes initials of words, so a one-word folder gives one letter — and "ACC"
        # and "AoA" would then both be "A".
        plan = plan_folder([_up("pkg/ACC/a.pdf"), _up("pkg/AoA/b.pdf")], set_id="s")
        assert [p.abbr for p in plan.manifest.parts] == ["ACC", "AOA"]

    def test_a_detached_signature_is_counted_as_proof_not_listed_as_unread(self):
        # 201 of the 441 real files are `.p7s` — one per PDF. Calling them "held, not read" is
        # wrong (they are evidence the PDF is authentic) and loud enough to bury the 34 that are.
        plan = plan_folder([
            _up("pkg/BQ/bill.pdf"),
            _up("pkg/BQ/bill.pdf.p7s", b"signature bytes"),
            _up("pkg/BQ/log.txt", b"a download log"),
        ], set_id="s")
        assert plan.signed == 1
        assert [h.suffix for h in plan.held] == [".txt"]
        assert "1 digitally signed" in plan.summary()

    def test_a_signature_for_a_file_that_is_not_here_stays_on_the_held_list(self):
        # It signs something absent, which is worth somebody noticing rather than counting away.
        plan = plan_folder([
            _up("pkg/BQ/bill.pdf"),
            _up("pkg/BQ/missing.pdf.p7s", b"signature for a file nobody sent"),
        ], set_id="s")
        assert plan.signed == 0
        assert [h.relative_path for h in plan.held] == ["pkg/BQ/missing.pdf.p7s"]


class TestNothingIsSilentlyDropped:
    def test_a_workbook_that_parses_as_a_bill_is_routed(self, tmp_path):
        path = build_bill_workbook(tmp_path / "bq.xlsx", 0)
        plan = plan_folder([
            _up("ND202504/CT/conditions.pdf"),
            _up("ND202504/BQ/E-ND_2025_04_BQ-0.xlsx", path.read_bytes()),
        ], set_id="s")
        assert len(plan.bills) == 1
        assert plan.bills[0].relative_path.endswith(".xlsx")
        assert plan.bills[0].priceable > 0
        assert plan.held == [], "a routed bill is not also 'held'"

    def test_a_workbook_that_is_not_a_bill_is_held_rather_than_guessed_at(self):
        # A filename is a weak signal; the reader either finds priceable items or it does not.
        plan = plan_folder([_up("ND202504/BQ/notes.xlsx", b"not a workbook at all")], set_id="s")
        assert plan.bills == []
        assert [h.relative_path for h in plan.held] == ["ND202504/BQ/notes.xlsx"]

    def test_everything_unreadable_is_listed_with_its_reason(self):
        plan = plan_folder([
            _up("a/letter.docx", b"docx bytes"),
            _up("a/photo.jpg", b"jpeg bytes"),
        ], set_id="s")
        assert {h.suffix for h in plan.held} == {".docx", ".jpg"}
        assert all("held, not read" in h.note for h in plan.held)
        assert all(h.bytes > 0 for h in plan.held)

    def test_two_candidate_bills_are_not_guessed_between(self, tmp_path):
        rev0 = build_bill_workbook(tmp_path / "bq0.xlsx", 0).read_bytes()
        rev2 = build_bill_workbook(tmp_path / "bq2.xlsx", 2).read_bytes()
        plan = plan_folder([
            _up("TA #1/BQ/bill.xlsx", rev0), _up("TA #2/BQ/bill.xlsx", rev2),
        ], set_id="s")
        assert len(plan.bills) == 2
        # Which revision is operative is a decision, and the app does not make it.
        assert any("decision" in p for p in plan.problems)

    def test_the_summary_counts_files_rather_than_pages_of_a_binder(self, tmp_path):
        path = build_bill_workbook(tmp_path / "bq.xlsx", 0)
        plan = plan_folder([
            _up("a/one.pdf", _pdf(4)), _up("a/two.pdf", _pdf(6)),
            _up("a/bill.xlsx", path.read_bytes()), _up("a/photo.jpg", b"x"),
        ], set_id="s")
        summary = plan.summary()
        assert "2 files" in summary and "10 pages" in summary
        assert "bill of quantities" in summary and "1 held, not read" in summary

    def test_a_folder_of_no_pdfs_still_keeps_everything(self):
        plan = plan_folder([_up("a/only.docx", b"x")], set_id="s")
        assert plan.manifest.parts == [] and len(plan.held) == 1
        assert "everything is held" in " ".join(plan.problems)


class TestTheHttpSurface:
    def _post(self, client, files, layout="folder"):
        return client.post(f"{BASE}/ingest/upload", files=files,
                           data={"project_name": "ND/2025/04", "layout": layout,
                                 "relative_paths": [f[1][0] for f in files]})

    def _finish(self, client, files):
        """Upload and wait. The folder job runs all the way to interpreted parts, so the useful
        assertions are about the END state rather than the acknowledgement."""
        body = self._post(client, files).json()
        if body.get("status") == "done":
            return body
        for _ in range(400):
            state = client.get(f"{BASE}/ingest/status/{body['job_id']}").json()
            if state["status"] in ("done", "error"):
                assert state["status"] == "done", state.get("error")
                return state
            time.sleep(0.05)
        raise AssertionError("the folder job never finished")

    def test_a_folder_ingests_with_no_gate(self, client):
        files = [("files", ("ND202504/CT/conditions.pdf", _pdf(4), "application/pdf")),
                 ("files", ("ND202504/DRG/GI-210.pdf", _pdf(2), "application/pdf"))]
        body = self._finish(client, files)
        assert body["stage"] == "ingested"
        assert body["result"]["approved"] is True
        assert body["result"]["auto_approved"] is True
        assert body["result"]["layout"] == "folder"

    def test_the_paths_survive_to_disk(self, client, tmp_path):
        files = [("files", ("TA #1/BQ/BQ.pdf", _pdf(2, "first"), "application/pdf")),
                 ("files", ("TA #2/BQ/BQ.pdf", _pdf(3, "second"), "application/pdf"))]
        self._finish(client, files)
        docs = Workspace().docs_dir("ND/2025/04")
        assert (docs / "TA #1" / "BQ" / "BQ.pdf").is_file()
        assert (docs / "TA #2" / "BQ" / "BQ.pdf").is_file()

    def test_both_same_named_files_become_parts(self, client):
        files = [("files", ("TA #1/BQ/BQ.pdf", _pdf(2), "application/pdf")),
                 ("files", ("TA #2/BQ/BQ.pdf", _pdf(3), "application/pdf"))]
        body = self._finish(client, files)
        titles = [p["title"] for p in body["result"]["parts"]]
        assert titles == ["TA #1/BQ/BQ.pdf", "TA #2/BQ/BQ.pdf"]

    def test_the_coverage_bar_does_not_claim_zero_of_zero(self, client):
        files = [("files", ("a/one.pdf", _pdf(5), "application/pdf"))]
        result = self._finish(client, files)["result"]
        assert result["file_count"] == 1 and result["file_pages"] == 5
        assert result["coverage_detail"]["gaps"] == []

    def test_a_path_that_escapes_the_workspace_is_refused(self, client):
        files = [("files", ("../../etc/passwd.pdf", _pdf(1), "application/pdf"))]
        response = self._post(client, files)
        assert response.status_code == 400
        assert "climbs above" in response.json()["detail"]

    def test_mismatched_path_count_is_refused_rather_than_misfiled(self, client):
        files = [("files", ("a/one.pdf", _pdf(1), "application/pdf")),
                 ("files", ("a/two.pdf", _pdf(1), "application/pdf"))]
        response = client.post(f"{BASE}/ingest/upload", files=files,
                               data={"project_name": "P", "layout": "folder",
                                     "relative_paths": ["a/one.pdf"]})
        assert response.status_code == 422 and "matched by position" in response.json()["detail"]

    def test_an_unknown_layout_is_refused(self, client):
        files = [("files", ("a.pdf", _pdf(1), "application/pdf"))]
        response = client.post(f"{BASE}/ingest/upload", files=files,
                               data={"project_name": "P", "layout": "sideways"})
        assert response.status_code == 422

    def test_the_binder_path_is_untouched_when_layout_is_absent(self, client):
        # Every existing test and the whole procurement side depend on this not moving.
        files = [("files", ("binder.pdf", _pdf(6), "application/pdf"))]
        body = client.post(f"{BASE}/ingest/upload", files=files,
                           data={"project_name": "P"}).json()
        assert body["stage"] == "awaiting-approval"
        assert body["result"]["approved"] is False
        assert body["result"]["layout"] == "binder"


class TestTheIngestActuallyFinishes:
    """The bug this class exists for: the folder path built a manifest of 203 parts, materialised
    none of them, and returned ``status="done"``. The set read "ingested" and was empty — which on
    screen looks like a split that went wrong rather than a step that never ran."""

    def _upload(self, client, files, project="P"):
        return client.post(f"{BASE}/ingest/upload", files=files,
                           data={"project_name": project, "layout": "folder",
                                 "relative_paths": [f[1][0] for f in files]})

    def _wait(self, client, job_id):
        for _ in range(400):
            state = client.get(f"{BASE}/ingest/status/{job_id}").json()
            if state["status"] in ("done", "error"):
                return state
            time.sleep(0.05)
        raise AssertionError("the folder job never finished")

    def test_it_returns_a_job_to_poll_not_a_false_done(self, client):
        files = [("files", ("a/one.pdf", _pdf(2), "application/pdf"))]
        body = self._upload(client, files, project="Queued").json()
        # Two hundred files of copying and interpreting is not something a request holds open,
        # and claiming "done" before any of it has happened is worse than being slow.
        assert body["job_id"] and body["status"] == "queued"
        self._wait(client, body["job_id"])   # never leave a job writing into the next test

    def test_the_parts_exist_once_the_job_finishes(self, client):
        files = [("files", ("a/one.pdf", _pdf(2), "application/pdf")),
                 ("files", ("b/two.pdf", _pdf(3), "application/pdf"))]
        job_id = self._upload(client, files, project="Parts").json()["job_id"]
        state = self._wait(client, job_id)
        assert state["status"] == "done", state.get("error")

        conn = store.get_conn()
        try:
            rows = store.load_parts(conn, "parts")
        finally:
            conn.close()
        assert len(rows) == 2, "a manifest with no parts behind it is an empty set"
        assert all(path for _spec, path, _ctx in rows), "each part should be on disk"

    def test_the_progress_counts_the_files_rather_than_sitting_on_one_word(self, client):
        # "splitting" for two hundred files is indistinguishable from a hang. The count now
        # travels as NUMBERS (`done`/`total` on the job, fed by the split/interpret loops via
        # `count_cb`), not baked into the stage string where nothing could read it as a quantity.
        # A four-file DEMO run finishes in milliseconds, so polling cannot be guaranteed to catch
        # an in-flight count — but the terminal state is deterministic: the folder job stamps
        # done=total=len(parts) when it finishes, which proves the counting plumbing end to end.
        files = [("files", (f"a/{n}.pdf", _pdf(1), "application/pdf")) for n in range(4)]
        job_id = self._upload(client, files, project="Progress").json()["job_id"]
        state: dict = {}
        for _ in range(400):
            state = client.get(f"{BASE}/ingest/status/{job_id}").json()
            if state["status"] in ("done", "error"):
                break
            time.sleep(0.02)
        assert state["status"] == "done", state
        assert state.get("total") == 4 and state.get("done") == 4, state


class TestSplittingAFolderSet:
    def test_a_whole_file_part_is_copied_byte_for_byte_not_re_encoded(self, client):
        original = _pdf(4, "original")
        files = [("files", ("a/one.pdf", original, "application/pdf"))]
        job_id = client.post(f"{BASE}/ingest/upload", files=files,
                             data={"project_name": "P", "layout": "folder",
                                   "relative_paths": ["a/one.pdf"]}).json()["job_id"]
        for _ in range(400):
            state = client.get(f"{BASE}/ingest/status/{job_id}").json()
            if state["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert state["status"] == "done", state.get("error")

        conn = store.get_conn()
        try:
            rows = store.load_parts(conn, "p")
        finally:
            conn.close()
        assert rows, "the folder set should have produced a part"
        _spec, path, _ctx = rows[0]
        assert Path(path).read_bytes() == original, (
            "slicing would re-encode an untouched PDF through PyMuPDF and lose byte-identity")


class TestPickingTheBill:
    """The gap that made a folder set unpriceable.

    `plan_folder` found the bills, refused to guess which was operative — correctly, that is a
    decision — and told the reader to "pick one on the Price step". There was nowhere to pick. The
    candidates were returned once on the upload response and the screen reloads from
    `/ingest/manifest/{set_id}`, which never carried them; the rows that were rendered had no
    action; and `/boq/import` wanted an upload of a file already on the server's disk.

    Measured on the real ND/2025/04 package: three workbooks parse as bills (162, 165 and 166
    items), all three sat on disk, and `/costing/{set_id}` answered 404 for want of a bill.
    """

    def _upload(self, client, files) -> str:
        """Ingest a folder and return the set_id the app chose for it."""
        body = client.post(f"{BASE}/ingest/upload", files=files,
                           data={"project_name": "ND/2025/04", "layout": "folder",
                                 "relative_paths": [f[1][0] for f in files]}).json()
        for _ in range(400):
            state = client.get(f"{BASE}/ingest/status/{body['job_id']}").json()
            if state["status"] in ("done", "error"):
                assert state["status"] == "done", state.get("error")
                return state["result"]["set_id"]
            time.sleep(0.05)
        raise AssertionError("folder ingest did not finish")

    def _workbook(self, tmp_path, rev: int) -> bytes:
        return build_bill_workbook(tmp_path / f"bill-{rev}.xlsx", rev=rev).read_bytes()

    def _three_bills(self, tmp_path):
        """The shape of the real package: a base bill, then one per technical addendum."""
        return [
            ("files", ("ND202504/DRG/GI-210.pdf", _pdf(2), "application/pdf")),
            ("files", ("ND202504/BQ/E-BQ-0.xlsx", self._workbook(tmp_path, 0),
                       "application/octet-stream")),
            ("files", ("ND202504/TA #1/BQ/E-BQ-1.xlsx", self._workbook(tmp_path, 1),
                       "application/octet-stream")),
            ("files", ("ND202504/TA #2/BQ/E-BQ-2.xlsx", self._workbook(tmp_path, 2),
                       "application/octet-stream")),
        ]

    def test_the_candidates_are_listed_and_the_latest_addendum_is_proposed(self, client, tmp_path):
        set_id = self._upload(client, self._three_bills(tmp_path))
        body = client.get(f"{BASE}/boq/{set_id}/candidates").json()
        assert body["count"] == 3, body

        proposed = [c for c in body["candidates"] if c["proposed"]]
        assert len(proposed) == 1, "exactly one proposal, or it is not a proposal"
        assert proposed[0]["relative_path"] == "ND202504/TA #2/BQ/E-BQ-2.xlsx"
        assert "TA #2" in proposed[0]["why"], proposed[0]["why"]
        assert all(c["priceable"] > 0 for c in body["candidates"])
        assert not any(c["already_imported"] for c in body["candidates"])

    def test_a_drawing_is_not_offered_as_a_bill(self, client):
        """"Reads as a bill" is decided by trying, never by the filename or the folder."""
        set_id = self._upload(client, [
            ("files", ("ND202504/BQ/GI-210.pdf", _pdf(2), "application/pdf")),
            ("files", ("ND202504/BQ/not-a-bill.xlsx", b"not a workbook at all",
                       "application/octet-stream")),
        ])
        assert client.get(f"{BASE}/boq/{set_id}/candidates").json()["count"] == 0

    def test_importing_by_path_prices_the_set(self, client, tmp_path):
        """The whole point: no re-upload, and the costing engine has something to work on."""
        set_id = self._upload(client, self._three_bills(tmp_path))
        assert client.get(f"{BASE}/costing/{set_id}").status_code == 404

        resp = client.post(f"{BASE}/boq/{set_id}/import-from-set",
                           json={"relative_path": "ND202504/TA #2/BQ/E-BQ-2.xlsx"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["priceable"] > 0

        assert client.get(f"{BASE}/costing/{set_id}").status_code == 200

    def test_an_imported_bill_is_marked_so_it_is_not_offered_twice(self, client, tmp_path):
        set_id = self._upload(client, self._three_bills(tmp_path))
        client.post(f"{BASE}/boq/{set_id}/import-from-set",
                    json={"relative_path": "ND202504/TA #2/BQ/E-BQ-2.xlsx"})
        body = client.get(f"{BASE}/boq/{set_id}/candidates").json()
        done = [c for c in body["candidates"] if c["already_imported"]]
        assert [c["relative_path"] for c in done] == ["ND202504/TA #2/BQ/E-BQ-2.xlsx"]

    def test_importing_by_path_and_by_upload_agree(self, client, tmp_path):
        """Two routes, one revision. If these ever differ, one of them is lying about the bill."""
        set_id = self._upload(client, self._three_bills(tmp_path))
        by_path = client.post(f"{BASE}/boq/{set_id}/import-from-set",
                              json={"relative_path": "ND202504/TA #2/BQ/E-BQ-2.xlsx"}).json()
        by_upload = client.post(
            f"{BASE}/boq/import",
            data={"set_id": set_id},
            files={"file": ("E-BQ-2.xlsx", self._workbook(tmp_path, 2),
                            "application/octet-stream")}).json()
        for field in ("items", "priceable", "pre_priced", "bills", "notes"):
            assert by_path[field] == by_upload[field], field

    def test_a_path_that_climbs_out_of_the_set_is_refused(self, client, tmp_path):
        """Refused, not trimmed — a traversal attempt is not a typo."""
        set_id = self._upload(client, self._three_bills(tmp_path))
        for attempt in ("../../../etc/passwd.xlsx", "/etc/passwd.xlsx", "C:\secrets.xlsx"):
            resp = client.post(f"{BASE}/boq/{set_id}/import-from-set",
                               json={"relative_path": attempt})
            assert resp.status_code == 422, attempt

    def test_a_path_that_is_simply_not_here_says_so(self, client, tmp_path):
        set_id = self._upload(client, self._three_bills(tmp_path))
        resp = client.post(f"{BASE}/boq/{set_id}/import-from-set",
                           json={"relative_path": "ND202504/BQ/nope.xlsx"})
        assert resp.status_code == 404
        assert "candidates" in resp.json()["detail"], "say where the list is"

    def test_the_manifest_still_carries_them_after_a_reload(self, client, tmp_path):
        """The list used to live only on the upload response — one refresh and the bills you were
        told to choose between were gone, along with the held files."""
        set_id = self._upload(client, self._three_bills(tmp_path) + [
            ("files", ("ND202504/ACC/notes.docx", b"held", "application/octet-stream")),
        ])
        body = client.get(f"{BASE}/ingest/manifest/{set_id}").json()
        assert len(body["bills"]) == 3
        assert [h["relative_path"] for h in body["held"]] == ["ND202504/ACC/notes.docx"]
        assert any("operative is a decision" in p for p in body["problems"])

    def test_a_binder_manifest_is_unchanged(self, client):
        """These keys belong to a folder set. A binder must not grow them."""
        client.post(f"{BASE}/ingest/upload", files={"files": ("binder.pdf", _pdf(9), "application/pdf")},
                    data={"project_name": "binder-set"})
        body = client.get(f"{BASE}/ingest/manifest/binder-set").json()
        assert body["layout"] == "binder"
        assert "bills" not in body and "held" not in body
