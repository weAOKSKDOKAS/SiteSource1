"""Per-section relevant-document resolver (Layer 1, deterministic; pymupdf lazy for slicing).

For one dispatched SoR section, decide exactly which documents a firm needs and how much of
each: slice a text-layer Particular Specification to the pages of the clauses its items
reference (± 1 page so a clause across a page break is not cut), fall back to the WHOLE file
where the document is scanned or nothing resolves, always include the generated SoR sheet, the
Method of Measurement, and every clarification/general document, and flag any referenced spec
section that was not supplied — never a silent omission. The plan is data (testable offline);
the actual file slicing (``slice_pdf``) runs at assembly.
"""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel, Field

from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.doc_refs import clause_of, refs_for_items, spec_section_of

# Topic fallback: a section whose scope reads geotechnical needs PS/Appendix 7; a tree /
# landscape section needs PS/Appendix 26. Robustness for SoR items that don't spell out a ref.
_TOPIC: list[tuple[re.Pattern, set[str]]] = [
    (re.compile(r"geotech|ground\s*invest|\bGI\b|drilling|borehole|rotary|in-?situ", re.I), {"7"}),
    (re.compile(r"\btree|landscap|preservation|planting|arbor|soft\s*works", re.I), {"26"}),
]


class PlanAttachment(BaseModel):
    """One document in a section's assembled set."""

    source_doc: str            # the original filename, or the generated SoR sheet name
    mode: str                  # "sliced" | "whole" | "generated"
    pages: list[int] = Field(default_factory=list)   # 1-based pages (sliced mode only)
    reason: str = ""
    flags: list[str] = Field(default_factory=list)   # e.g. "scanned_whole"


class MissingSpec(BaseModel):
    spec: str          # e.g. "PS Section 28"
    referenced_by: str  # "SoR references" | "topic map"


class SectionPlan(BaseModel):
    package_key: str = ""
    section: str = ""
    attachments: list[PlanAttachment] = Field(default_factory=list)
    missing_specs: list[MissingSpec] = Field(default_factory=list)


def _topic_specs(text: str) -> set[str]:
    specs: set[str] = set()
    for pattern, s in _TOPIC:
        if pattern.search(text or ""):
            specs |= s
    return specs


def _slice_pages(entry: DocIndexEntry, clauses: list[str]) -> list[int]:
    """0-based pages for a set of clause numbers, each expanded ±1 (clamped to the doc)."""
    hits = {entry.clause_index[c] for c in clauses if c in entry.clause_index}
    if not hits:
        return []
    pages: set[int] = set()
    last = max(0, entry.page_count - 1)
    for p in hits:
        for q in (p - 1, p, p + 1):
            if 0 <= q <= last:
                pages.add(q)
    return sorted(pages)


def resolve_section_plan(
    *, package_key: str, trade: str, section_title: str, items: list,
    doc_index: list[DocIndexEntry], sor_sheet_name: str, section: str = "",
) -> SectionPlan:
    """The relevant-only attachment plan for one dispatched SoR section."""
    refs = refs_for_items(items)
    ref_specs = {spec_section_of(r) for r in refs.get("ps", []) + refs.get("gs", []) if spec_section_of(r)}
    topic_specs = _topic_specs(f"{trade} {section_title}")
    relevant_specs = ref_specs | topic_specs

    clauses_by_spec: dict[str, list[str]] = defaultdict(list)
    for r in refs.get("ps", []):
        clauses_by_spec[spec_section_of(r)].append(clause_of(r))
    # An appendix is matched by its NUMBER ("Appendix 7.4.1" -> appendix 7) against the doc's
    # declared "Appendix 7"; the sub-clause drives the slice within it.
    cited_appendices = {spec_section_of(a) for a in refs.get("appendix", []) if spec_section_of(a)} | topic_specs

    plan: list[PlanAttachment] = [
        PlanAttachment(source_doc=sor_sheet_name, mode="generated", reason="Priced Schedule of Rates for this section"),
    ]
    present_ps: set[str] = set()
    present_appendices: set[str] = set()
    for e in doc_index:
        if e.kind == "method_of_measurement":
            plan.append(PlanAttachment(source_doc=e.filename, mode="whole", reason="Method of Measurement — measurement rules apply broadly"))
        elif e.kind == "clarification":
            plan.append(PlanAttachment(source_doc=e.filename, mode="whole", reason="Clarification / addendum — issued to all firms"))
        elif e.kind == "general_specification":
            if refs.get("gs") or (e.spec_section_number and e.spec_section_number in relevant_specs):
                plan.append(PlanAttachment(source_doc=e.filename, mode="whole", reason="General Specification — referenced by this section"))
        elif e.kind == "particular_specification":
            if e.spec_section_number and e.spec_section_number in relevant_specs:
                present_ps.add(e.spec_section_number)
                pages = _slice_pages(e, clauses_by_spec.get(e.spec_section_number, [])) if e.text_layer else []
                if pages:
                    plan.append(PlanAttachment(
                        source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages],
                        reason=f"PS Section {e.spec_section_number} — referenced clauses"))
                else:
                    scanned = not e.text_layer
                    plan.append(PlanAttachment(
                        source_doc=e.filename, mode="whole",
                        reason=f"PS Section {e.spec_section_number} — whole ({'scanned' if scanned else 'no clause resolved to a page'})",
                        flags=["scanned_whole"] if scanned else []))
        elif e.kind == "appendix":
            if e.spec_section_number and (e.spec_section_number in cited_appendices or e.spec_section_number in relevant_specs):
                present_appendices.add(e.spec_section_number)
                pages = _slice_pages(e, [clause_of(a) for a in refs.get("appendix", [])]) if e.text_layer else []
                if pages:
                    plan.append(PlanAttachment(
                        source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages],
                        reason=f"Appendix {e.spec_section_number} — referenced pages"))
                else:
                    scanned = not e.text_layer
                    plan.append(PlanAttachment(
                        source_doc=e.filename, mode="whole",
                        reason=f"Appendix {e.spec_section_number} — whole ({'scanned' if scanned else 'referenced'})",
                        flags=["scanned_whole"] if scanned else []))

    missing = [
        MissingSpec(spec=f"PS Section {spec}", referenced_by=("SoR references" if spec in ref_specs else "topic map"))
        for spec in sorted(relevant_specs) if spec not in present_ps
    ]
    return SectionPlan(package_key=package_key, section=section, attachments=plan, missing_specs=missing)


def slice_pdf(data: bytes, pages_1based: list[int]) -> bytes:
    """Extract ``pages_1based`` from a PDF into a new PDF (pymupdf, lazy). Empty / on error
    returns the original bytes (whole-file — never fabricate or drop content)."""
    if not pages_1based:
        return data
    try:
        import fitz  # PyMuPDF — lazy
    except Exception:  # noqa: BLE001
        return data
    try:
        with fitz.open(stream=data, filetype="pdf") as src:
            out = fitz.open()
            last = src.page_count - 1
            for p in sorted({q - 1 for q in pages_1based if 1 <= q <= last + 1}):
                out.insert_pdf(src, from_page=p, to_page=p)
            result = out.tobytes()
            out.close()
            return result or data
    except Exception:  # noqa: BLE001
        return data
