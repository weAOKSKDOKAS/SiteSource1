"""Spec for R3/R4 — the three routes that answer "what does this mean, and where does it come from".

Each exists because of a specific complaint about the shipped UI:

* the register showed ``PS-01`` and nothing else, so a reviewer could not tell what position the
  finding was measured against. The library holding that position was never exposed;
* the context cards asserted things about a part with no way to check them against the page, and
  no way to disagree with them;
* the register described a *different document* from the one on screen, so nothing highlighted and
  the viewer looked broken when it was working exactly as designed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip("fitz")  # PyMuPDF

QUOTE = "Any qualification of tender may cause the tender to be disqualified"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _binder(pages: int = 12) -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        page = doc.new_page()
        page.insert_text((72, 100), f"Binder page {i} of {pages}", fontsize=11)
        if i == 2:  # inside part 1 (pages 1-4)
            page.insert_text((72, 140), QUOTE, fontsize=9)
    doc.set_toc([
        [1, "Conditions of Tender", 1],
        [1, "Scope of Works", 5],
        [1, "Pricing Schedule", 9],
    ])
    data = doc.tobytes()
    doc.close()
    return data


def _ingest(client: TestClient, name="context-demo", data: bytes | None = None) -> str:
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": name},
        files={"files": ("binder.pdf", data or _binder(), "application/pdf")},
    )
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    return set_id


def _part(client: TestClient, set_id: str, index: int = 0) -> dict:
    return client.get(f"/client-boq/ingest/parts/{set_id}").json()["parts"][index]


# ---------------------------------------------------------------------------
# The acceptable-terms library
# ---------------------------------------------------------------------------
def test_the_criteria_library_is_exposed_with_the_fields_that_explain_a_finding(client):
    """A register row stores `PS-01`. Without these two fields it is a code nobody can decode."""
    body = client.get("/client-boq/criteria").json()
    assert body["count"] > 0

    by_id = {c["id"]: c for c in body["criteria"]}
    ps01 = by_id["PS-01"]
    assert ps01["clause_area"] == "Payment Claims"
    assert ps01["acceptable_position"], "what we accept"
    assert ps01["red_flag"], "what to watch for"
    assert ps01["why_it_matters"]


def test_placeholder_criteria_are_returned_not_silently_dropped(client):
    """The module's standing rule: no referenced criterion disappears quietly."""
    body = client.get("/client-boq/criteria").json()
    assert isinstance(body["placeholders"], list)
    assert all(c["is_placeholder"] for c in body["placeholders"])


# ---------------------------------------------------------------------------
# Editing a context card
# ---------------------------------------------------------------------------
def test_editing_a_card_stamps_it_user(client):
    """The model's reading is a proposal like everything else it produces. Correcting one
    transfers ownership — the same rule as a scope line, for the same reason."""
    set_id = _ingest(client)
    part = _part(client, set_id)
    before = client.get(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}").json()["context"]
    assert before["badge"] == "ai"

    resp = client.post(
        f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/context",
        json={"summary": "This is the invitation letter and the tender timetable.",
              "obligations": ["Return by the stated deadline.", "Use the issued forms."]},
    )
    assert resp.status_code == 200, resp.text
    ctx = resp.json()["context"]
    assert ctx["badge"] == "user"
    assert ctx["summary"].startswith("This is the invitation letter")
    assert len(ctx["obligations"]) == 2


def test_an_edit_survives_a_reload(client):
    set_id = _ingest(client)
    part = _part(client, set_id)
    client.post(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/context",
                json={"summary": "Corrected by hand."})

    fresh = client.get(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}").json()["context"]
    assert fresh["summary"] == "Corrected by hand." and fresh["badge"] == "user"


def test_readable_is_a_measurement_and_cannot_be_edited(client):
    """Whether a page carries a text layer is measured, and the module's standing rule is that a
    measurement is not clearable by an opinion — the same reason `mark_scanned` is re-applied
    after the planner and after a manifest edit."""
    set_id = _ingest(client)
    part = _part(client, set_id)

    resp = client.post(
        f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/context",
        json={"summary": "x", "readable": False},   # extra field, silently ignored by the schema
    )
    assert resp.status_code == 200
    assert resp.json()["context"]["readable"] is True


