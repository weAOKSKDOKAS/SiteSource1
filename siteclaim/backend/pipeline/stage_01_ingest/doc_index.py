"""Per-document index built at ingest (Layer 1, deterministic; pymupdf lazy-imported).

Beyond the trade routing that ``classify`` produces, the relevant-document assembler needs
structural facts about each uploaded original: its ``kind``, the spec section it self-declares
on page 1 (``SECTION 7 – GEOTECHNICAL WORKS`` / ``Appendix 7``), whether it carries a real
text layer, its page count, and — for a text-layer Particular Specification or appendix — a
``clause_index`` mapping each clause heading to the page it starts on. That index lets dispatch
slice a spec to only the clauses a firm's SoR section references, and fall back to whole-file
where the document is scanned or nothing resolves. Pure pymupdf + regex — no LLM, no network;
persisted with the run so dispatch can read it back.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from schemas.models import DocType

_log = logging.getLogger(__name__)

# Page-1 self-declaration: "SECTION 7 – GEOTECHNICAL WORKS", "SECTION 26 - PRESERVATION …".
# The dash/colon separator is optional (a scanned header may drop the en-dash glyph); the
# title must start with a letter so a bare "SECTION 7" heading does not match with no title.
_SECTION_DECL = re.compile(r"SECTION\s+(\d+)\s*[–—:.\-]?\s*([A-Za-z][^\n]{1,79})", re.I)
_APPENDIX_DECL = re.compile(r"\bAppendix\s+(\d+(?:\.\d+)*)", re.I)
_GENERAL_SPEC = re.compile(r"General\s+Specification", re.I)

# A PS/GS clause id: a dotted number with optional letter / bracket / trailing-letter suffixes
# (7.34, 7.34A, 7.39S, 7.41.(4)S, 7.72(6)S — the dot before the bracket is optional). Kept verbatim
# so a reference resolves to the exact amendment, and matches the same id ``doc_refs`` produces.
_CLAUSE_ID = r"\d+(?:\.\d+)*[A-Za-z]?(?:\.?\(\d+\))?[A-Za-z]?"
# PS amendment lead-ins carry the GS clause they amend: "Replace GS Clause 7.28 with the
# following:", "Add the following Clauses after GS Clause 7.30:". Indexed so a GS reference
# resolves to the page where its amendment begins.
_PS_LEADIN = re.compile(r"(?:Replace|Add)\b[^\n]*?GS\s+Clause\s+(\d+(?:\.\d+)*[A-Za-z]?)", re.I)
# MM preamble clause markers: "PB 71". A running-header noise line ("- PB/2 -") never matches —
# the marker must start the line and have digits immediately after PB.
_MM_MARKER = re.compile(r"^\s*PB\s*(\d+)\b", re.I)


class DocIndexEntry(BaseModel):
    """The structural index for one uploaded original."""

    filename: str
    kind: str = "other"  # schedule_of_rates | method_of_measurement | particular_specification |
    #                      appendix | general_specification | clarification | other
    spec_section_number: str = ""   # "7" / "26" / "" (the section this doc IS, if it declares one)
    spec_section_title: str = ""
    text_layer: bool = False        # >= 1 page with a real text layer
    page_count: int = 0
    # clause id -> the 0-based pages it spans (its marker page to the page before the next
    # marker; ±1 is applied at slice time). Text-layer PS / appendix / GS / MM only.
    clause_index: dict[str, list[int]] = Field(default_factory=dict)
    # PS clause id -> appendix clause ids referenced WITHIN that clause's page span (e.g.
    # "7.07A" -> ["7.8.20"] from "refer to Appendix 7.8.20"). Lets dispatch pull the SEPARATE
    # appendix document a PS clause points to — the onward hop SoR item -> PS clause -> appendix.
    clause_onward_appendices: dict[str, list[str]] = Field(default_factory=dict)


def _kind_for(doc_type: DocType, page1: str, filename: str) -> str:
    """Refine the coarse DocType into the assembler's kind, reading the page-1 declaration."""
    hay = f"{page1}\n{filename}"
    if doc_type == DocType.SCHEDULE_OF_RATES:
        return "schedule_of_rates"
    if doc_type == DocType.METHOD_OF_MEASUREMENT:
        return "method_of_measurement"
    if doc_type == DocType.TENDER_ADDENDUM:
        return "clarification"
    if _APPENDIX_DECL.search(hay) and not _SECTION_DECL.search(page1):
        return "appendix"
    if doc_type == DocType.PARTICULAR_SPECIFICATION:
        return "particular_specification"
    if _GENERAL_SPEC.search(hay):
        return "general_specification"
    return "other"


