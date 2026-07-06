"""Per-section relevant-document resolver (Layer 1, deterministic; pymupdf lazy for slicing).

For one dispatched SoR section, decide exactly which documents a firm needs and how much of
each — driven by the clauses its SoR items reference (the "Clause Ref" column), NOT a
trade→spec guess:

* PS: slice the Particular Specification to the pages of the PS clauses the section references
  (and the PS amendments of any referenced GS clause), ± 1 page so a clause across a break is
  whole.
* MM: slice the Method of Measurement to the pages of the referenced ``PB`` clauses — it is no
  longer sent whole to every firm.
* GS: the General Specification is not in the package. A GS clause amended by a present PS
  clause rides in the PS extract; a GS clause with no present amendment is flagged
  ``missing_spec: General Specification 7.xx`` — never silently omitted.
* Fallbacks: a referenced clause that cannot be located → the whole doc for that firm, flagged;
  a scanned doc → whole, flagged. Always include the generated SoR sheet and every
  clarification / general document (whole, to everyone).

The plan is data (testable offline); the actual file slicing (``slice_pdf``) runs at assembly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.doc_refs import base_clause, clause_of, refs_for_items, spec_section_of


class PlanAttachment(BaseModel):
    """One document in a section's assembled set."""

    source_doc: str            # the original filename, or the generated SoR sheet name
    mode: str                  # "sliced" | "whole" | "generated"
    pages: list[int] = Field(default_factory=list)   # 1-based pages (sliced mode only)
    clauses: list[str] = Field(default_factory=list)  # the clause ids this extract contains
    reason: str = ""
    flags: list[str] = Field(default_factory=list)   # e.g. "scanned_whole" | "whole_clause_not_located"


class MissingSpec(BaseModel):
    spec: str          # e.g. "PS Section 28"
    referenced_by: str  # "SoR references" | "topic map"


class SectionPlan(BaseModel):
    package_key: str = ""
    section: str = ""
    attachments: list[PlanAttachment] = Field(default_factory=list)
    missing_specs: list[MissingSpec] = Field(default_factory=list)


def apply_attachment_overrides(
    plan: SectionPlan, *, removed: list[str] | None = None, whole: list[str] | None = None,
) -> SectionPlan:
    """Apply the human gate's per-document decisions to a section plan and return a NEW plan:
    drop any document the person removed, and expand any *sliced* document they chose to send
    whole (mode -> "whole", pages cleared). The generated SoR sheet is never removable — it is
    the priced-return sheet the enquiry is asking for. ``missing_specs`` are left intact so a
    referenced-but-unsupplied spec stays visible even after edits. Deterministic; no I/O."""
    removed_set = set(removed or [])
    whole_set = set(whole or [])
    kept: list[PlanAttachment] = []
    for att in plan.attachments:
        if att.source_doc in removed_set and att.mode != "generated":
            continue
        if att.source_doc in whole_set and att.mode == "sliced":
            att = att.model_copy(update={
                "mode": "whole", "pages": [],
                "reason": (att.reason + " · expanded to whole file at the gate").lstrip(" ·"),
            })
        kept.append(att)
    return plan.model_copy(update={"attachments": kept})


def _slice_pages(entry: DocIndexEntry, clauses: list[str]) -> list[int]:
    """0-based pages spanned by a set of clause ids, each page expanded ±1 (clamped to the doc)
    so a clause straddling a page break is kept whole. ``clause_index`` maps a clause to the
    list of pages it spans."""
    hits: set[int] = set()
    for c in clauses:
        hits.update(entry.clause_index.get(c, []))
    if not hits:
        return []
    pages: set[int] = set()
    last = max(0, entry.page_count - 1)
    for p in hits:
        for q in (p - 1, p, p + 1):
            if 0 <= q <= last:
                pages.add(q)
    return sorted(pages)


