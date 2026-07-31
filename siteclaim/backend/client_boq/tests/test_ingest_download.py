"""Spec for T1 (download the split as folders) and T2 (list the tenders).

T1 is the deliverable a user uploads a binder to get back: the partitioned folder tree, with a
readable context card beside each cut PDF. T2 is the one call a dashboard opens on.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip("fitz")  # PyMuPDF


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _binder(pages: int = 12) -> bytes:
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


def _ingest(client: TestClient, name: str = "download-demo") -> str:
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": name},
        files={"files": ("binder.pdf", _binder(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    return set_id


# ---------------------------------------------------------------------------
# T1 — download the split
# ---------------------------------------------------------------------------
def test_the_archive_mirrors_the_folder_per_part_layout(client):
    set_id = _ingest(client)

    resp = client.get(f"/client-boq/ingest/{set_id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert f"{set_id}-split.zip" in resp.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = archive.namelist()
        assert "README.md" in names
        assert "split-manifest.json" in names

        parts = client.get(f"/client-boq/ingest/parts/{set_id}").json()["parts"]
        # One folder per part, each holding its cut PDF and its context card.
        for part in parts:
            folder = f"{part['n']:02d}_{part['abbr'].upper()}"
            in_folder = [n for n in names if n.startswith(f"{folder}/")]
            assert any(n.endswith(".pdf") for n in in_folder), f"{folder} has no PDF"
            assert f"{folder}/context.md" in in_folder


def test_the_pdfs_inside_the_archive_are_real_and_keep_their_page_counts(client):
    set_id = _ingest(client)
    parts = {p["part_id"]: p for p in client.get(f"/client-boq/ingest/parts/{set_id}").json()["parts"]}

    resp = client.get(f"/client-boq/ingest/{set_id}/download")
    total = 0
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        pdfs = [n for n in archive.namelist() if n.endswith(".pdf")]
        assert len(pdfs) == len(parts)
        for name in pdfs:
            with fitz.open(stream=archive.read(name), filetype="pdf") as doc:
                total += len(doc)
    assert total == 12  # every page of the source survives the round trip


def test_the_readme_states_the_page_arithmetic(client):
    set_id = _ingest(client)
    resp = client.get(f"/client-boq/ingest/{set_id}/download")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        readme = archive.read("README.md").decode("utf-8")
        manifest = json.loads(archive.read("split-manifest.json"))

    assert "Coverage: 12 of 12 pages" in readme
    assert "Confidence tier" in readme
    for part in manifest["parts"]:
        assert part["title"] in readme          # every part is listed
        assert f"{part['start']}-{part['end']}" in readme


def test_the_source_upload_is_excluded_by_default_and_included_on_request(client):
    set_id = _ingest(client)

    without = client.get(f"/client-boq/ingest/{set_id}/download")
    with zipfile.ZipFile(io.BytesIO(without.content)) as archive:
        assert not [n for n in archive.namelist() if n.startswith("source/")]

    with_source = client.get(f"/client-boq/ingest/{set_id}/download?include_source=true")
    with zipfile.ZipFile(io.BytesIO(with_source.content)) as archive:
        assert "source/binder.pdf" in archive.namelist()
    assert len(with_source.content) > len(without.content)


def test_an_unreadable_part_carries_an_honest_card_into_the_archive(client):
    doc = fitz.open()
    for _ in range(4):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
    scanned = doc.tobytes()
    doc.close()

    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": "scanned-set"},
        files={"files": ("scan.pdf", scanned, "application/pdf")},
    )
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})

    resp = client.get(f"/client-boq/ingest/{set_id}/download")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        cards = [n for n in archive.namelist() if n.endswith("context.md")]
        assert cards
        body = archive.read(cards[0]).decode("utf-8")
    # The card says it could not be read, rather than carrying invented content.
    assert "readable: false" in body and "Not read" in body


def test_downloading_a_set_that_was_never_split_404s(client):
    assert client.get("/client-boq/ingest/nope/download").status_code == 404

    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": "unsplit"},
        files={"files": ("binder.pdf", _binder(), "application/pdf")},
    )
    set_id = resp.json()["result"]["set_id"]
    # Inspected but never approved or split: there is nothing to package yet.
    assert client.get(f"/client-boq/ingest/{set_id}/download").status_code == 404


# ---------------------------------------------------------------------------
# T2 — list the tenders
# ---------------------------------------------------------------------------
def test_an_empty_installation_lists_nothing(client):
    body = client.get("/client-boq/sets").json()
    assert body == {"count": 0, "sets": []}


def test_a_set_appears_with_its_part_count_and_gate_states(client):
    set_id = _ingest(client)

    body = client.get("/client-boq/sets").json()
    assert body["count"] == 1
    row = body["sets"][0]

    assert row["set_id"] == set_id
    assert row["name"] == "download-demo"
    assert row["parts"] == 3
    assert row["tier"] in {1, 2, 3, 4}
    # Split, but nothing downstream has been signed off yet.
    assert row["gates"] == {"manifest": True, "review": False, "scope": False}
    assert row["price"] is None


def test_the_gates_track_the_workflow_forward(client):
    set_id = _ingest(client)

    def gates() -> dict:
        return client.get("/client-boq/sets").json()["sets"][0]["gates"]

    client.post("/client-boq/review/run", data={"project_name": "download-demo", "set_id": set_id})
    assert gates() == {"manifest": True, "review": False, "scope": False}

    client.post("/client-boq/review/approve",
                json={"set_id": set_id, "decisions": {}, "approved": True})
    assert gates() == {"manifest": True, "review": True, "scope": False}

    client.post("/client-boq/estimate/scope", json={"set_id": set_id})
    client.post("/client-boq/estimate/scope/approve", json={"set_id": set_id, "approved": True})
    assert gates() == {"manifest": True, "review": True, "scope": True}


def test_a_priced_set_reports_its_price_in_the_list(client):
    set_id = _ingest(client)
    client.post("/client-boq/review/run", data={"project_name": "download-demo", "set_id": set_id})
    client.post("/client-boq/review/approve",
                json={"set_id": set_id, "decisions": {}, "approved": True})
    client.post("/client-boq/estimate/scope", json={"set_id": set_id})
    client.post("/client-boq/estimate/scope/approve", json={"set_id": set_id, "approved": True})
    client.post("/client-boq/estimate/run", json={"set_id": set_id})

    row = client.get("/client-boq/sets").json()["sets"][0]
    persisted = client.get(f"/client-boq/estimate/{set_id}").json()["totals"]["price"]
    assert row["price"] == persisted  # the list figure is the estimate's, not a recomputation


def test_several_sets_are_listed_newest_first(client):
    for name in ("alpha-set", "beta-set", "gamma-set"):
        _ingest(client, name)

    body = client.get("/client-boq/sets").json()
    assert body["count"] == 3
    assert {row["set_id"] for row in body["sets"]} == {"alpha-set", "beta-set", "gamma-set"}
    created = [row["created_at"] for row in body["sets"]]
    assert created == sorted(created, reverse=True)


def test_the_new_routes_are_mounted(client):
    paths = set(client.app.openapi()["paths"])  # openapi(), not app.routes — CLAUDE.md trap 1
    assert {"/client-boq/sets", "/client-boq/ingest/{set_id}/download"} <= paths
