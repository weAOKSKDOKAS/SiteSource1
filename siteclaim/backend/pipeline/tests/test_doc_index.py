"""Per-document structural index at ingest (relevant-doc assembler, RD2). Builds tiny real
PDFs with pymupdf so text-layer / scanned behaviour is exercised offline."""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    build_doc_entry,
    load_doc_index,
    save_doc_index,
)
from pipeline.workspace import Workspace
from schemas.models import DocType

fitz = pytest.importorskip("fitz")  # PyMuPDF


def _pdf(pages: list[list[str]]) -> bytes:
    """A PDF from a list of pages, each a list of text lines (empty list = a scanned/blank page)."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        y = 72
        for line in lines:
            page.insert_text((72, y), line)
            y += 18
    return doc.tobytes()


def test_text_layer_ps_gets_section_title_and_clause_page_index():
    data = _pdf([
        ["SECTION 7 - GEOTECHNICAL WORKS", "7.1 General requirements"],
        ["7.13.1 Rotary drilling in soil", "7.14 Sampling and testing"],
    ])
    e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.kind == "particular_specification"
    assert e.spec_section_number == "7" and "GEOTECHNICAL" in e.spec_section_title.upper()
    assert e.text_layer is True and e.page_count == 2
    assert e.clause_index["7.1"] == 0
    assert e.clause_index["7.13.1"] == 1 and e.clause_index["7.14"] == 1


def test_scanned_appendix_has_no_text_layer_and_no_clause_index():
    # a page with no inserted text = no text layer (a scan)
    data = _pdf([[], [], []])
    e = build_doc_entry("APPENDIX 7.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.text_layer is False and e.page_count == 3
    assert e.clause_index == {}
    # kind still resolves from the filename declaration even with no text layer
    assert e.kind == "appendix"


def test_appendix_declared_on_page_one_is_kind_appendix():
    data = _pdf([["Appendix 7", "Ground investigation logs"], ["borehole BH-01"]])
    e = build_doc_entry("appendix7.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.kind == "appendix" and e.spec_section_number == "7"


def test_non_pdf_bytes_degrade_to_no_text_layer():
    e = build_doc_entry("scan.png", DocType.PARTICULAR_SPECIFICATION, b"not a pdf")
    assert e.text_layer is False and e.page_count == 0 and e.clause_index == {}


def test_doc_index_round_trips_through_the_workspace(tmp_path):
    ws = Workspace(tmp_path)
    data = _pdf([["SECTION 26 - PRESERVATION AND PROTECTION OF TREES", "26.1 Scope"]])
    entries = [build_doc_entry("PS-S26.pdf", DocType.PARTICULAR_SPECIFICATION, data)]
    save_doc_index(ws, "GE/2026/14", entries)
    loaded = load_doc_index(ws, "GE/2026/14")
    assert len(loaded) == 1 and loaded[0].spec_section_number == "26"
    assert loaded[0].clause_index == {"26.1": 0}
    assert load_doc_index(ws, "no-such-tender") == []  # missing -> empty, never raises