def _dedup(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _resolving_ps_clauses(entry: DocIndexEntry, ps_clauses: list[str], gs_clauses: list[str]) -> list[str]:
    """The clause_index keys of this PS doc that the section references: the referenced PS clauses
    present in the index, plus any key that AMENDS a referenced GS clause (a direct match, or a
    suffixed clause / amendment lead-in whose base equals the GS clause)."""
    keys = list(entry.clause_index)
    resolved = [c for c in ps_clauses if c in entry.clause_index]
    for g in gs_clauses:
        resolved += [k for k in keys if k == g or base_clause(k) == g]
    return _dedup(resolved)


def resolve_section_plan(
    *, package_key: str, trade: str, section_title: str, items: list,
    doc_index: list[DocIndexEntry], sor_sheet_name: str, section: str = "",
) -> SectionPlan:
    """The relevant-only attachment plan for one dispatched SoR section, driven by the clause
    references its items carry (Clause Ref column). See the module docstring for the slicing rules."""
    refs = refs_for_items(items)
    ps_clauses = _dedup([clause_of(r) for r in refs.get("ps", [])])
    gs_clauses = _dedup([clause_of(r) for r in refs.get("gs", [])])
    pb_clauses = [r for r in refs.get("pb", []) if r.startswith("PB ")]  # MM number form "PB 71"
    appendix_clauses = _dedup([clause_of(a) for a in refs.get("appendix", [])])

    ps_ref_specs = {spec_section_of(r) for r in refs.get("ps", []) if spec_section_of(r)}
    gs_ref_specs = {spec_section_of(r) for r in refs.get("gs", []) if spec_section_of(r)}
    relevant_ps_specs = ps_ref_specs | gs_ref_specs  # a PS section is relevant if a PS or GS clause in it is cited
    cited_appendices = {spec_section_of(a) for a in refs.get("appendix", []) if spec_section_of(a)}

    # Onward hop: a resolved PS clause may point to a SEPARATE appendix document ("refer to
    # Appendix 7.8.20"). Gather those appendix clause ids from the persisted clause_onward index
    # (a pre-pass so order in doc_index doesn't matter), and merge them into what the appendix
    # branch pulls — so the firm gets the appendix even though its SoR item only cited the PS clause.
    onward: list[str] = []
    for e in doc_index:
        if e.kind in ("particular_specification", "general_specification") and e.spec_section_number in relevant_ps_specs:
            for c in (_resolving_ps_clauses(e, ps_clauses, gs_clauses) if e.text_layer else []):
                onward += e.clause_onward_appendices.get(c, [])
    onward = _dedup(onward)
    appendix_clauses = _dedup(appendix_clauses + onward)
    cited_appendices = cited_appendices | {spec_section_of(a) for a in onward if spec_section_of(a)}

    plan: list[PlanAttachment] = [
        PlanAttachment(source_doc=sor_sheet_name, mode="generated", reason="Priced Schedule of Rates for this section"),
    ]
    present_ps: set[str] = set()
    present_appendices: set[str] = set()
    gs_covered: set[str] = set()  # GS clauses a present PS doc amends

    for e in doc_index:
        if e.kind == "clarification":
            plan.append(PlanAttachment(source_doc=e.filename, mode="whole", reason="Clarification / addendum — issued to all firms"))
        elif e.kind == "general_specification":
            plan.append(PlanAttachment(source_doc=e.filename, mode="whole", reason="General Specification — issued to all firms"))
        elif e.kind == "method_of_measurement":
            if not pb_clauses:
                continue  # this section references no measurement preamble — no MM extract
            resolved = [c for c in pb_clauses if c in e.clause_index]
            pages = _slice_pages(e, resolved) if e.text_layer else []
            if pages:
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages], clauses=resolved,
                    reason="Method of Measurement — referenced preamble clauses"))
            else:
                scanned = not e.text_layer
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole", clauses=pb_clauses,
                    reason=f"Method of Measurement — whole ({'scanned' if scanned else 'clause not located'})",
                    flags=["scanned_whole"] if scanned else ["whole_clause_not_located"]))
        elif e.kind == "particular_specification":
            if not (e.spec_section_number and e.spec_section_number in relevant_ps_specs):
                continue  # this PS section is not referenced by the dispatched section
            present_ps.add(e.spec_section_number)
            resolved = _resolving_ps_clauses(e, ps_clauses, gs_clauses) if e.text_layer else []
            for g in gs_clauses:  # record which GS clauses this PS doc amends
                if any(k == g or base_clause(k) == g for k in e.clause_index):
                    gs_covered.add(g)
            pages = _slice_pages(e, resolved) if e.text_layer else []
            if pages:
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages], clauses=resolved,
                    reason=f"PS Section {e.spec_section_number} — referenced clauses"))
            else:
                scanned = not e.text_layer
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole",
                    reason=f"PS Section {e.spec_section_number} — whole ({'scanned' if scanned else 'clause not located'})",
                    flags=["scanned_whole"] if scanned else ["whole_clause_not_located"]))
        elif e.kind == "appendix":
            if not (e.spec_section_number and (e.spec_section_number in cited_appendices or e.spec_section_number in relevant_ps_specs)):
                continue
            present_appendices.add(e.spec_section_number)
            pages = _slice_pages(e, appendix_clauses) if e.text_layer else []
            if pages:
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages], clauses=appendix_clauses,
                    reason=f"Appendix {e.spec_section_number} — referenced pages"))
            else:
                scanned = not e.text_layer
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole",
                    reason=f"Appendix {e.spec_section_number} — whole ({'scanned' if scanned else 'referenced'})",
                    flags=["scanned_whole"] if scanned else []))

    missing: list[MissingSpec] = [
        MissingSpec(spec=f"PS Section {spec}", referenced_by="SoR references")
        for spec in sorted(ps_ref_specs - present_ps)
    ]
    # A GS clause with no present PS amendment: the base General Specification text is not
    # enclosed — surface it so the human decides, never a silent omission.
    for g in gs_clauses:
        if g not in gs_covered:
            missing.append(MissingSpec(spec=f"General Specification {g}", referenced_by="SoR references"))
    # An appendix referenced (by an item directly, or onward from a PS clause) but with no matching
    # appendix document present — flagged, not silently dropped.
    for app_sec in sorted(cited_appendices - present_appendices):
        missing.append(MissingSpec(spec=f"Appendix {app_sec}", referenced_by="SoR references"))
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
