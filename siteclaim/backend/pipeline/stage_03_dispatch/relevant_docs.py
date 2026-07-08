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

import re
from typing import Callable, Optional

from pydantic import BaseModel, Field

from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.doc_refs import base_clause, clause_of, extract_refs, refs_for_items, spec_section_of


class PlanAttachment(BaseModel):
    """One document in a section's assembled set."""

    source_doc: str            # the original filename (disk lookup key), or the generated SoR sheet name
    out_filename: str = ""     # the emitted filename when it differs from source_doc (the SoR slice is
    #   looked up under the original SR name but sent as "SoR_{unit}_Section_{X}.pdf"); "" -> source_doc
    mode: str                  # "sliced" | "whole" | "generated"
    pages: list[int] = Field(default_factory=list)   # 1-based pages (sliced mode only)
    clauses: list[str] = Field(default_factory=list)  # the clause ids this extract contains
    directed_clauses: list[str] = Field(default_factory=list)  # of ``clauses``, those the blind index
    #   MISSED and the directed text search located (engine-independent) — for the location report
    clauses_not_located: list[str] = Field(default_factory=list)  # referenced clauses located NOWHERE
    #   (neither index nor directed) though this section IS present — surfaced, never silently dropped
    reason: str = ""
    flags: list[str] = Field(default_factory=list)   # e.g. "scanned_whole" | "whole_clause_not_located"


