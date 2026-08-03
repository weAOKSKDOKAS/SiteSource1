"""Spec for U1/U2 — the document pane: render a page, and search inside a part.

Two rules carry the weight here and both are easy to get wrong later:

* **Page numbers are the source document's.** A part cut from page 5 of a binder is asked for
  page 5, not its own page 1, because manifest ranges, citation pages and highlight rectangles
  all speak in binder numbers. Two conventions on one screen is how a highlight lands on the
  wrong page.
* **Searching and seeing are different questions.** An image-only part renders perfectly well
  and cannot be searched at all; the endpoint says so rather than returning an empty result set
  that reads as "no matches".
"""

from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip("fitz")  # PyMuPDF


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


NEEDLE = "The Contractor shall indemnify the Employer against all claims"


def _binder(pages: int = 12) -> bytes:
    """A three-part binder whose middle part carries a distinctive sentence on one page."""
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 100), f"Binder page {i} of {pages}", fontsize=11)
        if i == 6:  # inside "Scope of Works" (pages 5-8)
            page.insert_text((72, 140), NEEDLE, fontsize=10)
    doc.set_toc([
        [1, "Conditions of Tender", 1],
        [1, "Scope of Works", 5],
        [1, "Pricing Schedule", 9],
    ])
    data = doc.tobytes()
    doc.close()
    return data


