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


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


requires_tesseract = pytest.mark.skipif(not _tesseract_available(), reason="tesseract/pytesseract not installed")


@pytest.fixture(autouse=True)
def _isolate_ocr_cache(tmp_path, monkeypatch):
    # build_doc_entry reads the OCR spine, which caches on disk — keep tests off the real root.
    monkeypatch.setenv("SITESOURCE_OCR_CACHE", str(tmp_path / "ocr_cache"))


def _scanned_pdf(pages: list[list[str]]) -> bytes:
    """Like ``_pdf`` but each page is flattened to an image (no text layer) — a scanned doc."""
    src = fitz.open()
    for lines in pages:
        p = src.new_page()
        p.insert_text((72, 100), "\n".join(lines), fontsize=16)
    out = fitz.open()
    for i in range(src.page_count):
        png = src[i].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes("png")
        op = out.new_page(width=src[i].rect.width, height=src[i].rect.height)
        op.insert_image(op.rect, stream=png)
    data = out.tobytes()
    src.close()
    out.close()
    return data


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
    assert e.clause_index["7.1"] == [0]
    assert e.clause_index["7.13.1"] == [1] and e.clause_index["7.14"] == [1]


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


def test_ps_without_a_cover_page_keeps_ps_kind_and_scopes_from_the_filename():
    # A PS whose page 1 lost its "SECTION 7" header (scanned cover / starts mid-section) and merely
    # CITES an appendix inline must NOT be reclassified appendix: it stays a PS, its section is
    # derived from the "PS-S07" filename, and its clause index scopes to 7 (so a stray 0.5 is noise).
    data = _pdf([
        ["7.34A Rotary drilling in rock", "Refer to Appendix 7.4.16 for the borehole logs."],
        ["7.37A Standard penetration test", "0.5 m nominal diameter"],
    ])
    e = build_doc_entry("PS-S07-particular-spec.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.kind == "particular_specification"      # not appendix, despite the inline "Appendix 7.4.16"
    assert e.spec_section_number == "7"              # derived from the filename
    assert e.clause_index.get("7.34A") == [0] and e.clause_index.get("7.37A") == [1]
    assert "7.4.16" not in e.clause_index            # inline appendix cross-reference, not a heading
    assert "0.5" not in e.clause_index               # bare decimal, not a clause


def test_non_pdf_bytes_degrade_to_no_text_layer():
    e = build_doc_entry("scan.png", DocType.PARTICULAR_SPECIFICATION, b"not a pdf")
    assert e.text_layer is False and e.page_count == 0 and e.clause_index == {}


def test_ps_clause_records_its_onward_appendix_reference():
    # A PS clause that points to a separate appendix ("refer to Appendix 7.8.20") records the
    # onward appendix id, so dispatch can pull that appendix from the persisted index alone.
    data = _pdf([[
        "SECTION 7 - GEOTECHNICAL WORKS",
        "7.07A Bored piling in rock",
        "Refer to Appendix 7.8.20 for the borehole logs.",
    ]])
    e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.clause_onward_appendices.get("7.07A") == ["7.8.20"]


@requires_tesseract
def test_scanned_ps_gets_text_layer_and_clause_index_via_ocr(tmp_path, monkeypatch):
    # The point of the OCR spine: a SCANNED PS (no native text) now yields text_layer=True and a
    # clause_index, so the assembler slices it instead of falling back to whole-file.
    monkeypatch.setenv("SITESOURCE_OCR_CACHE", str(tmp_path / "ocr_cache"))
    data = _scanned_pdf([
        ["SECTION 7 - GEOTECHNICAL WORKS", "7.34A Rotary drilling in rock"],
        ["7.37A Standard penetration test", "the clause explanation continues"],
    ])
    e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.text_layer is True and e.page_count == 2       # scanned, but OCR gave it text
    assert "7.34A" in e.clause_index and "7.37A" in e.clause_index  # markers found in the OCR text


def test_doc_index_round_trips_through_the_workspace(tmp_path):
    ws = Workspace(tmp_path)
    data = _pdf([["SECTION 26 - PRESERVATION AND PROTECTION OF TREES", "26.1 Scope"]])
    entries = [build_doc_entry("PS-S26.pdf", DocType.PARTICULAR_SPECIFICATION, data)]
    save_doc_index(ws, "GE/2026/14", entries)
    loaded = load_doc_index(ws, "GE/2026/14")
    assert len(loaded) == 1 and loaded[0].spec_section_number == "26"
    assert loaded[0].clause_index == {"26.1": [0]}
    assert load_doc_index(ws, "no-such-tender") == []  # missing -> empty, never raises


# -- Assembler v2: PS suffix / amendment markers + MM PB markers ------------
def test_ps_index_locates_letter_suffixed_clauses_and_amendment_leadins():
    data = _pdf([
        ["SECTION 7 - GEOTECHNICAL WORKS", "Replace GS Clause 7.28 with the following:"],
        ["7.34A Rotary drilling in rock", "the full explanation of the clause continues"],
        ["7.37A Standard penetration test", "7.41.(4)S Special provision applies"],
    ])
    e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.clause_index["7.34A"] == [1]                 # letter-suffixed PS clause located
    assert e.clause_index["7.37A"] == [2]
    assert e.clause_index["7.41.(4)S"] == [2]             # bracket + S suffix located
    assert e.clause_index["7.28"] == [0]                  # amendment lead-in -> the GS clause it amends


def test_mm_index_locates_pb_markers_and_ignores_running_headers():
    data = _pdf([
        ["PART A - GROUND INVESTIGATION", "PB 1 General measurement"],
        ["- PB/2 -", "PB 71 Boreholes measured by depth drilled"],
    ])
    e = build_doc_entry("MM-01.pdf", DocType.METHOD_OF_MEASUREMENT, data)
    assert e.kind == "method_of_measurement" and e.text_layer is True
    assert e.clause_index["PB 1"] == [0] and e.clause_index["PB 71"] == [1]
    assert "PB 2" not in e.clause_index and "PB/2" not in e.clause_index  # noise line not a clause


# -- multi-column scanned PS: layout-aware clause markers from word boxes ----
from pipeline.stage_01_ingest.doc_index import _headings_from_words  # noqa: E402


def _wb(text, left, width, *, row, top):
    """A tesseract-style word box (as ``ocr_table._words`` returns): text + geometry only."""
    return {"text": text, "conf": 90.0, "left": float(left), "cx": left + width / 2.0,
            "top": float(top), "row_key": (1, 1, row)}


def test_headings_from_word_boxes_recovers_the_clause_number_column():
    # A multi-column PS row under OCR: a label column (left), the clause id in a clause-number
    # column (~30% across), then the body — the id lands mid-line, fused with the body text.
    label = [_wb("Standpipes", 40, 60, row=1, top=100), _wb("in", 110, 15, row=1, top=100),
             _wb("trial", 135, 30, row=1, top=100), _wb("pits", 170, 20, row=1, top=100)]
    rowA = label + [_wb("7.278.2A", 220, 70, row=1, top=100),
                    _wb("(1)", 360, 25, row=1, top=100), _wb("When", 400, 40, row=1, top=100)]
    # An OCR-split clause id ("7.279." + "1A") in the SAME column must rejoin to "7.279.1A", while
    # the body sub-item "(1)" a column over must NOT be swallowed.
    rowB = [_wb("Drainage", 40, 60, row=2, top=130), _wb("test", 110, 30, row=2, top=130),
            _wb("7.279.", 220, 48, row=2, top=130), _wb("1A", 272, 22, row=2, top=130),
            _wb("(1)", 360, 25, row=2, top=130), _wb("The", 400, 30, row=2, top=130)]
    ids = _headings_from_words(rowA + rowB, "7")
    assert ids == ["7.278.2A", "7.279.1A"]  # column recovered; split id rejoined; "(1)" not fused


def test_headings_from_word_boxes_rejects_inline_cross_references():
    # An inline reference is in the body column (far right) or is preceded by a cue word; neither
    # is a heading. A real heading on the same page keeps the id anchored so the band is derived.
    heading = [_wb("Rotary", 40, 60, row=1, top=100), _wb("7.286A", 220, 70, row=1, top=100)]
    body_ref = [_wb("As", 360, 20, row=2, top=130), _wb("in", 390, 15, row=2, top=130),
                _wb("Clause", 415, 45, row=2, top=130), _wb("7.278.1A", 470, 70, row=2, top=130)]
    cue_ref = [_wb("of", 110, 15, row=3, top=160), _wb("Clause", 150, 45, row=3, top=160),
               _wb("7.300A", 225, 60, row=3, top=160), _wb("applies", 300, 50, row=3, top=160)]
    ids = _headings_from_words(heading + body_ref + cue_ref, "7")
    assert ids == ["7.286A"]  # only the true heading; the body ref and the cue-preceded ref rejected


def test_headings_from_word_boxes_normalise_ocr_noise_forms():
    # Leading OCR punctuation ("=7.286A") and an internal OCR space ("7.279." + "1A") normalise to
    # the same canonical clause id the resolver's clause_of produces.
    rowA = [_wb("=7.286A", 220, 70, row=1, top=100), _wb("Rotary", 360, 50, row=1, top=100)]
    rowB = [_wb("7.279.", 220, 48, row=2, top=130), _wb("1A", 272, 22, row=2, top=130)]
    assert _headings_from_words(rowA + rowB, "7") == ["7.286A", "7.279.1A"]


def test_headings_from_word_boxes_scope_to_the_declared_section():
    # A dotted number from another section (2.1) on a Section-7 page is not taken as a clause.
    rows = [_wb("2.1", 220, 40, row=1, top=100), _wb("stray", 360, 40, row=1, top=100),
            _wb("7.34A", 220, 60, row=2, top=130), _wb("Rotary", 360, 50, row=2, top=130)]
    assert _headings_from_words(rows, "7") == ["7.34A"]          # scoped to section 7
    # Unscoped, a real clause must show structure — 7.34A has a letter suffix and is kept; a bare
    # 1-dot "2.1" is indistinguishable from a decimal and is rejected as noise (no section to vouch).
    assert _headings_from_words(rows, "") == ["7.34A"]


def test_headings_from_word_boxes_reject_bare_decimals():
    # A bare decimal like "0.5" in the clause-number band (an OCR'd quantity) is NOT a clause id — a
    # real clause shows >=2 dots or a letter suffix. "7.278.5A" still indexes.
    rowA = [_wb("7.278.5A", 220, 70, row=1, top=100), _wb("Rotary", 360, 50, row=1, top=100)]
    rowB = [_wb("0.5", 220, 40, row=2, top=130), _wb("metre", 360, 40, row=2, top=130)]
    assert _headings_from_words(rowA + rowB, "") == ["7.278.5A"]  # unscoped: bare 0.5 rejected as noise


def test_headings_from_word_boxes_reject_inline_appendix_reference():
    # "… see Appendix 7.4.16 …" in the band is an onward cross-reference (the cue word "Appendix"
    # precedes the id), not a heading. A real heading on the page anchors the band.
    heading = [_wb("Rotary", 40, 60, row=1, top=100), _wb("7.286A", 220, 70, row=1, top=100)]
    app_cue = [_wb("see", 110, 30, row=2, top=130), _wb("Appendix", 150, 70, row=2, top=130),
               _wb("7.4.16", 230, 55, row=2, top=130), _wb("for", 300, 25, row=2, top=130)]
    assert _headings_from_words(heading + app_cue, "") == ["7.286A"]  # the inline appendix ref rejected


def test_layout_marker_maps_a_column_scanned_clause_to_its_page(monkeypatch):
    # Orchestration without tesseract: a mixed doc (native page 0 + scanned page 1). The native
    # page keeps the line-start path; the scanned page is read from stubbed word boxes and the
    # clause is mapped to page 1. Proves _spec_markers_layout routes native vs scanned by page.
    import pipeline.ocr_table as ocr_table

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "SECTION 7 - GEOTECHNICAL WORKS\n7.1 General requirements")
    scan = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 400))
    pix.clear_with(255)  # image-only page => no native text => the scanned/column path
    scan.insert_image(scan.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()

    boxes = [_wb("Rotary", 40, 60, row=1, top=100), _wb("7.286A", 220, 70, row=1, top=100),
             _wb("(1)", 360, 25, row=1, top=100)]
    monkeypatch.setattr(ocr_table, "_words", lambda *a, **k: boxes)  # scanned page 1 -> these boxes

    e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.clause_index.get("7.1") == [0]      # native page 0, line-start path unchanged
    assert e.clause_index.get("7.286A") == [1]   # scanned page 1, recovered from the word boxes


def test_engine_missing_on_the_word_box_path_fails_loud_not_a_silent_empty_index(monkeypatch):
    # A configured-but-missing engine on the scanned word-box path PROPAGATES (OcrEngineUnavailable),
    # never a silent [] that reads as "this page has no clauses". Mixed doc: native page 0 + scanned 1.
    import pipeline.ocr as ocr
    import pipeline.ocr_table as ocr_table

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "SECTION 7 - GEOTECHNICAL WORKS\n7.1 General requirements")
    scan = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 400))
    pix.clear_with(255)  # image-only page => the scanned/word-box path
    scan.insert_image(scan.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()

    def _no_engine(*a, **k):
        raise ocr.OcrEngineUnavailable("tesseract not found")

    monkeypatch.setattr(ocr_table, "_words", _no_engine)  # word-box path hits the missing engine
    with pytest.raises(ocr.OcrEngineUnavailable):
        build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)