# The priced-return sheet the enquiry asks the firm to fill and send back — the SoR sliced to this
# unit's section (or, offline, the generated .xlsx). Carried as a flag so the human gate protects it
# regardless of its mode (a slice, a whole-SoR fallback, or the generated sheet).
PRICED_RETURN = "priced_return"


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
    whole (mode -> "whole", pages cleared). The priced-return sheet (the SoR slice — or, offline,
    the generated sheet) is never removable and never expanded to the whole SoR: it is exactly the
    section the enquiry asks the firm to price. ``missing_specs`` are left intact so a
    referenced-but-unsupplied spec stays visible even after edits. Deterministic; no I/O."""
    removed_set = set(removed or [])
    whole_set = set(whole or [])
    kept: list[PlanAttachment] = []
    for att in plan.attachments:
        protected = att.mode == "generated" or PRICED_RETURN in att.flags
        if att.source_doc in removed_set and not protected:
            continue
        if att.source_doc in whole_set and att.mode == "sliced" and not protected:
            att = att.model_copy(update={
                "mode": "whole", "pages": [],
                "reason": (att.reason + " · expanded to whole file at the gate").lstrip(" ·"),
            })
        kept.append(att)
    return plan.model_copy(update={"attachments": kept})


def _expand(pages0: set[int], page_count: int) -> list[int]:
    """0-based pages expanded ±1 and clamped to the doc, so a clause straddling a page break stays
    whole. Shared by the blind-index slice and the directed-search slice."""
    last = max(0, page_count - 1)
    out: set[int] = set()
    for p in pages0:
        for q in (p - 1, p, p + 1):
            if 0 <= q <= last:
                out.add(q)
    return sorted(out)


def _slice_pages(entry: DocIndexEntry, clauses: list[str]) -> list[int]:
    """0-based pages spanned by a set of clause ids, each page expanded ±1. ``clause_index`` maps a
    clause to the list of pages it spans."""
    hits: set[int] = set()
    for c in clauses:
        hits.update(entry.clause_index.get(c, []))
    return _expand(hits, entry.page_count) if hits else []


# -- directed clause location over cached OCR text (engine-independent) -------
# We KNOW which PS/GS clauses a section references (its SoR clause_refs). When the blind clause_index
# STILL missed one after mid-line detection, locate that specific clause by searching the doc's CACHED
# page text — no live engine, single- and multi-column alike. OCR-TOLERANT: the clause id may carry a
# leading "=" and whitespace around its dots (verified in the wild: "=7.286A", "7.77. 2A", "7. 77.2A");
# the match is normalised (whitespace stripped, leading "=" dropped) before canonicalisation. Anchored
# so it is not matched inside a longer number.
# Whitespace is tolerated ONLY around the DOTS ("7.77. 2A", "7. 77.2A"); the suffix bracket must
# follow immediately (no space), so a space-separated body "(1)" after the id is NOT absorbed as part
# of it ("7.286A (1)" -> "7.286A", not "7.286A(1)").
_OCR_CLAUSE = re.compile(r"(?<![\w.])=?\d+(?:\s*\.\s*\d+)+[A-Za-z]?(?:\.?\(\d+\))?[A-Za-z]?")


def _located_headings(page_texts: list[str], section_number: str) -> dict[str, list[int]]:
    """``{canonical clause id -> sorted 0-based pages}`` for every clause id that appears as a HEADING
    in the cached page text — the SAME line-start / mid-line heading test as the blind index
    (``doc_index._is_heading_occurrence``), so an inline cross-reference ("… in Clauses 7.301A (4)")
    or a measurement ("… 7.5 metres") is not taken as a heading. OCR-tolerant matching; reads text
    only, so it is engine-independent and layout-agnostic."""
    from pipeline.stage_01_ingest.doc_index import _accept_clause_id, _is_heading_occurrence

    out: dict[str, set[int]] = {}
    for page_no, text in enumerate(page_texts):
        for line in text.splitlines():
            for m in _OCR_CLAUSE.finditer(line):
                cid = clause_of(re.sub(r"\s+", "", m.group(0)).lstrip("="))  # normalise OCR spacing / '='
                if cid and _accept_clause_id(cid, section_number) and _is_heading_occurrence(line, m, section_number):
                    out.setdefault(cid, set()).add(page_no)
    return {k: sorted(v) for k, v in out.items()}


def _directed_for_entry(
    entry: DocIndexEntry, ps_clauses: list[str], gs_clauses: list[str], page_texts: list[str],
) -> dict[str, list[int]]:
    """``{clause id -> located 0-based pages}`` for the referenced clauses this PS doc SHOULD carry but
    whose blind ``clause_index`` MISSED — located by a directed heading search over the cached OCR
    text. PS clauses match exactly; a GS clause matches a heading whose ``base_clause`` equals it (its
    suffixed PS amendment). Empty when no text is available (DEMO / no upload)."""
    if not page_texts:
        return {}
    sec = entry.spec_section_number
    ps_wanted = [c for c in ps_clauses
                 if c not in entry.clause_index and base_clause(c).split(".")[0] == sec]
    gs_wanted = [g for g in gs_clauses
                 if base_clause(g).split(".")[0] == sec
                 and not any(k == g or base_clause(k) == g for k in entry.clause_index)]
    if not (ps_wanted or gs_wanted):
        return {}
    located = _located_headings(page_texts, sec)
    out: dict[str, list[int]] = {}
    for c in ps_wanted:
        if c in located:
            out[c] = located[c]
    for g in gs_wanted:
        pages = sorted({p for k, pgs in located.items() if (k == g or base_clause(k) == g) for p in pgs})
        if pages:
            out[g] = pages
    return out


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


def _unit_out_name(trade: str, package_key: str, section: str) -> str:
    """The friendly emit-name for the priced-return SoR slice: ``SoR_{unit}_Section_{X}.pdf`` (or
    ``SoR_{unit}.pdf`` with no section). The unit token is filename-safe — ``:`` in a package_key and
    spaces are replaced."""
    unit = (trade or package_key or "unit").replace(" ", "_").replace(":", "-").strip("-") or "unit"
    return f"SoR_{unit}_Section_{section}.pdf" if section else f"SoR_{unit}.pdf"


def _priced_return_attachment(
    doc_index: list[DocIndexEntry], *, sections: list[str], trade: str, package_key: str, sor_sheet_name: str,
) -> PlanAttachment:
    """The priced-return sheet this enquiry asks the firm to fill and send back. In order of
    preference: the ORIGINAL Schedule of Rates sliced to this unit's section pages (``mode="sliced"``,
    emitted as ``SoR_{unit}_Section_{X}.pdf``) when an indexed SoR carries the section(s); the whole
    SoR flagged when it is present but NONE of the unit's sections is locatable (scanned / unindexed);
    or — offline, with no original SoR uploaded — the generated ``.xlsx`` sheet (unchanged DEMO /
    no-upload path). ``sections`` is the unit's SoR section code(s): the ``:SECTION`` suffix for a
    split unit, or — for a suffix-less single/specialty package — the distinct sections its items
    carry; a multi-section unit slices the UNION of their pages. Always flagged :data:`PRICED_RETURN`
    so the human gate never drops it."""
    section_keys = list(dict.fromkeys(s.upper() for s in sections if s))  # distinct, order-preserved
    sr_entries = [e for e in doc_index if e.kind == "schedule_of_rates"]
    if not sr_entries:
        return PlanAttachment(
            source_doc=sor_sheet_name, mode="generated", flags=[PRICED_RETURN],
            reason="Priced Schedule of Rates for this section")
    hit = next(
        (e for e in sr_entries if e.text_layer and any(sk in e.sor_section_pages for sk in section_keys)), None)
    if hit is not None:
        located = [sk for sk in section_keys if sk in hit.sor_section_pages]
        # Each located section's OWN pages, in page order — the UNION for a multi-section unit, NO ±1
        # straddle expansion. ±1 is for spec clauses (which can cross a page break); a SoR section is
        # already delimited at page granularity by _spans, so expanding it would leak the ADJACENT
        # sections' items into the sheet this firm is asked to price (and let a firm bid a section it
        # was never enquired on).
        pages = [p + 1 for p in sorted({p for sk in located for p in hit.sor_section_pages[sk]})]
        plural = "s" if len(located) > 1 else ""
        return PlanAttachment(
            source_doc=hit.filename, out_filename=_unit_out_name(trade, package_key, "-".join(located)),
            mode="sliced", pages=pages, flags=[PRICED_RETURN],
            reason=f"Schedule of Rates — Section{plural} {', '.join(located)} (the priced-return sheet for this enquiry)")
    # The SoR is present but none of this unit's sections could be located (scanned / unindexed) -> whole, flagged.
    e = sr_entries[0]
    scanned = not e.text_layer
    label = ", ".join(section_keys) or "?"
    return PlanAttachment(
        source_doc=e.filename, out_filename=_unit_out_name(trade, package_key, ""), mode="whole",
        flags=[PRICED_RETURN, "scanned_whole" if scanned else "whole_section_not_located"],
        reason=f"Schedule of Rates — whole ({'scanned' if scanned else f'Section {label} not located'})")


def resolve_section_plan(
    *, package_key: str, trade: str, section_title: str, items: list,
    doc_index: list[DocIndexEntry], sor_sheet_name: str, section: str = "",
    sections: Optional[list[str]] = None,
    page_texts_of: Optional[Callable[[str], list[str]]] = None,
) -> SectionPlan:
    """The relevant-only attachment plan for one dispatched SoR section, driven by the clause
    references its items carry (Clause Ref column). See the module docstring for the slicing rules.

    ``page_texts_of`` (filename -> cached OCR page texts) enables the DIRECTED clause search: a
    referenced clause the blind ``clause_index`` missed is located over the doc's cached text,
    engine-independent. Omitted (DEMO / no upload) -> the directed search is skipped and the plan is
    exactly the blind-index behaviour."""
    refs = refs_for_items(items)
    ps_clauses = _dedup([clause_of(r) for r in refs.get("ps", [])])
    gs_clauses = _dedup([clause_of(r) for r in refs.get("gs", [])])
    pb_clauses = [r for r in refs.get("pb", []) if r.startswith("PB ")]  # MM number form "PB 71"
    appendix_clauses = _dedup([clause_of(a) for a in refs.get("appendix", [])])

    ps_ref_specs = {spec_section_of(r) for r in refs.get("ps", []) if spec_section_of(r)}
    gs_ref_specs = {spec_section_of(r) for r in refs.get("gs", []) if spec_section_of(r)}
    relevant_ps_specs = ps_ref_specs | gs_ref_specs  # a PS section is relevant if a PS or GS clause in it is cited
    cited_appendices = {spec_section_of(a) for a in refs.get("appendix", []) if spec_section_of(a)}

    # Directed location (engine-independent): for each relevant PS doc, the referenced clauses the
    # blind clause_index missed, located by a heading search over the doc's CACHED OCR text. Each
    # doc's text is read at most once. Empty when no text reader is supplied (DEMO / no upload).
    _texts_cache: dict[str, list[str]] = {}

    def _texts(filename: str) -> list[str]:
        if page_texts_of is None:
            return []
        if filename not in _texts_cache:
            try:
                _texts_cache[filename] = page_texts_of(filename) or []
            except Exception:  # noqa: BLE001 — a text read must never fail the plan (whole-file remains)
                _texts_cache[filename] = []
        return _texts_cache[filename]

    directed_by_doc: dict[str, dict[str, list[int]]] = {}
    for e in doc_index:
        if e.kind == "particular_specification" and e.text_layer and e.spec_section_number in relevant_ps_specs:
            directed_by_doc[e.filename] = _directed_for_entry(e, ps_clauses, gs_clauses, _texts(e.filename))

    # Onward hop: a resolved PS clause may point to a SEPARATE appendix document ("refer to
    # Appendix 7.8.20"). Gather those appendix clause ids from the persisted clause_onward index
    # (a pre-pass so order in doc_index doesn't matter), and merge them into what the appendix
    # branch pulls — so the firm gets the appendix even though its SoR item only cited the PS clause.
    onward: list[str] = []
    for e in doc_index:
        if e.kind in ("particular_specification", "general_specification") and e.spec_section_number in relevant_ps_specs:
            for c in (_resolving_ps_clauses(e, ps_clauses, gs_clauses) if e.text_layer else []):
                onward += e.clause_onward_appendices.get(c, [])
            # A directed-located clause has no clause_onward_appendices entry (that is built from the
            # index at ingest) — scan its located pages' text for onward appendix refs directly, so an
            # appendix a directed-found clause points to is still pulled.
            directed = directed_by_doc.get(e.filename, {})
            if directed:
                texts = _texts(e.filename)
                for pages in directed.values():
                    span = "\n".join(texts[p] for p in pages if 0 <= p < len(texts))
                    onward += [clause_of(a) for a in extract_refs(span).get("appendix", [])]
    onward = _dedup([o for o in onward if o])
    appendix_clauses = _dedup(appendix_clauses + onward)
    cited_appendices = cited_appendices | {spec_section_of(a) for a in onward if spec_section_of(a)}

    # The unit's SoR section code(s): the caller's explicit list (a suffix-less package derives them
    # from its items) or, by default, the single ``:SECTION`` suffix. Never derive from clause refs.
    unit_sections = sections if sections is not None else ([section] if section else [])
    plan: list[PlanAttachment] = [
        _priced_return_attachment(
            doc_index, sections=unit_sections, trade=trade, package_key=package_key,
            sor_sheet_name=sor_sheet_name),
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
            blind = _resolving_ps_clauses(e, ps_clauses, gs_clauses) if e.text_layer else []
            directed = directed_by_doc.get(e.filename, {})  # referenced clauses the index missed
            for g in gs_clauses:  # a GS clause this PS doc amends — by the index OR the directed search
                if g in directed or any(k == g or base_clause(k) == g for k in e.clause_index):
                    gs_covered.add(g)
            index_pages = set(_slice_pages(e, blind)) if e.text_layer else set()
            directed_pages = set(_expand({p for pgs in directed.values() for p in pgs}, e.page_count))
            pages = sorted(index_pages | directed_pages)
            directed_ids = [c for c in directed if c not in blind]  # located ONLY by the directed search
            located = _dedup(blind + list(directed))
            # Referenced PS clauses of THIS section located nowhere (index or directed) — surfaced on
            # the (present) section so a partial gap is never silent, per the no-drop invariant.
            not_located = [c for c in ps_clauses
                           if base_clause(c).split(".")[0] == e.spec_section_number and c not in located]
            if pages:
                reason = f"PS Section {e.spec_section_number} — referenced clauses"
                if directed_ids:
                    reason += f" ({len(directed_ids)} located by directed text search: {', '.join(directed_ids)})"
                if not_located:
                    reason += f" · {len(not_located)} not located: {', '.join(not_located)}"
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages],
                    clauses=located, directed_clauses=directed_ids, clauses_not_located=not_located,
                    reason=reason))
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