def _pages_text(data: bytes) -> Optional[list[str]]:
    """Per-page text via the OCR spine — the native text layer where a page has one, local
    tesseract OCR for scanned pages — so ``text_layer`` and the clause index build on scanned
    specs too, not just native-text ones. ``None`` when the input is not a readable PDF (or
    pymupdf is absent); a scanned page with no OCR available degrades to ``""`` (no false
    marker), exactly the pre-OCR behaviour."""
    from pipeline import ocr  # lazy: pymupdf / pytesseract stay optional for module import

    try:
        return ocr.page_texts(data)
    except ocr.NotAPdf:
        return None
    except Exception:  # noqa: BLE001 — no pymupdf / unreadable upload -> no index (whole-file fallback)
        return None


def _heading_re(section_number: str) -> re.Pattern:
    """A line-start clause-heading matcher, scoped to the doc's own section number when known
    (``7.34A`` under Section 7) so a stray dotted number elsewhere is not mistaken for a clause;
    else any clause id."""
    scoped = rf"{re.escape(section_number)}\.\d+(?:\.\d+)*[A-Za-z]?(?:\.?\(\d+\))?[A-Za-z]?" if section_number else _CLAUSE_ID
    return re.compile(rf"^\s*({scoped})(?=[\s.:)]|$)")


def _page_line_markers(text: str, heading: re.Pattern, page_no: int) -> list[tuple[str, int]]:
    """Line-start clause headings + amendment lead-ins on one page's text — the native-text path
    (a real text layer, or a single-column page whose OCR keeps clause ids at line start)."""
    markers: list[tuple[str, int]] = []
    for line in text.splitlines():
        m = heading.match(line)
        if m:
            markers.append((m.group(1), page_no))
        for lm in _PS_LEADIN.finditer(line):
            markers.append((lm.group(1), page_no))
    return markers


def _spec_markers(pages: list[str], section_number: str) -> list[tuple[str, int]]:
    """``(clause_id, page)`` for a PS / appendix / GS doc: clause headings at line start (scoped to
    the doc's own section numbering when known, e.g. ``7.34A``), plus the GS clauses named in
    amendment lead-ins. In document order. Line-start only — the layout-aware scanned-spec path is
    :func:`_spec_markers_layout` (used for PS/GS, which are multi-column when scanned)."""
    heading = _heading_re(section_number)
    return [m for page_no, text in enumerate(pages) for m in _page_line_markers(text, heading, page_no)]


# -- layout-aware spec markers (multi-column scanned PS / GS) ----------------
# HK GI Particular Specification pages are MULTI-COLUMN (a narrow label column, a clause-number
# column ~30% across, then the clause body). Under OCR the columns collapse onto one line, so the
# clause id lands MID-LINE fused with the body ("Standpipes in trial pits  7.278.2A  (1) When …")
# and the line-start scan above matches nothing. For a SCANNED PS/GS page we instead read the OCR
# word boxes and take the clause id that sits in the clause-number column, mirroring the SoR
# column recovery in ``ocr_table``. A native-text page keeps the line-start path unchanged.

_NATIVE_MIN = 20  # a page with fewer native chars than this is treated as scanned (as page_texts)
# A token that begins like a clause number ("7.278.2A", "7.279.", "=7.286A") — anchors the Pass-1
# clause-number column and is tolerant of the leading OCR punctuation seen in the documents.
_LOOSE_CLAUSE = re.compile(r"^[=.]*\d+\.\d")
# Words that, immediately before a clause id, mark it an INLINE cross-reference, not a heading
# ("… in Clause 7.278.1A", "General Specification Clause 7.73"). Compared in a stripped, lower form.
_CUE_WORDS = {
    "clause", "clauses", "subclause", "specification", "specifications", "general", "particular",
    "gs", "ps", "in", "under", "see", "refer", "reference", "ref", "per",
}