def test_readable_ps_with_no_clause_markers_warns_instead_of_trusting_empty_index(caplog):
    # A PS with a real text layer but NO clause ids yields an empty index — surfaced as a WARNING
    # (it will be sent whole), never silently trusted as "no clauses" (no silent engine dependence).
    data = _pdf([["SECTION 7 - GEOTECHNICAL WORKS", "General prose with no clause numbers here."]])
    with caplog.at_level("WARNING"):
        e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.text_layer and e.clause_index == {}
    assert any("EMPTY clause index" in r.getMessage() for r in caplog.records)


def test_scanned_single_column_ps_line_start_heading_unioned_when_word_boxes_empty(monkeypatch):
    # A SINGLE-column scanned PS page: the clause id is at the OCR line start. Even when the word-box
    # column path finds nothing (the engine-live symptom), the line-start scan over the cached OCR
    # TEXT catches "7.286A" — the blind index degrades gracefully without a live word-box call.
    import pipeline.ocr as ocr

    data = _pdf([[], []])  # two image-less pages: no native text -> both take the scanned path
    monkeypatch.setattr(ocr, "page_texts", lambda *a, **k: [
        "SECTION 7 - GEOTECHNICAL WORKS",
        "7.286A Rotary drilling in rock\nthe clause body continues",
    ])
    monkeypatch.setattr(ocr, "page_words", lambda *a, **k: [])  # column path returns nothing
    e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.text_layer is True
    assert e.clause_index.get("7.286A") == [1]  # located from the line-start union over OCR text