def _scanned(pages: int = 4) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def _ingest(client: TestClient, data: bytes, name: str) -> str:
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": name},
        files={"files": ("binder.pdf", data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    return set_id


def _parts(client: TestClient, set_id: str) -> list[dict]:
    return client.get(f"/client-boq/ingest/parts/{set_id}").json()["parts"]


def _png_size(data: bytes) -> tuple[int, int]:
    """Width and height straight out of the PNG IHDR — proof it is a real image."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


# ---------------------------------------------------------------------------
# Rendering a page
# ---------------------------------------------------------------------------
def test_a_page_renders_as_a_png(client):
    set_id = _ingest(client, _binder(), "viewer-demo")
    part = _parts(client, set_id)[1]              # Scope of Works, pages 5-8

    resp = client.get(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/page/6.png")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    width, height = _png_size(resp.content)
    assert width > 200 and height > 200


def test_the_page_number_is_the_source_documents_not_the_parts(client):
    """Part 2 covers binder pages 5-8. Page 1 belongs to part 1, so asking part 2 for it 404s —
    it does not quietly render part 2's own first page."""
    set_id = _ingest(client, _binder(), "viewer-numbering")
    part = _parts(client, set_id)[1]
    assert part["pages"] == "5-8"
    pid = part["part_id"]

    for page in (5, 6, 7, 8):
        assert client.get(f"/client-boq/ingest/parts/{set_id}/{pid}/page/{page}.png").status_code == 200
    for outside in (1, 4, 9, 12):
        resp = client.get(f"/client-boq/ingest/parts/{set_id}/{pid}/page/{outside}.png")
        assert resp.status_code == 404
        assert "outside part" in resp.json()["detail"]


def test_each_page_renders_its_own_content(client):
    """Different source pages must produce different images — otherwise an off-by-one in the
    part-relative conversion would go unnoticed."""
    set_id = _ingest(client, _binder(), "viewer-distinct")
    pid = _parts(client, set_id)[1]["part_id"]

    images = {p: client.get(f"/client-boq/ingest/parts/{set_id}/{pid}/page/{p}.png").content
              for p in (5, 6, 7, 8)}
    assert len(set(images.values())) == 4


def test_dpi_is_honoured_and_clamped(client):
    set_id = _ingest(client, _binder(), "viewer-dpi")
    pid = _parts(client, set_id)[0]["part_id"]
    url = f"/client-boq/ingest/parts/{set_id}/{pid}/page/1.png"

    small = _png_size(client.get(f"{url}?dpi=60").content)
    large = _png_size(client.get(f"{url}?dpi=200").content)
    assert large[0] > small[0]

    # A hostile DPI is clamped, not honoured: the query string must not be able to ask for a
    # multi-gigabyte pixmap.
    absurd = _png_size(client.get(f"{url}?dpi=4000").content)
    ceiling = _png_size(client.get(f"{url}?dpi=300").content)
    assert absurd == ceiling


def test_a_large_sheet_is_capped_by_pixel_width_not_by_dpi(client, tmp_path, monkeypatch):
    """A DPI means different things to different paper. On the reference tender the A3 drawing
    sheets rendered 1819px and 1.6MB at exactly the DPI that gives an A4 page 910px and 58KB —
    a 27x heavier response for the same request. The ceiling is on the image, not the DPI."""
    from client_boq.ingest import pdfops

    a3 = fitz.open()
    a3.new_page(width=1191, height=842)  # A3 landscape, in points
    a3_bytes = a3.tobytes()
    a3.close()

    a4 = fitz.open()
    a4.new_page(width=595, height=842)
    a4_bytes = a4.tobytes()
    a4.close()

    wide = _png_size(pdfops.render_page(a3_bytes, 1, 300))
    narrow = _png_size(pdfops.render_page(a4_bytes, 1, 110))

    assert wide[0] <= pdfops.MAX_RENDER_WIDTH_PX
    # The ordinary page is nowhere near the ceiling, so it is rendered exactly as asked.
    assert narrow[0] == pytest.approx(595 * 110 / 72, abs=2)


def test_a_scanned_part_still_renders(client):
    """It cannot be searched, but it can certainly be looked at."""
    set_id = _ingest(client, _scanned(), "viewer-scan")
    part = _parts(client, set_id)[0]
    assert part["readable"] is False

    resp = client.get(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/page/1.png")
    assert resp.status_code == 200
    assert _png_size(resp.content)[0] > 100


def test_an_unknown_part_or_set_404s(client):
    set_id = _ingest(client, _binder(), "viewer-404")
    assert client.get(f"/client-boq/ingest/parts/{set_id}/nope/page/1.png").status_code == 404
    assert client.get("/client-boq/ingest/parts/nope/nope/page/1.png").status_code == 404


# ---------------------------------------------------------------------------
# Searching inside a part
# ---------------------------------------------------------------------------
def test_search_finds_the_sentence_and_reports_the_source_page(client):
    set_id = _ingest(client, _binder(), "search-demo")
    part = _parts(client, set_id)[1]              # pages 5-8; the needle is on 6

    body = client.get(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/search",
                      params={"q": NEEDLE}).json()
    assert body["searchable"] is True
    assert body["count"] == 1
    hit = body["hits"][0]
    assert hit["page"] == 6                       # the binder's number, not the part's page 2

    box = hit["highlights"][0]
    assert box["page"] == 6
    # Fractions of the page, so a viewer can overlay them at any zoom.
    assert 0.0 <= box["x0"] < box["x1"] <= 1.0
    assert 0.0 <= box["y0"] < box["y1"] <= 1.0


def test_a_short_query_is_allowed_here_even_though_a_citation_fragment_would_not_be(client):
    """The 45-character floor in ``_search_fragments`` is a rule about *proof*: a citation
    confirmed by an accidental match is worse than one left unconfirmed. Someone typing in a
    search box is making no claim, so the floor must not apply — applying it would break the
    feature outright."""
    set_id = _ingest(client, _binder(), "search-short")
    pid = _parts(client, set_id)[1]["part_id"]

    body = client.get(f"/client-boq/ingest/parts/{set_id}/{pid}/search",
                      params={"q": "indemnify"}).json()
    assert body["count"] == 1
    assert body["hits"][0]["page"] == 6


def test_a_query_that_is_not_there_returns_no_hits_but_stays_searchable(client):
    set_id = _ingest(client, _binder(), "search-miss")
    pid = _parts(client, set_id)[1]["part_id"]

    body = client.get(f"/client-boq/ingest/parts/{set_id}/{pid}/search",
                      params={"q": "liquidated damages at HK$5,000 per day"}).json()
    assert body["searchable"] is True and body["count"] == 0 and body["note"] == ""


def test_a_scanned_part_says_it_cannot_be_searched_rather_than_finding_nothing(client):
    """The difference between 'we looked and it is not there' and 'we could not look'. Reporting
    an empty result set for an image-only part would train the user to distrust the search."""
    set_id = _ingest(client, _scanned(), "search-scan")
    pid = _parts(client, set_id)[0]["part_id"]

    body = client.get(f"/client-boq/ingest/parts/{set_id}/{pid}/search",
                      params={"q": "anything at all"}).json()
    assert body["searchable"] is False
    assert body["count"] == 0
    assert "no text layer" in body["note"]


def test_an_empty_query_searches_for_nothing(client):
    set_id = _ingest(client, _binder(), "search-empty")
    pid = _parts(client, set_id)[0]["part_id"]

    body = client.get(f"/client-boq/ingest/parts/{set_id}/{pid}/search", params={"q": "  "}).json()
    assert body["query"] == "" and body["hits"] == []


def test_search_is_scoped_to_its_own_part(client):
    """The needle sits on binder page 6, inside part 2. Part 1 and part 3 must not find it."""
    set_id = _ingest(client, _binder(), "search-scoped")
    parts = _parts(client, set_id)

    found = {
        p["part_id"]: client.get(f"/client-boq/ingest/parts/{set_id}/{p['part_id']}/search",
                                 params={"q": NEEDLE}).json()["count"]
        for p in parts
    }
    assert sum(found.values()) == 1
    assert found[parts[1]["part_id"]] == 1


# ---------------------------------------------------------------------------
# Re-interpreting one part
# ---------------------------------------------------------------------------
def test_reinterpret_rewrites_one_parts_card_and_leaves_the_split_alone(client):
    set_id = _ingest(client, _binder(), "reinterpret-demo")
    before = _parts(client, set_id)
    target = before[1]

    resp = client.post(f"/client-boq/ingest/parts/{set_id}/{target['part_id']}/reinterpret")
    assert resp.status_code == 200, resp.text
    assert resp.json()["part_id"] == target["part_id"]

    after = _parts(client, set_id)
    # Page bounds, scan flags and every other part are untouched — interpretation is what
    # was retried, not the cut.
    assert [(p["part_id"], p["pages"], p["scanned"]) for p in after] == [
        (p["part_id"], p["pages"], p["scanned"]) for p in before
    ]


def test_reinterpreting_an_unreadable_part_stays_honest(client):
    """The retry may fail again, and when it does the card must still say so. A part nobody has
    read must never come back with a plausible summary — that is the one failure the interpret
    stage exists to prevent (CLAUDE.md trap 9)."""
    set_id = _ingest(client, _scanned(), "reinterpret-scan")
    part = _parts(client, set_id)[0]
    assert part["readable"] is False

    body = client.post(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/reinterpret").json()
    assert body["readable"] is False
    assert not body["context"]["summary"].strip()
    assert body["context"]["notes"]


def test_reinterpreting_an_unknown_part_404s(client):
    set_id = _ingest(client, _binder(), "reinterpret-404")
    assert client.post(f"/client-boq/ingest/parts/{set_id}/nope/reinterpret").status_code == 404


def test_the_viewer_routes_are_mounted(client):
    paths = set(client.app.openapi()["paths"])  # openapi(), not app.routes — CLAUDE.md trap 1
    assert {
        "/client-boq/ingest/parts/{set_id}/{part_id}/page/{page}.png",
        "/client-boq/ingest/parts/{set_id}/{part_id}/search",
        "/client-boq/ingest/parts/{set_id}/{part_id}/reinterpret",
    } <= paths