def _clean_word(text: str) -> str:
    """A word reduced to its lowercase letters for cue matching (``"Clause"``/``"Clause,"`` ->
    ``"clause"``, ``"sub-clause"`` -> ``"subclause"``)."""
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _canonical_heading(raw: str, section_number: str) -> Optional[str]:
    """Normalise a clause-number cell to the SAME canonical clause id the resolver's ``clause_of``
    produces (so index keys match referenced refs), dropping internal OCR spaces. ``None`` unless
    it is a dotted clause id and — when the doc declares a section — in that section."""
    from pipeline.stage_03_dispatch.doc_refs import base_clause, clause_of  # lazy: pure util

    cid = clause_of((raw or "").replace(" ", ""))
    if not cid or "." not in cid:
        return None
    if section_number and base_clause(cid).split(".")[0] != str(section_number):
        return None
    return cid


def _clause_number_column(words: list[dict]) -> Optional[tuple[float, float]]:
    """The ``(left, right)`` x-band of the clause-number column, derived (never hardcoded) from the
    LEFTMOST cluster of clause-id-shaped token boxes on the page — an inline body reference clusters
    further right and is excluded. ``None`` when the page carries no clause-id token."""
    lrs = [(float(w["left"]), 2.0 * float(w["cx"]) - float(w["left"]))  # (left, right=left+width)
           for w in words if _LOOSE_CLAUSE.match(w.get("text") or "")]
    if not lrs:
        return None
    lefts = sorted(left for left, _ in lrs)
    gap = max(20.0, (lefts[-1] - lefts[0]) * 0.15)  # tolerant to page size; splits the columns
    cluster_max_left = lefts[0]
    for prev, cur in zip(lefts, lefts[1:]):
        if cur - prev > gap:
            break  # first big gap = the jump to the body column's inline refs
        cluster_max_left = cur
    col_left = lefts[0]
    col_right = max((r for left, r in lrs if col_left <= left <= cluster_max_left), default=cluster_max_left)
    pad = max(12.0, gap * 0.4)
    return (col_left - pad, col_right + pad)


def _row_heading(row: list[dict], band: tuple[float, float], section_number: str) -> Optional[str]:
    """The clause id for one row of word boxes: the contiguous run of tokens sitting in the
    clause-number ``band`` (so an OCR-split id ``7.279.`` + ``1A`` rejoins, while the body ``(1)`` a
    column over is excluded). ``None`` when no token is in the band, or the first band token is an
    inline reference (immediately preceded by a cue word like ``Clause`` / ``in``)."""
    lo, hi = band
    in_band = [i for i, w in enumerate(row) if lo <= float(w["cx"]) <= hi]
    if not in_band:
        return None
    first = in_band[0]
    if first > 0 and _clean_word(row[first - 1].get("text") or "") in _CUE_WORDS:
        return None  # "… in Clause 7.278.1A …" — an inline cross-reference, not a heading
    run = [first]
    for i in in_band[1:]:
        if i != run[-1] + 1:
            break  # only join tokens adjacent within the column (an OCR-split clause id)
        run.append(i)
    raw = "".join(row[i].get("text") or "" for i in run)
    return _canonical_heading(raw, section_number)


def _headings_from_words(words: list[dict], section_number: str) -> list[str]:
    """The clause-heading ids on one scanned page, from its OCR word boxes: find the clause-number
    column, then take the in-column clause id per row. Pure (no tesseract) — tests stub the word
    reader as ``test_ocr_table`` does."""
    from pipeline import ocr_table  # reuse the SoR row grouping; pure, no tesseract at import

    band = _clause_number_column(words)
    if band is None:
        return []
    ids: list[str] = []
    for row in ocr_table._group_rows(words):
        cid = _row_heading(row, band, section_number)
        if cid and cid not in ids:
            ids.append(cid)
    return ids