@requires_tesseract
def test_real_multi_column_scanned_ps_is_sliced_not_whole(tmp_path, monkeypatch):
    # The whole point, end to end on a real render: a MULTI-COLUMN scanned PS (label column, a
    # clause-number column, body on the same rows) yields a clause_index with the clause id — so
    # the assembler slices it instead of "whole (clause not located)".
    monkeypatch.setenv("SITESOURCE_OCR_CACHE", str(tmp_path / "ocr_cache"))
    src = fitz.open()
    page = src.new_page(width=612, height=200)
    page.insert_text((36, 60), "SECTION 7 - GEOTECHNICAL WORKS", fontsize=12)
    # a multi-column row: label (left), clause id (~30% across), body (right) — all on one line
    page.insert_text((36, 110), "Standpipes in trial pits", fontsize=12)
    page.insert_text((200, 110), "7.286A", fontsize=12)
    page.insert_text((300, 110), "(1) When instructed by the Service Manager", fontsize=12)
    png = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes("png")
    src.close()
    flat = fitz.open()
    op = flat.new_page(width=612, height=200)
    op.insert_image(op.rect, stream=png)  # flatten => scanned (no text layer)
    data = flat.tobytes()
    flat.close()

    e = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert e.text_layer is True                 # OCR gave the scanned page text
    assert "7.286A" in e.clause_index           # the mid-line clause id was located (not whole+flag)
