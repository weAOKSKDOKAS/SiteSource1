"""End-to-end DEMO test for the INGEST stage, exercised through the HTTP API.

Upload a real (small, synthetic) tender binder, get a draft manifest, edit and approve it at the
gate, split, and read the parts back. Asserts the things that must not regress: the gate refuses
the split until approved, an edited manifest that does not fit the document is refused, the cut
covers every page, a re-split after an edit really re-cuts, and an unreadable part is catalogued
rather than guessed at.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip("fitz")  # PyMuPDF


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    # Keep every artifact this test writes inside tmp_path, never the real workspace.
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _binder(pages: int = 12) -> bytes:
    """A synthetic tender binder with its own bookmarks — the tier 1 path."""
    doc = fitz.open()
    for i in range(1, pages + 1):
        doc.new_page().insert_text((72, 100), f"Binder page {i} of {pages}", fontsize=11)
    doc.set_toc([
        [1, "Conditions of Tender", 1],
        [1, "Scope of Works", 5],
        [1, "Pricing Schedule", 9],
    ])
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client: TestClient, name: str = "ingest-demo", data: bytes | None = None) -> dict:
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": name},
        files={"files": ("binder.pdf", data if data is not None else _binder(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]


def test_upload_returns_a_draft_manifest_and_approves_nothing(client):
    manifest = _upload(client)

    assert manifest["set_id"] == "ingest-demo"
    assert manifest["pages"] == 12
    assert manifest["approved"] is False          # the gate starts shut
    assert manifest["tier"] in {1, 2, 3, 4}
    assert manifest["tier_reason"]                # always says WHY it split that way
    assert manifest["parts"]
    assert manifest["coverage"] == 12             # every page accounted for


def test_the_manifest_gate_refuses_the_split_until_it_is_approved(client):
    _upload(client)

    resp = client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    assert resp.status_code == 409
    assert "not approved" in resp.json()["detail"]

    client.post("/client-boq/ingest/manifest/approve", json={"set_id": "ingest-demo"})
    resp = client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    assert resp.status_code == 200, resp.text


def test_the_gate_refuses_an_edited_manifest_that_does_not_fit_the_document(client):
    _upload(client)

    resp = client.post("/client-boq/ingest/manifest/approve", json={
        "set_id": "ingest-demo",
        "parts": [{"n": 1, "abbr": "X", "slug": "overrun", "title": "Overrun",
                   "start": 1, "end": 999}],
    })
    assert resp.status_code == 422
    assert "outside" in resp.json()["detail"]

    # ...and the gate stayed shut, so nothing downstream can proceed on a bad split.
    gate = client.get("/client-boq/ingest/manifest/ingest-demo").json()
    assert gate["approved"] is False


def test_a_human_edit_replaces_the_split_and_is_what_gets_cut(client):
    _upload(client)

    edited = [
        {"n": 1, "abbr": "A", "slug": "first-half", "title": "First half",
         "start": 1, "end": 6, "category": "tender-instructions"},
        {"n": 2, "abbr": "B", "slug": "second-half", "title": "Second half",
         "start": 7, "end": 12, "category": "pricing"},
    ]
    resp = client.post("/client-boq/ingest/manifest/approve",
                       json={"set_id": "ingest-demo", "parts": edited})
    assert resp.status_code == 200, resp.text
    assert resp.json()["manifest_approved"] is True
    assert resp.json()["parts"] == 2

    client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    parts = client.get("/client-boq/ingest/parts/ingest-demo").json()
    assert parts["count"] == 2
    assert [p["title"] for p in parts["parts"]] == ["First half", "Second half"]
    assert [p["category"] for p in parts["parts"]] == ["tender-instructions", "pricing"]


def test_the_split_covers_every_page_and_the_cut_pdfs_are_real(client):
    _upload(client)
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": "ingest-demo"})
    client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})

    parts = client.get("/client-boq/ingest/parts/ingest-demo").json()["parts"]
    assert sum(p["page_count"] for p in parts) == 12

    seen = 0
    for part in parts:
        detail = client.get(f"/client-boq/ingest/parts/ingest-demo/{part['part_id']}").json()
        path = detail["pdf_path"]
        assert path, f"part {part['part_id']} was not materialised"
        with fitz.open(path) as doc:
            assert len(doc) == part["page_count"]   # the cut file really holds those pages
            seen += len(doc)
    assert seen == 12


def test_resplitting_after_an_edit_re_cuts_the_parts(client):
    _upload(client)
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": "ingest-demo"})
    client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    first = client.get("/client-boq/ingest/parts/ingest-demo").json()["count"]

    client.post("/client-boq/ingest/manifest/approve", json={
        "set_id": "ingest-demo",
        "parts": [{"n": 1, "abbr": "ALL", "slug": "everything", "title": "Everything",
                   "start": 1, "end": 12}],
    })
    client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    after = client.get("/client-boq/ingest/parts/ingest-demo").json()

    assert first != 1  # the draft really did split it up
    assert after["count"] == 1  # and the stale parts are gone, not merged with the new ones
    assert after["parts"][0]["page_count"] == 12


def test_a_part_with_no_text_layer_is_catalogued_and_flagged_never_invented(client):
    doc = fitz.open()
    for _ in range(4):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
    scanned = doc.tobytes()
    doc.close()

    manifest = _upload(client, data=scanned)
    assert all(p["scanned"] for p in manifest["parts"])  # detected, not silently accepted

    client.post("/client-boq/ingest/manifest/approve", json={"set_id": "ingest-demo"})
    client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    parts = client.get("/client-boq/ingest/parts/ingest-demo").json()

    assert parts["count"] == 1          # a document we cannot read still ingests
    assert parts["parts"][0]["page_count"] == 4  # and all of its pages are accounted for

    # ...and it is reported as NOT read, with no summary invented for it. This holds in DEMO
    # too: the fixture must not be handed to a part that has no readable text, or an offline
    # demo fabricates content for a scan.
    assert parts["unreadable"] == 1
    assert parts["parts"][0]["readable"] is False
    assert parts["parts"][0]["summary"] == ""

    detail = client.get(f"/client-boq/ingest/parts/ingest-demo/{parts['parts'][0]['part_id']}").json()
    assert detail["context"]["readable"] is False
    assert detail["context"]["key_points"] == []
    assert "not been read" in detail["context"]["notes"]
    assert "Not read" in detail["card"]


def test_editing_the_manifest_does_not_clear_the_scanned_flags(client):
    # Regression: the flag is a measurement of the pages, so re-cutting must recompute it
    # rather than inherit whatever the edited part list happened to carry.
    doc = fitz.open()
    for i in range(6):
        page = doc.new_page()
        if i < 3:                                   # first three pages are scans
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
            pix.clear_with(255)
            page.insert_image(page.rect, pixmap=pix)
        else:
            # Comfortably past SCANNED_CHAR_THRESHOLD, or the page reads as a scan itself.
            page.insert_text(
                (72, 100),
                f"Page {i + 1} carries a real text layer with enough characters to be read.",
                fontsize=11,
            )
    data = doc.tobytes()
    doc.close()

    _upload(client, data=data)
    resp = client.post("/client-boq/ingest/manifest/approve", json={
        "set_id": "ingest-demo",
        # The edit carries no scanned flags at all, and splits exactly on the scan boundary.
        "parts": [
            {"n": 1, "abbr": "S", "slug": "scans", "title": "Scans", "start": 1, "end": 3},
            {"n": 2, "abbr": "T", "slug": "text", "title": "Text", "start": 4, "end": 6},
        ],
    })
    assert resp.status_code == 200, resp.text

    client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    parts = client.get("/client-boq/ingest/parts/ingest-demo").json()["parts"]
    assert [p["scanned"] for p in parts] == [True, False]


def test_a_non_pdf_upload_is_refused_with_a_useful_message(client):
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": "junk"},
        files={"files": ("notes.txt", b"just some text", "text/plain")},
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_an_empty_upload_is_refused(client):
    resp = client.post("/client-boq/ingest/upload", data={"project_name": "nothing"})
    assert resp.status_code == 422


def test_unknown_sets_and_parts_404(client):
    assert client.get("/client-boq/ingest/manifest/nope").status_code == 404
    assert client.get("/client-boq/ingest/parts/nope").status_code == 404
    _upload(client)
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": "ingest-demo"})
    client.post("/client-boq/ingest/split", json={"set_id": "ingest-demo"})
    assert client.get("/client-boq/ingest/parts/ingest-demo/99-nope").status_code == 404


def test_review_refuses_an_ingested_set_whose_manifest_is_not_approved(client):
    _upload(client)
    resp = client.post("/client-boq/review/run",
                       data={"project_name": "ingest-demo", "set_id": "ingest-demo"})
    assert resp.status_code == 409
    assert "not approved" in resp.json()["detail"]


def test_review_still_accepts_loose_files_with_no_ingested_set(client):
    # The pre-ingest path must keep working for a single document with nothing to split.
    resp = client.post(
        "/client-boq/review/run",
        data={"project_name": "loose-docs"},
        files={"files": ("subcontract.pdf", b"%PDF-1.4 demo", "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["register"]["line_items"]


def test_the_ingest_routes_are_mounted(client):
    paths = set(client.app.openapi()["paths"])  # openapi(), not app.routes — see CLAUDE.md trap 1
    assert {
        "/client-boq/ingest/upload",
        "/client-boq/ingest/status/{job_id}",
        "/client-boq/ingest/manifest/{set_id}",
        "/client-boq/ingest/manifest/approve",
        "/client-boq/ingest/split",
        "/client-boq/ingest/parts/{set_id}",
        "/client-boq/ingest/parts/{set_id}/{part_id}",
    } <= paths


# ---------------------------------------------------------------------------
# A live model's shape, not the fixture's
# ---------------------------------------------------------------------------
def test_a_prose_field_returned_as_a_list_is_joined_not_rejected():
    """The card must survive a model answering in the neighbouring shape.

    `PartContext` asks for `notes` and `summary` as prose and for six other fields as
    `list[str]`, so a model returning `notes: ["...", "..."]` has read the document correctly and
    merely picked the shape next door. Pydantic rejected it, `interpret_part` caught the
    ValidationError, and the WHOLE card was stored as "not readable" — losing the summary, the
    obligations and the commercial flags along with it.

    Measured on the first live run of the ND/2025/04 corpus through `gpt-5.6-luna`: **93 of 203
    parts** were lost this way, `01-acc` among them — a 65-page conditions of contract with a
    perfectly good text layer, catalogued as unread. It also caused 120 retries, because a
    validation failure is indistinguishable from a malformed response at the call site.
    """
    from client_boq.models import PartContext

    context = PartContext(
        summary=["The Additional Conditions of Contract.", "It amends the NEC ECC HK Edition."],
        notes=["The source description is a drawing.", "No scope is stated in the supplied text."],
    )
    assert context.summary == (
        "The Additional Conditions of Contract. It amends the NEC ECC HK Edition."
    )
    assert context.notes.startswith("The source description is a drawing.")
    assert context.readable is True, "a joined card is a read card"

    # A string is untouched, and a genuinely wrong type still fails.
    assert PartContext(notes="already prose").notes == "already prose"
    with pytest.raises(Exception):
        PartContext(notes={"not": "prose"})