def _open_pdf(data: bytes):
    import fitz  # PyMuPDF — lazy

    try:
        return fitz.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001 — unreadable -> caller degrades to the line-start path
        return None


def _column_headings(data: bytes, page_no: int, section_number: str) -> list[str]:
    """Clause-heading ids for one SCANNED spec page via CACHED word-box OCR (``ocr.page_words`` —
    served from the versioned cache, tesseract only on a miss).

    A configured-but-missing ENGINE (:class:`ocr.OcrEngineUnavailable`) PROPAGATES — it is a
    deployment fault, and swallowing it to ``[]`` would silently produce an empty clause index that
    reads as 'this page has no clauses'. Only a NARROW per-page glitch (no pytesseract installed at
    all, a rasterise error) degrades to no markers for THIS page (whole-file fallback)."""
    from pipeline import ocr

    try:
        words = ocr.page_words(data, page_no)
    except ocr.OcrEngineUnavailable:
        raise  # engine misconfiguration — fail loud, never a silent empty index
    except Exception:  # noqa: BLE001 — no pytesseract / a per-page rasterise glitch -> no markers here
        return []
    return _headings_from_words(words, section_number)


def _spec_markers_layout(data: bytes, pages: list[str], section_number: str) -> list[tuple[str, int]]:
    """``(clause_id, page)`` for a PS / GS doc, LAYOUT-AWARE: a native-text page keeps the line-start
    scan; a scanned page (multi-column PS/GS whose OCR fuses the clause id mid-line) is read from its
    word boxes so the clause-number column is recovered. Amendment lead-ins are read from the page
    text either way. With OCR disabled it is exactly ``_spec_markers`` (native-only)."""
    from pipeline import ocr

    heading = _heading_re(section_number)
    doc = _open_pdf(data) if ocr.ocr_enabled() else None
    if doc is None:
        return _spec_markers(pages, section_number)  # OCR off / unreadable -> native line-start only
    markers: list[tuple[str, int]] = []
    try:
        for page_no, text in enumerate(pages):
            page = doc[page_no] if page_no < doc.page_count else None
            native = page.get_text("text", sort=True) if page is not None else text
            if page is None or len(native.strip()) >= _NATIVE_MIN:
                markers.extend(_page_line_markers(text, heading, page_no))  # native page, unchanged
            else:
                markers.extend((cid, page_no) for cid in _column_headings(data, page_no, section_number))
                for lm in _PS_LEADIN.finditer(text):  # lead-ins from the OCR text on a scanned page
                    markers.append((lm.group(1), page_no))
    finally:
        doc.close()
    return markers


def _mm_markers(pages: list[str]) -> list[tuple[str, int]]:
    """``("PB N", page)`` for each Method-of-Measurement preamble clause, in document order."""
    markers: list[tuple[str, int]] = []
    for page_no, text in enumerate(pages):
        for line in text.splitlines():
            m = _MM_MARKER.match(line)
            if m:
                markers.append((f"PB {m.group(1)}", page_no))
    return markers


def _onward_appendices(pages: list[str], clause_index: dict[str, list[int]]) -> dict[str, list[str]]:
    """For each PS clause, the appendix clause ids referenced within its page span — parsed from
    the page text with the SAME appendix regex the SoR resolver uses. Empty entries are dropped."""
    from pipeline.stage_03_dispatch.doc_refs import clause_of, extract_refs  # lazy: pure util, avoids a cycle

    out: dict[str, list[str]] = {}
    for clause_id, span in clause_index.items():
        text = "\n".join(pages[p] for p in span if 0 <= p < len(pages))
        apps = extract_refs(text).get("appendix", [])
        if apps:
            ids: list[str] = []
            for a in apps:
                cid = clause_of(a)  # "Appendix 7.8.20" -> "7.8.20"
                if cid and cid not in ids:
                    ids.append(cid)
            if ids:
                out[clause_id] = ids
    return out


