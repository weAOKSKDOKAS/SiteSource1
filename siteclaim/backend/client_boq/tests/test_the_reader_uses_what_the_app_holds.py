"""The drawing reader can see the drawings the app already has.

THE INEFFICIENCY, measured on the reference pack. The archive ingest classified `DRG/` — 35 sheets
— into parts with ``category == "drawings"`` and materialised every one on disk. And
`POST /site/schedule/read` took `files: list[UploadFile] = File(...)` and nothing else, so the Site
importer asked the operator to go find those same PDFs in a Downloads folder and upload them again,
with the read button disabled until they did. The bill already had the fix (`/boq/import-from-set`,
"uploading a file the server already has on disk is work for no reason"); this is the drawing set's
copy of it.

TWO THINGS PRESERVED, both pinned here:

* **the proposal-not-saved contract** — a from-set read stores nothing; the take-off appears only
  when a person saves the reviewed proposal, exactly as an upload read always worked;
* **the triage that finds BOTH schedule sheets** — the register's free text-layer triage runs
  identically over the set-sourced files, so it still finds GI/210 AND GI/310 rather than stopping
  at the first, and it still costs no extra model call.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fitz")

BASE = "/client-boq"
SET = "nd-2025-04"

REGISTER_TEXT = (
    "DRAWING REGISTER\n"
    "60740338/GI/000   WORKING AREA OF GROUND INVESTIGATION SHEET 1\n"
    "60740338/GI/020   WORKING AREA OF GROUND INVESTIGATION - COORDINATE\n"
    "60740338/GI/100   GENERAL NOTES AND DETAILS\n"
    "60740338/GI/210   PROPOSED SITE INVESTIGATION - COORDINATE\n"
    "60740338/GI/310   PROPOSED SITE INVESTIGATION PLAN (ENVIRONMENTAL) - COORDINATE\n"
    + "GI REGISTER CONTINUATION SHEET " * 30   # the register test wants >=500 chars of real text layer
)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _pdf(text: str = "", height: float = 842.0) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=1191, height=height)
    if text:
        y = 40
        for line in text.splitlines():
            page.insert_text((40, y), line, fontsize=10)
            y += 14
    data = doc.tobytes()
    doc.close()
    return data


def _seed_drawing_parts(tmp_path, extra=None) -> None:
    """A tender whose ingest already classified and materialised the drawing set.

    One `save_parts` call for EVERYTHING, including any `extra` specs — a second call at the same
    rev is a re-split and REPLACES the parts, which is exactly right for a manifest edit and
    exactly wrong for a test fixture that meant to append.
    """
    from client_boq import models, store

    files = {
        "DRG__60740338-GI-COVER.pdf": _pdf(REGISTER_TEXT),
        "DRG__60740338-GI-210.pdf": _pdf(),
        "DRG__60740338-GI-310.pdf": _pdf(),
        "DRG__60740338-GI-020.pdf": _pdf(),
    }
    specs, paths = [], {}
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=SET, name=SET, slug=SET, status="reviewed")
        for n, (name, data) in enumerate(sorted(files.items()), start=1):
            path = tmp_path / name
            path.write_bytes(data)
            spec = models.PartSpec(part_id=f"{n:02d}-drg", n=n, title=name,
                                   start=1, end=1, category="drawings", source_doc=name)
            specs.append(spec)
            paths[spec.part_id] = str(path)
        # And one part that is NOT a drawing, so the filter is real rather than vacuous.
        other = models.PartSpec(part_id="99-acc", n=99, title="conditions", start=1, end=9,
                                category="contract-conditions", source_doc="ACC.pdf")
        specs.append(other)
        paths[other.part_id] = str(tmp_path / "acc.pdf")
        (tmp_path / "acc.pdf").write_bytes(_pdf("conditions"))
        for spec, path in (extra or []):
            specs.append(spec)
            paths[spec.part_id] = path
        store.save_parts(conn, SET, specs, paths, rev=0)
        conn.commit()
    finally:
        conn.close()


class TestTheTenderKnowsWhatItHolds:
    def test_the_drawing_count_is_readable_before_any_read(self, client, tmp_path):
        _seed_drawing_parts(tmp_path)
        body = client.get(f"{BASE}/site/{SET}/drawings").json()
        assert body["count"] == 4
        assert "DRG__60740338-GI-210.pdf" in body["names"]
        assert "ACC.pdf" not in body["names"], "a conditions part is not a drawing"

    def test_a_tender_with_no_drawings_says_what_to_do_instead(self, client):
        body = client.get(f"{BASE}/site/{SET}/drawings").json()
        assert body["count"] == 0
        assert "upload" in body["waiting_on"]


class TestReadingFromTheSet:
    def test_no_files_means_the_tenders_own_drawings(self, client, tmp_path):
        _seed_drawing_parts(tmp_path)
        body = client.post(f"{BASE}/site/schedule/read", data={"set_id": SET}).json()
        assert body["source"] == "set"
        # THE TRIAGE STILL FINDS BOTH SHEETS — the property that must not regress. The register
        # part's text layer drove it, at no model cost, exactly as on an upload.
        numbers = [s["number"] for s in body["triage"]["sheets"]]
        assert numbers == ["GI/210", "GI/310"]
        assert body["triage"]["register"] == "DRG__60740338-GI-COVER.pdf"
        assert any("WORKING AREA" in note for note in body["triage"]["excluded"])

    def test_a_from_set_read_saves_nothing(self, client, tmp_path):
        """The proposal-not-saved contract, on the new path."""
        _seed_drawing_parts(tmp_path)
        client.post(f"{BASE}/site/schedule/read", data={"set_id": SET})
        stored = client.get(f"{BASE}/site/{SET}/schedule").json()
        assert stored["stations"] == [], "reading from the set must not write the take-off"

    def test_an_upload_still_reads_exactly_the_uploaded_files(self, client, tmp_path):
        """The fallback for a drawing that arrived outside the archive — unchanged."""
        _seed_drawing_parts(tmp_path)
        files = [("files", ("DRG__60740338-GI-210.pdf", _pdf(), "application/pdf"))]
        body = client.post(f"{BASE}/site/schedule/read", data={"set_id": SET},
                           files=files).json()
        assert body["source"] == "upload"
        # One loose sheet and no register: filename-tier triage over the UPLOAD, not the set.
        assert body["triage"]["register"] == ""

    def test_no_files_and_no_drawings_is_a_404_naming_the_way_in(self, client):
        response = client.post(f"{BASE}/site/schedule/read", data={"set_id": SET})
        assert response.status_code == 404
        assert "Upload the schedule sheets" in response.json()["detail"]

    def test_a_part_whose_file_left_the_disk_is_skipped_not_fatal(self, client, tmp_path):
        from client_boq import models

        gone = models.PartSpec(part_id="98-drg", n=98, title="gone", start=1, end=1,
                               category="drawings", source_doc="DRG__gone.pdf")
        _seed_drawing_parts(tmp_path, extra=[(gone, str(tmp_path / "not-there.pdf"))])
        body = client.post(f"{BASE}/site/schedule/read", data={"set_id": SET}).json()
        assert body["source"] == "set", "one missing file must not take the whole read down"
        assert [s["number"] for s in body["triage"]["sheets"]] == ["GI/210", "GI/310"]