def test_re_interpreting_puts_the_machine_reading_back(client):
    """Because that genuinely IS a fresh machine reading — it must not keep claiming to be yours."""
    set_id = _ingest(client)
    part = _part(client, set_id)
    client.post(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/context",
                json={"summary": "Mine."})
    assert client.get(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}").json()["context"]["badge"] == "user"

    client.post(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/reinterpret")
    assert client.get(f"/client-boq/ingest/parts/{set_id}/{part['part_id']}").json()["context"]["badge"] == "ai"


def test_an_empty_edit_is_refused(client):
    set_id = _ingest(client)
    part = _part(client, set_id)
    assert client.post(
        f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/context", json={}
    ).status_code == 422


# ---------------------------------------------------------------------------
# Proving a quoted claim against the page
# ---------------------------------------------------------------------------
def test_a_quote_that_is_on_the_page_is_located_with_a_measured_page(client):
    set_id = _ingest(client)
    part = _part(client, set_id)  # pages 1-4; the quote is on page 2

    body = client.post(
        f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/locate", json={"quote": QUOTE}
    ).json()
    assert body["verdict"] == "located"
    assert body["page"] == 2
    box = body["highlights"][0]
    assert 0.0 <= box["x0"] < box["x1"] <= 1.0
    # `located` covers both an exact hit and a fragment fallback, and those are not equally strong
    # evidence. The verdict alone cannot say which, so the note must.
    assert body["match"] == "exact"
    assert body["note"] == "found on page 2"


def test_a_quote_that_is_not_on_these_pages_says_so(client):
    """This verdict earns its place: an offline fixture broadcasts the same strategy flags onto
    every part of a set, and this is what shows that only one part actually contains them."""
    set_id = _ingest(client)
    other = _part(client, set_id, 1)  # pages 5-8 — the quote is on page 2

    body = client.post(
        f"/client-boq/ingest/parts/{set_id}/{other['part_id']}/locate", json={"quote": QUOTE}
    ).json()
    assert body["verdict"] == "not_located"
    assert body["highlights"] == []
    assert "not on pages" in body["note"]


def test_a_scanned_part_reports_that_it_could_not_be_checked(client):
    doc = fitz.open()
    for _ in range(4):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
    scanned = doc.tobytes()
    doc.close()

    set_id = _ingest(client, "locate-scan", scanned)
    part = _part(client, set_id)
    body = client.post(
        f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/locate", json={"quote": QUOTE}
    ).json()
    assert body["verdict"] == "unverifiable"
    assert "no text layer" in body["note"]


# ---------------------------------------------------------------------------
# Locating across the whole set — what "show me on the page" actually needs
# ---------------------------------------------------------------------------
def test_a_set_wide_locate_names_the_part_holding_the_quote(client):
    """The per-part route can only answer about the document already open, and that made the
    button useless on a folder set: it reported "not found" from whichever part happened to be on
    screen while the words sat in another file. Finding the right document is the button's job."""
    set_id = _ingest(client, "set-locate")           # 3 parts; the quote is on page 2, part one
    parts = client.get(f"/client-boq/ingest/parts/{set_id}").json()["parts"]
    assert len(parts) >= 3

    # Ask from a part that does NOT contain it — the case that used to fail.
    body = client.post(
        f"/client-boq/ingest/{set_id}/locate",
        json={"quote": QUOTE, "prefer_part_id": parts[2]["part_id"]},
    ).json()
    assert body["verdict"] == "located"
    assert body["part_id"] == parts[0]["part_id"], "it must name the part that holds the words"
    assert body["page"] == 2
    assert body["highlights"]
    assert parts[0]["part_id"] in body["note"], "the note must say which document it landed in"


def test_a_set_wide_miss_says_how_many_documents_were_searched(client):
    """"Not found" is only worth trusting if it says how hard it looked."""
    set_id = _ingest(client, "set-locate-miss")
    body = client.post(
        f"/client-boq/ingest/{set_id}/locate",
        json={"quote": "a sentence that is in none of these documents whatsoever"},
    ).json()
    assert body["verdict"] == "not_located"
    assert body["part_id"] == ""
    assert body["highlights"] == []
    assert "searchable document" in body["note"]


def test_a_set_wide_locate_needs_a_quote_and_a_set(client):
    set_id = _ingest(client, "set-locate-guard")
    assert client.post(f"/client-boq/ingest/{set_id}/locate", json={"quote": " "}).status_code == 422
    assert client.post("/client-boq/ingest/no-such-set/locate", json={"quote": QUOTE}).status_code == 404


def test_locating_nothing_is_refused(client):
    set_id = _ingest(client)
    part = _part(client, set_id)
    assert client.post(
        f"/client-boq/ingest/parts/{set_id}/{part['part_id']}/locate", json={"quote": "  "}
    ).status_code == 422


# ---------------------------------------------------------------------------
# "These findings are not about your document"
# ---------------------------------------------------------------------------
def test_the_register_reports_when_it_describes_a_different_document(client):
    """The single most confusing state in the app. In DEMO the review returns a fixture about a
    fictional subcontract, so every citation is unlocatable and nothing highlights — which looks
    like a broken viewer and is not one. The register now says so."""
    set_id = _ingest(client, "mismatch-demo")
    client.post("/client-boq/review/run", data={"project_name": "mismatch-demo", "set_id": set_id})

    body = client.get(f"/client-boq/review/register/{set_id}").json()
    mismatch = body["parse_mismatch"]
    assert mismatch is not None, "the DEMO fixture is about another document; that must be visible"
    assert "binder.pdf" in [u for u in mismatch["uploaded"]]
    assert mismatch["reviewed"] and "binder.pdf" not in mismatch["reviewed"]
    assert "that were uploaded" in mismatch["note"]


def test_the_mismatch_note_stays_short_however_many_files_were_uploaded():
    """The warning must not grow until it hides the findings it is warning about.

    It used to inline every filename on both sides. That read fine for a binder plus two annexes,
    and on a 203-file folder ingest it rendered a wall of text that made the Register unusable —
    roughly 14,000 characters of paths where two sentences were wanted. The full lists are returned
    beside the note as ``reviewed`` and ``uploaded`` for the screen to disclose on demand.
    """
    from client_boq.router import _name_a_few

    many = [f"nd202504 contract dcos/acc/i-nd_2025_04-acc_app_{n}-0.pdf" for n in range(203)]
    named = _name_a_few(many)

    assert named.endswith("and 200 more")
    assert len(named) < 200, named
    # Basenames, not paths: the folder is already established by the sentence around it.
    assert "nd202504 contract dcos/" not in named
    assert _name_a_few(["a.pdf", "b.pdf"]) == "a.pdf, b.pdf"   # a short list is shown in full
    assert _name_a_few([]) == "nothing"


def test_the_mismatch_is_absent_when_nothing_was_split(client):
    """Nothing to disagree with — the guard must not fire on a set that was never ingested."""
    resp = client.post(
        "/client-boq/review/run",
        data={"project_name": "loose-upload"},
        files={"files": ("contract.pdf", _binder(), "application/pdf")},
    )
    assert resp.status_code == 200
    set_id = resp.json()["result"]["set_id"]
    assert client.get(f"/client-boq/review/register/{set_id}").json()["parse_mismatch"] is None


def test_the_new_routes_are_mounted(client):
    paths = set(client.app.openapi()["paths"])  # openapi(), not app.routes — CLAUDE.md trap 1
    assert {
        "/client-boq/criteria",
        "/client-boq/ingest/parts/{set_id}/{part_id}/context",
        "/client-boq/ingest/parts/{set_id}/{part_id}/locate",
        "/client-boq/ingest/{set_id}/locate",
    } <= paths