def _spans(markers: list[tuple[str, int]], page_count: int) -> dict[str, list[int]]:
    """Turn ordered clause markers into ``clause_id -> [pages]``: each clause spans from its
    marker's page to the page BEFORE the next marker (at least its own page). A repeated id
    unions its spans. ±1 is applied later, at slice time, to catch a clause across a page break."""
    index: dict[str, list[int]] = {}
    for i, (clause_id, page) in enumerate(markers):
        next_page = markers[i + 1][1] if i + 1 < len(markers) else page_count
        end = next_page - 1 if next_page > page else page
        span = set(range(page, max(end, page) + 1))
        index[clause_id] = sorted(set(index.get(clause_id, [])) | span)
    return index


def build_doc_entry(filename: str, doc_type: DocType, data: bytes) -> DocIndexEntry:
    """Structural index for one original. Non-PDF / unreadable -> text_layer False, no index."""
    pages = _pages_text(data)
    if pages is None:
        return DocIndexEntry(filename=filename, kind=_kind_for(doc_type, "", filename))
    page1 = pages[0] if pages else ""
    text_layer = any(p.strip() for p in pages)

    section_number, section_title = "", ""
    sec = _SECTION_DECL.search(page1)
    if sec:
        section_number, section_title = sec.group(1), sec.group(2).strip()
    else:
        app = _APPENDIX_DECL.search(page1)
        if app:
            section_number, section_title = app.group(1), f"Appendix {app.group(1)}"

    kind = _kind_for(doc_type, page1, filename)
    clause_index: dict[str, list[int]] = {}
    clause_onward: dict[str, list[str]] = {}
    if text_layer and kind == "method_of_measurement":
        clause_index = _spans(_mm_markers(pages), len(pages))
    elif text_layer and kind in ("particular_specification", "general_specification"):
        # PS/GS pages are multi-column when scanned, so the clause id lands mid-line under OCR;
        # scan the word boxes column-aware (native pages keep the line-start path). Do NOT touch MM.
        clause_index = _spans(_spec_markers_layout(data, pages, section_number), len(pages))
        if not clause_index:
            # The doc WAS readable (text layer / OCR) yet produced no clause markers — surface it
            # rather than trust a silently-empty index: it will be sent WHOLE, and an empty index on
            # a readable spec usually means a broken OCR engine or unrecognised markers, not "no
            # clauses". No silent engine dependence.
            _log.warning(
                "PS/GS %r has a text layer but produced an EMPTY clause index (%d pages) — it will be "
                "sent whole; verify the OCR engine and clause markers rather than trusting the empty index",
                filename, len(pages),
            )
        # A PS clause may point onward to an appendix ("refer to Appendix 7.8.20"); record it now,
        # while the page text is in hand, so dispatch reads only the persisted index.
        clause_onward = _onward_appendices(pages, clause_index)
    elif text_layer and kind == "appendix":
        clause_index = _spans(_spec_markers(pages, section_number), len(pages))

    return DocIndexEntry(
        filename=filename, kind=kind, spec_section_number=section_number,
        spec_section_title=section_title, text_layer=text_layer, page_count=len(pages),
        clause_index=clause_index, clause_onward_appendices=clause_onward,
    )


def build_doc_index(docs: list[tuple[str, DocType, bytes]]) -> list[DocIndexEntry]:
    """Index every uploaded original: ``(filename, doc_type, bytes)`` -> entries."""
    return [build_doc_entry(name, doc_type, data) for (name, doc_type, data) in docs]


def save_doc_index(workspace, tender_id: str, entries: list[DocIndexEntry]) -> None:
    path = workspace.doc_index_path(tender_id, create=True)
    path.write_text(json.dumps([e.model_dump() for e in entries], indent=2), encoding="utf-8")


def load_doc_index(workspace, tender_id: str) -> list[DocIndexEntry]:
    path = workspace.doc_index_path(tender_id)
    if not path.is_file():
        return []
    try:
        return [DocIndexEntry(**d) for d in json.loads(path.read_text(encoding="utf-8"))]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
