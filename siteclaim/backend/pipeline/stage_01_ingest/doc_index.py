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
import re
from typing import Optional

from pydantic import BaseModel, Field

from schemas.models import DocType

# Page-1 self-declaration: "SECTION 7 – GEOTECHNICAL WORKS", "SECTION 26 - PRESERVATION …".
# The dash/colon separator is optional (a scanned header may drop the en-dash glyph); the
# title must start with a letter so a bare "SECTION 7" heading does not match with no title.
_SECTION_DECL = re.compile(r"SECTION\s+(\d+)\s*[–—:.\-]?\s*([A-Za-z][^\n]{1,79})", re.I)
_APPENDIX_DECL = re.compile(r"\bAppendix\s+(\d+(?:\.\d+)*)", re.I)
_GENERAL_SPEC = re.compile(r"General\s+Specification", re.I)


class DocIndexEntry(BaseModel):
    """The structural index for one uploaded original."""

    filename: str
    kind: str = "other"  # schedule_of_rates | method_of_measurement | particular_specification |
    #                      appendix | general_specification | clarification | other
    spec_section_number: str = ""   # "7" / "26" / "" (the section this doc IS, if it declares one)
    spec_section_title: str = ""
    text_layer: bool = False        # >= 1 page with a real text layer
    page_count: int = 0
    # clause heading -> 0-based page it starts on (text-layer PS/appendix only)
    clause_index: dict[str, int] = Field(default_factory=dict)


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
    """Per-page text via pymupdf, or None if it is not a readable PDF."""
    try:
        import fitz  # PyMuPDF — lazy
    except Exception:  # noqa: BLE001 — no pymupdf -> no index (whole-file fallback downstream)
        return None
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return [page.get_text("text", sort=True) for page in doc]
    except Exception:  # noqa: BLE001 — an image/corrupt upload: treated as no text layer
        return None


def _clause_index(pages: list[str], section_number: str) -> dict[str, int]:
    """Map each clause heading to the 0-based page it first starts on. Scoped to the doc's own
    section numbering when known (``^7\\.\\d+ …``), else any dotted heading at line start."""
    prefix = rf"{re.escape(section_number)}\.\d+(?:\.\d+)*" if section_number else r"\d+\.\d+(?:\.\d+)*"
    heading = re.compile(rf"^\s*({prefix})(?:\b|\s)")
    index: dict[str, int] = {}
    for page_no, text in enumerate(pages):
        for line in text.splitlines():
            m = heading.match(line)
            if m and m.group(1) not in index:
                index[m.group(1)] = page_no
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
    clause_index: dict[str, int] = {}
    if text_layer and kind in ("particular_specification", "appendix", "general_specification"):
        clause_index = _clause_index(pages, section_number)

    return DocIndexEntry(
        filename=filename, kind=kind, spec_section_number=section_number,
        spec_section_title=section_title, text_layer=text_layer, page_count=len(pages),
        clause_index=clause_index,
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
