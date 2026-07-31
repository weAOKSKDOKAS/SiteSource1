"""Spec for T7 — physically locating a cited quotation in the document.

Measured against the real tenders before building: exact search finds verbatim quotations
reliably in born-digital text (1,769 of 1,769 single-line quotations across GCT, SCT, CT, COE and
CSR), and correctly rejects a paraphrase. So a miss is meaningful — but only where the document
was searchable in the first place, which is why there are three verdicts rather than two.
"""

from __future__ import annotations

import pytest

from client_boq.ingest import pdfops
from client_boq.models import (
    LOCATED,
    NOT_LOCATED,
    UNVERIFIABLE,
    ClauseItem,
    DepartureItem,
    DepartureRegister,
    ParsedDocumentSet,
    PartSpec,
)
from client_boq.review import s08_citation_verify

fitz = pytest.importorskip("fitz")  # PyMuPDF

CLAUSE = ("Any qualification of tender or of the tender documents may cause the tender to be "
          "disqualified.")
OTHER = ("The tenderer shall be deemed to be in possession of a valid business registration "
         "certificate for the works described in the tender documents.")


def _doc(pages: list[str], path) -> str:
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        if body:
            page.insert_textbox(fitz.Rect(56, 72, 540, 720), body, fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


def _scan(pages: int, path) -> str:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
    doc.save(str(path))
    doc.close()
    return str(path)


# ---------------------------------------------------------------------------
# The locate primitive
# ---------------------------------------------------------------------------
def test_a_verbatim_quotation_is_found_with_its_page_and_rectangles(tmp_path):
    path = _doc(["filler page", CLAUSE], tmp_path / "d.pdf")
    hit = pdfops.locate(open(path, "rb").read(), CLAUSE)

    assert hit is not None
    assert hit["page"] == 2
    assert hit["match"] == "exact"
    assert hit["highlights"]
    box = hit["highlights"][0]
    # Fractions of the page, so a viewer can overlay them at any zoom.
    assert 0.0 <= box["x0"] < box["x1"] <= 1.0
    assert 0.0 <= box["y0"] < box["y1"] <= 1.0


def test_the_page_is_reported_in_the_source_documents_numbering(tmp_path):
    # A part cut from page 17 of a binder must report page 17, not its own page 1.
    path = _doc([CLAUSE], tmp_path / "part.pdf")
    hit = pdfops.locate(open(path, "rb").read(), CLAUSE, page_offset=16)
    assert hit["page"] == 17


def test_a_paraphrase_is_not_found(tmp_path):
    # The whole point of the guard: same meaning, different words, so the register would be
    # citing wording the contract does not contain.
    path = _doc([CLAUSE], tmp_path / "d.pdf")
    data = open(path, "rb").read()
    assert pdfops.locate(data, CLAUSE) is not None
    assert pdfops.locate(
        data, "Any qualification of the tender may result in disqualification of the tender."
    ) is None


def test_a_quotation_whose_tail_diverges_still_pins_the_page_down(tmp_path):
    path = _doc([CLAUSE], tmp_path / "d.pdf")
    trailing = CLAUSE + " The Employer's decision in this respect shall be final and binding."
    hit = pdfops.locate(open(path, "rb").read(), trailing)

    assert hit is not None and hit["page"] == 1
    assert hit["match"] == "fragment"          # honest about having matched only part of it
    assert hit["matched_text"] in trailing


def test_typographic_punctuation_does_not_defeat_a_match(tmp_path):
    """Regression, found against the real CIC Conditions of Tender.

    A typeset tender uses curly punctuation; a quotation retyped or produced by a model uses the
    straight forms. They read identically and are different characters, so an exact search fails
    on text that is plainly on the page. Measured on the reference documents: 81 curly quotes in
    the ND General Conditions of Tender, 44 in the CIC General Conditions of Employment, 31 in
    its Conditions of Tender.

    Tested with the straight forms in the document and the curly forms in the query, because
    PyMuPDF's base-14 fonts encode Latin-1 and cannot render a curly apostrophe into a synthetic
    test PDF at all. The matching logic is symmetric, so this exercises the same code path; the
    real-document direction is covered by the verification run against the CIC tender itself.
    """
    plain = ("Tenderer shall comply with the CIC's General Conditions of Contract for Works "
             "and shall allow twelve - eighteen months for the defects liability period.")
    data = open(_doc([plain], tmp_path / "d.pdf"), "rb").read()

    assert pdfops.locate(data, plain) is not None            # as written
    typeset = plain.replace("'", "’").replace(" - ", " – ")
    assert typeset != plain
    assert pdfops.locate(data, typeset) is not None          # curly query, straight document


def test_the_variant_generator_covers_both_directions():
    plain = "the Employer's decision - final"
    variants = pdfops._variants(plain)
    assert plain in variants
    assert any("’" in v for v in variants)              # straight -> curly
    curly = "the Employer’s decision – final"
    assert plain in pdfops._variants(curly)                  # curly -> straight


def test_a_short_needle_is_refused_rather_than_matched_by_accident(tmp_path):
    # A citation confirmed by accident is worse than one left unconfirmed.
    path = _doc([CLAUSE], tmp_path / "d.pdf")
    assert pdfops.locate(open(path, "rb").read(), "the tender") is None
    assert pdfops.locate(open(path, "rb").read(), "") is None


def test_a_scanned_document_has_no_text_layer_to_search(tmp_path):
    scanned = open(_scan(3, tmp_path / "scan.pdf"), "rb").read()
    readable = open(_doc([CLAUSE], tmp_path / "text.pdf"), "rb").read()

    assert pdfops.has_text_layer(scanned) is False
    assert pdfops.has_text_layer(readable) is True
    assert pdfops.locate(scanned, CLAUSE) is None
    assert pdfops.has_text_layer(b"") is False


# ---------------------------------------------------------------------------
# The three verdicts, and the corroboration rule
# ---------------------------------------------------------------------------
def _fixture(tmp_path, *, cited: str, part_path: str, part_id: str = "01-ct",
             extra: list[tuple[str, str]] = ()):
    """A register of one or more lines, all citing clauses in one part."""
    clauses = [ClauseItem(clause_id="4.26", text=CLAUSE, part_id=part_id, page=1)]
    items = [DepartureItem(item=1, clause="4.26", cited_text=cited, status="candidate")]
    for index, (clause_id, text) in enumerate(extra, start=2):
        clauses.append(ClauseItem(clause_id=clause_id, text=text, part_id=part_id, page=1))
        items.append(DepartureItem(item=index, clause=clause_id, cited_text=text,
                                   status="candidate"))
    parsed = ParsedDocumentSet(set_id="s", clauses=clauses)
    register = DepartureRegister(set_id="s", items=items)
    spec = PartSpec(n=1, abbr="CT", slug="ct", title="Conditions", start=1, end=2)
    return register, parsed, [(spec, part_path)]


def test_a_located_citation_reports_a_measured_page(tmp_path):
    path = _doc(["filler", CLAUSE], tmp_path / "part.pdf")
    register, parsed, parts = _fixture(tmp_path, cited=CLAUSE, part_path=path)

    locations = s08_citation_verify.locate_citations(register, parsed, parts)
    assert locations[0].verdict == LOCATED
    assert locations[0].page == 2
    assert locations[0].highlights
    # The measured page is written back onto the register line, replacing anything claimed.
    assert register.items[0].page == 2
    assert register.items[0].status == "candidate"      # untouched


def test_an_unsearchable_part_is_unverifiable_not_a_failure(tmp_path):
    # Two parts of the real 325 tender are image-only. Blaming the citation for the document's
    # shortcoming is how a warning becomes noise people learn to ignore.
    path = _scan(2, tmp_path / "part.pdf")
    register, parsed, parts = _fixture(tmp_path, cited=CLAUSE, part_path=path)

    locations = s08_citation_verify.locate_citations(register, parsed, parts)
    assert locations[0].verdict == UNVERIFIABLE
    assert "no text layer" in locations[0].note
    assert register.items[0].status == "candidate"      # NOT marked citation_failed


def test_a_paraphrase_fails_only_when_its_neighbours_corroborate_the_search(tmp_path):
    # Corroboration before accusation: another citation from the same part WAS found, so the
    # text layer, page range and parse all line up. A remaining miss is about the quotation.
    path = _doc([CLAUSE + "\n\n" + OTHER], tmp_path / "part.pdf")
    register, parsed, parts = _fixture(
        tmp_path,
        cited="Any qualification of the tender may result in disqualification of the tender.",
        part_path=path, extra=[("4.24", OTHER)],
    )

    locations = s08_citation_verify.locate_citations(register, parsed, parts)
    assert locations[1].verdict == LOCATED              # the neighbour corroborates
    assert locations[0].verdict == NOT_LOCATED
    assert "paraphrase" in locations[0].note
    assert register.items[0].status == "citation_failed"


def test_nothing_is_accused_when_no_citation_in_the_part_can_be_found(tmp_path):
    # The parse and the file do not correspond — a re-split, the wrong upload, or an offline
    # fixture. Condemning every citation at once would be both wrong and useless.
    path = _doc(["A page of entirely unrelated text about drainage and earthworks."],
                tmp_path / "part.pdf")
    register, parsed, parts = _fixture(
        tmp_path, cited=CLAUSE, part_path=path, extra=[("4.24", OTHER)],
    )

    locations = s08_citation_verify.locate_citations(register, parsed, parts)
    assert {loc.verdict for loc in locations} == {UNVERIFIABLE}
    assert "may not correspond" in locations[0].note
    assert all(item.status == "candidate" for item in register.items)


def test_reporting_mode_does_not_re_mark_the_register(tmp_path):
    path = _doc([CLAUSE + "\n\n" + OTHER], tmp_path / "part.pdf")
    register, parsed, parts = _fixture(
        tmp_path, cited="A paraphrase that is nowhere in this document at all whatsoever.",
        part_path=path, extra=[("4.24", OTHER)],
    )

    locations = s08_citation_verify.locate_citations(register, parsed, parts, strict=False)
    assert locations[0].verdict == NOT_LOCATED
    assert register.items[0].status == "candidate"      # read-only: nothing was re-marked


def test_a_human_verdict_is_never_overwritten_by_the_guard(tmp_path):
    # The approve endpoint is the only writer of a human verdict, including here.
    path = _doc([CLAUSE + "\n\n" + OTHER], tmp_path / "part.pdf")
    register, parsed, parts = _fixture(
        tmp_path, cited="Nowhere near what the document actually says, not at all.",
        part_path=path, extra=[("4.24", OTHER)],
    )
    register.items[0].status = "confirmed"

    s08_citation_verify.locate_citations(register, parsed, parts)
    assert register.items[0].status == "confirmed"


def test_a_line_citing_nothing_mapped_is_unverifiable(tmp_path):
    path = _doc([CLAUSE], tmp_path / "part.pdf")
    register, parsed, parts = _fixture(tmp_path, cited=CLAUSE, part_path=path)
    parsed.clauses[0].part_id = "99-missing"            # cites a part this set does not hold

    locations = s08_citation_verify.locate_citations(register, parsed, parts)
    assert locations[0].verdict == UNVERIFIABLE
    assert "nowhere to look" in locations[0].note


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _ingested(client) -> str:
    doc = fitz.open()
    for i in range(1, 13):
        doc.new_page().insert_text((72, 100), f"Binder page {i} with readable text", fontsize=11)
    doc.set_toc([[1, "Conditions of Tender", 1], [1, "Scope", 5], [1, "Pricing", 9]])
    data = doc.tobytes()
    doc.close()
    resp = client.post("/client-boq/ingest/upload", data={"project_name": "cite-demo"},
                       files={"files": ("binder.pdf", data, "application/pdf")})
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    client.post("/client-boq/review/run", data={"project_name": "cite-demo", "set_id": set_id})
    return set_id


def test_the_citations_endpoint_reports_every_verdict(client):
    set_id = _ingested(client)
    body = client.get(f"/client-boq/review/{set_id}/citations").json()

    assert body["checked"] > 0
    assert set(body["by_verdict"]) <= {LOCATED, UNVERIFIABLE, NOT_LOCATED}
    for entry in body["citations"]:
        assert entry["verdict"] in {LOCATED, UNVERIFIABLE, NOT_LOCATED}
        assert entry["note"]                     # every verdict explains itself


def test_citations_need_a_split_set_to_search(client):
    resp = client.post("/client-boq/review/run", data={"project_name": "loose"},
                       files={"files": ("x.pdf", b"%PDF-1.4 demo", "application/pdf")})
    set_id = resp.json()["result"]["set_id"]
    got = client.get(f"/client-boq/review/{set_id}/citations")
    assert got.status_code == 409
    assert "no document to search" in got.json()["detail"]
    assert client.get("/client-boq/review/nope/citations").status_code == 404


def test_the_citations_route_is_mounted(client):
    assert "/client-boq/review/{set_id}/citations" in set(client.app.openapi()["paths"])
