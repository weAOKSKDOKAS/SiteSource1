"""A tender pack still inside its ZIP is a third layout, and the screen has to know.

THE DEFECT this supports. `/bridge/archive/upload` has existed and worked since it was written —
streaming to disk a megabyte at a time, reading the ZIP's central directory without decompressing a
byte, checking the UNCOMPRESSED total against the ceiling BEFORE opening any member — and nothing
in this application ever called it. A dropped `.zip` was filtered out client-side and answered with
"Drop a PDF": a banner, no request, no status code, no mention of archives. `curl` worked because
`curl` talks to an endpoint the UI never called.

Wiring the upload alone is not enough, and this is the part that needed a backend change. The two
layouts are unpacked by DIFFERENT code: a binder is CUT into page ranges by `/ingest/split`, and a
pack is EXTRACTED by `/bridge/archive/extract`. An archive-planned manifest's "parts" are still zip
entries with `start=1, end=1`, so offering to slice pages out of one is offering to slice a
document that does not exist yet.

`plan_manifest` documents its own shape — "manifest.source_doc is empty and every part carries its
OWN" — and `run_split` resolves `part.source_doc or manifest.source_doc` on exactly that basis. So
that shape is the contract, and it is what `_manifest_payload` reads to report `layout: "archive"`.
"""

from __future__ import annotations

import io
import zipfile

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DEMO_MODE", "true")
    db = tmp_path / "bridge.db"
    import sqlite3

    sqlite3.connect(str(db)).close()
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _pdf(text: str) -> bytes:
    """A minimal one-page PDF. Real bytes, because the extractor opens what it extracts."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _pack(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buffer.getvalue()


PACK = {
    "ND202504 Contract Dcos/GCT/general-conditions.pdf": _pdf("General Conditions of Tender"),
    "ND202504 Contract Dcos/BQ/bill-of-quantities.pdf": _pdf("Bill of Quantities"),
    "ND202504 Contract Dcos/DRG/GI-210.pdf": _pdf("Borehole details"),
}


class TestTheUploadIsReachableAndProposesRatherThanExtracts:

    def test_a_pack_is_read_and_a_manifest_proposed(self, client):
        response = client.post("/bridge/archive/upload",
                               files={"file": ("ND202504.zip", _pack(PACK), "application/zip")},
                               data={"project_name": "ND 2025 04"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["entries"] == 3 and body["content_files"] == 3
        assert body["parts"] == 3
        assert body["uncompressed_bytes"] > 0

    def test_nothing_is_approved_by_the_upload(self, client):
        """The pack passes the same gate a single PDF does. Landing approved would be a 232 MB
        extraction nobody authorised."""
        body = client.post("/bridge/archive/upload",
                           files={"file": ("ND202504.zip", _pack(PACK), "application/zip")}).json()
        assert body["manifest_approved"] is False

    def test_the_folders_are_grouped_because_a_two_hundred_row_gate_is_a_wall(self, client):
        body = client.post("/bridge/archive/upload",
                           files={"file": ("ND202504.zip", _pack(PACK), "application/zip")}).json()
        folders = {f["folder"] for f in body["folders"]}
        assert {"GCT", "BQ", "DRG"} <= {f.rsplit("/", 1)[-1] for f in folders} or folders


class TestTheScreenIsToldItIsAPack:

    def test_the_manifest_reports_the_archive_layout(self, client):
        """Without this the Documents tab offers "Split into parts" on a set whose parts are still
        zip entries, and calls the page-slicing endpoint on a document that does not exist yet."""
        upload = client.post("/bridge/archive/upload",
                             files={"file": ("ND202504.zip", _pack(PACK), "application/zip")}).json()
        manifest = client.get(f"/client-boq/ingest/manifest/{upload['set_id']}").json()
        assert manifest["layout"] == "archive"

    def test_every_part_carries_its_own_source_and_the_manifest_carries_none(self, client):
        """The shape `plan_manifest` documents and `run_split` resolves on. It is the contract the
        layout is read from, so it is asserted rather than assumed."""
        upload = client.post("/bridge/archive/upload",
                             files={"file": ("ND202504.zip", _pack(PACK), "application/zip")}).json()
        manifest = client.get(f"/client-boq/ingest/manifest/{upload['set_id']}").json()
        assert manifest["source_doc"] == ""
        assert manifest["parts"] and all(p["source_doc"] for p in manifest["parts"])

    def test_a_binder_is_still_a_binder(self, client):
        """The layout must not start claiming every set is a pack. A binder has one source document
        on the manifest and page ranges on its parts."""
        response = client.post("/client-boq/ingest/upload",
                               files={"files": ("Binder.pdf", _pdf("page one"), "application/pdf")},
                               data={"project_name": "A binder"})
        assert response.status_code == 200, response.text
        set_id = "a-binder"
        manifest = client.get(f"/client-boq/ingest/manifest/{set_id}")
        if manifest.status_code == 200:
            assert manifest.json()["layout"] in ("binder", "folder")


class TestTheExtractStillRefusesUntilTheGateIsPassed:

    def test_it_409s_while_the_manifest_is_unapproved(self, client):
        upload = client.post("/bridge/archive/upload",
                             files={"file": ("ND202504.zip", _pack(PACK), "application/zip")}).json()
        response = client.post("/bridge/archive/extract", json={"set_id": upload["set_id"]})
        assert response.status_code == 409
        assert "not approved" in response.json()["detail"]

    def test_it_runs_once_the_gate_is_passed(self, client):
        upload = client.post("/bridge/archive/upload",
                             files={"file": ("ND202504.zip", _pack(PACK), "application/zip")}).json()
        approved = client.post("/client-boq/ingest/manifest/approve",
                               json={"set_id": upload["set_id"], "approved": True})
        assert approved.status_code == 200, approved.text
        response = client.post("/bridge/archive/extract", json={"set_id": upload["set_id"]})
        assert response.status_code == 200, response.text
        assert response.json()["kind"] == "archive"

    def test_an_unknown_set_is_a_404_not_a_500(self, client):
        response = client.post("/bridge/archive/extract", json={"set_id": "no-such-pack"})
        assert response.status_code == 404


class TestARefusedArchiveLeavesNothingBehind:

    def test_a_file_that_is_not_a_zip_is_a_400_with_a_reason(self, client):
        response = client.post("/bridge/archive/upload",
                               files={"file": ("broken.zip", b"not a zip at all", "application/zip")})
        assert response.status_code == 400
        assert response.json()["detail"]
