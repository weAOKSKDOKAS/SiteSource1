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

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    _FILENAME_APPENDIX,
    _FILENAME_PS_SECTION,
    _own_name,
)
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

# The dispatched priced-return document is NOT the artifact the design intends. The design sends
# the ORIGINAL Schedule of Rates, sliced to this unit's section pages, because a subcontractor
# returns what they were sent and the return format follows the dispatch format. This flag marks
# every case where something else went out instead — and it exists because the substitution was
# silent: on CEDD ND/2025/04 the draft carried `SoR_ground-investigation-4.xlsx` (7K) and nothing
# on the gate said the original bill had not been sliced, or why.
#
# The gate shows it BEFORE anything is drafted, and the operator decides. That is the whole of the
# fix: not "never substitute" — sometimes there is genuinely nothing to slice — but "never
# substitute quietly".
SUBSTITUTED = "substituted_priced_return"

# THE FULL SPECIFICATION WENT OUT BECAUSE NOTHING ESTABLISHED WHICH PART OF IT APPLIES.
#
# This issuer's Bill of Quantities has no Clause Ref column, so no item cites a clause and
# ``relevant_ps_specs`` came out empty — which attached NO specification at all. Two different
# trades then received identical bundles, neither containing the document that governs the work.
#
# Sending too much is wasteful and visible. Sending nothing is a firm pricing without the
# specification, and it looks exactly like a correct, tidy enquiry. So the fallback is to enclose
# the whole thing, flagged, and the flag is the invitation to confirm a mapping and stop paying for
# it — never a substitute for confirming one.
NO_RELEVANCE_ESTABLISHED = "no_relevance_established"

# The caller's string resolved to no tender at all. Distinct from "the index is empty" and from "the
# index is missing", and it is the state that produced six rounds of the same bug report: a lookup
# that went to a directory that was never going to exist, reported as though the pack were empty.
UNREGISTERED_TENDER = "<unregistered>"


class MissingSpec(BaseModel):
    spec: str          # e.g. "PS Section 28"
    referenced_by: str  # "SoR references" | "topic map"


class SectionPlan(BaseModel):
    package_key: str = ""
    section: str = ""
    attachments: list[PlanAttachment] = Field(default_factory=list)
    missing_specs: list[MissingSpec] = Field(default_factory=list)
    # HOW the specification set was chosen, for the gate to state plainly:
    #   "clause_refs"    the items cite clauses — the design's intent, and it always wins
    #   "confirmed_map"  a person confirmed which PS section governs this bill section
    #   "none"           neither — the full specification is enclosed (NO_RELEVANCE_ESTABLISHED)
    #   ""               no specification was in play at all
    relevance_source: str = ""


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


def _slice_pages(entry: DocIndexEntry, clauses: list[str], *, straddle: bool = True) -> list[int]:
    """0-based pages spanned by a set of clause ids. ``clause_index`` maps a clause to the pages it
    spans. ``straddle`` (default) expands each page ±1 so a spec clause whose body crosses a page
    break (and whose marker can sit mid-clause) stays whole — right for PS/GS/appendix. The Method of
    Measurement passes ``straddle=False``: a PB preamble clause's span is already page-precise
    (``_spans`` captures a genuine cross-break PB as multiple pages), so ±1 would only pull the
    adjacent, irrelevant pages around it."""
    hits: set[int] = set()
    for c in clauses:
        hits.update(entry.clause_index.get(c, []))
    if not hits:
        return []
    return _expand(hits, entry.page_count) if straddle else sorted(hits)


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


# The revision suffix an issuer puts on a reissued document: `…-S_PS28-0.pdf` is the original,
# `-1` the addendum's replacement. Read off the STEM, so a folder like `TA #1/` cannot be mistaken
# for one.
_REVISION_SUFFIX = re.compile(r"-(\d{1,2})$")

# Named so it can be quoted on the gate rather than assumed. THE SUFFIX IS THE ONLY EVIDENCE the
# pack carries: an addendum's replacement declares no revision inside the document, so precedence
# cannot be established from the text. It is stated, not buried.
REVISION_ASSUMPTION = (
    "the -0/-1 filename suffix is the only revision evidence in this pack; the document declares "
    "none inside itself"
)
SUPERSEDED_BY_ADDENDUM = "supersedes_earlier_revision"


def _doc_revision(filename: str) -> int:
    """The revision a filename claims (``…-S_PS28-1.pdf`` -> 1), or 0 when it claims none."""
    stem = (filename or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = _REVISION_SUFFIX.search(stem)
    return int(m.group(1)) if m else 0


def _effective_kind(e: DocIndexEntry) -> str:
    """The kind this document ACTUALLY is, read off its own name — not the kind stored for it.

    Every ``doc_index.json`` written before a classifier learned something carries the old answer,
    and a 232 MB pack is not re-split to correct a string. Two corrections, both keyed on the
    file's OWN basename so no folder can decide:

    * ``PSA…`` stored as a specification is an APPENDIX. `_APPENDIX_COVER` needs a bare
      "Appendix N", so a PSA file declaring only the dotted form was classified a specification and
      competed in `_ps_revisions` as if it WERE the section it appends to.
    * ``…PS25-1.pdf`` stored as a CLARIFICATION is a specification section. It lives under
      ``TA #1/``, `_ADDENDUM` matched the folder, and the reissue went whole to every firm through
      the clarification branch without ever meeting the ``-0`` it supersedes.

    A genuine addendum letter names no section, so neither rule touches it and it stays a
    clarification issued to everyone.
    """
    own = _own_name(e.filename)
    if e.kind == "particular_specification" and _FILENAME_APPENDIX.search(own):
        return "appendix"
    if e.kind == "clarification":
        if _FILENAME_APPENDIX.search(own):
            return "appendix"
        if _FILENAME_PS_SECTION.search(own):
            return "particular_specification"
    return e.kind


def _competes_as_a_specification(e: DocIndexEntry) -> bool:
    """Whether this entry may compete to BE a PS section, as opposed to belonging to one.

    TWO independent guards, and neither can be fooled by a folder — which is the whole point, since
    the pack files `I-ND_2025_04-S_PSA7.12-0.pdf` under `S/PS/PS7/` and the section number used to
    be read off that path:

    * ``kind`` — an appendix is not a specification. Necessary but NOT sufficient on its own:
      `_APPENDIX_COVER` needs a BARE "Appendix N", so a PSA file declaring only the dotted
      "Appendix 7.12" (or nothing) was classified `particular_specification` and competed.
    * the issuer's own ``PSA`` token on the file's OWN NAME. This is the marker that distinguishes
      the two names, and reading the basename is what makes the folder irrelevant.

    Not "require a page-1 SECTION declaration": that would be the strictest rule and it would undo
    the identity fix. PS28's page 1 declares nothing — the filename is the only evidence it has —
    so demanding a declaration would drop the specification this whole path exists to deliver.
    """
    return (
        e.kind == "particular_specification"
        and not _FILENAME_APPENDIX.search(_own_name(e.filename))
    )


def _ps_revisions(
    doc_index: list[DocIndexEntry],
) -> tuple[set[str], dict[str, int], list[tuple[str, str]]]:
    """``(filenames superseded, section -> the revision that won, contested pairs)``.

    AN ADDENDUM REVISES A SECTION; IT DOES NOT DELETE THE REST. Two consequences, and the second is
    the one that was broken:

    * where a section WAS reissued, the highest revision is the operative document and the earlier
      one is not enclosed — a firm pricing against a superseded specification is pricing the wrong
      scope, and it must not receive both with nothing to tell them apart;
    * where a section was NOT reissued, the ``-0`` original is the only version and IS enclosed.
      PS28 was reaching an enquiry as neither, because it was never identified at all (see
      ``doc_index._FILENAME_SECTION``); once identified, this must not then drop it for having no
      addendum.

    Only revisions of the SAME section compete, and only a genuine specification competes at all —
    see :func:`_competes_as_a_specification`. The pack ships a revised APPENDIX
    (`TA #1/…-S_PSA1.12-1.pdf`) beside the revised SPECIFICATION (`TA #1/…-S_PS1-1.pdf`); both once
    resolved to section 1 at revision 1, `rev > current[0]` is strict, and so WHICHEVER THE INDEX
    LISTED FIRST WON. Reversing the list handed the firm an appendix and not the section it appends
    to, with nothing on the gate to say so.

    A TIE IS NOT BROKEN BY LIST ORDER. Two documents claiming one section at one revision is a fact
    about the pack, not a coin flip: the winner is the lexicographically smallest filename — chosen
    only because it is stable and independent of how the index happened to be built — and every
    contested pair is returned so the gate can name the one that was set aside.
    """
    return _revision_contest(doc_index, _competes_as_a_specification)


def _revision_key(e: DocIndexEntry) -> str:
    """What two documents must agree on to be revisions OF EACH OTHER.

    For a specification or a measurement section that is the SECTION NUMBER: `TA #1/…-S_PS1-1.pdf`
    and `S/PS/…-S_PS1-0.pdf` are section 1 at two revisions.

    An APPENDIX cannot use it. Its `spec_section_number` is its PARENT'S — `PSA1.12` and `PSA1.13`
    are both "section 1" — so a contest keyed on the section number would have twenty-five
    appendices of PS 1 all claiming one identity and superseding each other. Its identity is its own
    name with the revision suffix removed, which is exactly what a reissue keeps.
    """
    if e.kind != "appendix":
        return e.spec_section_number
    stem = _own_name(e.filename).rsplit(".", 1)[0]
    return _REVISION_SUFFIX.sub("", stem) or stem


def _revision_contest(
    doc_index: list[DocIndexEntry], competes: Callable[[DocIndexEntry], bool],
) -> tuple[set[str], dict[str, int], list[tuple[str, str]]]:
    """THE precedence rule, once, for whichever population ``competes`` admits.

    Extracted from :func:`_ps_revisions` when the Method of Measurement needed exactly the same
    contest — the pack ships `TA #1/GP&PP/…-SMM_S02-1.pdf` beside the `-0`, and both were enclosed
    with identical reasons. A second copy of "highest revision wins, ties by filename, losers
    reported" would be a second place to drift; there is already a documented cost to having had
    one contest behind two doors.

    Only documents of the SAME population and the SAME section number compete: a Method of
    Measurement section 2 does not contest a Particular Specification section 2, and the two
    numbering systems mean nothing to each other.
    """
    by_section: dict[str, list[tuple[int, str]]] = {}
    for e in doc_index:
        key = _revision_key(e)
        if not key or not competes(e):
            continue
        by_section.setdefault(key, []).append((_doc_revision(e.filename), e.filename))

    best: dict[str, tuple[int, str]] = {}
    contested: list[tuple[str, str]] = []
    for section, entries in by_section.items():
        top = max(rev for rev, _fn in entries)
        at_top = sorted(fn for rev, fn in entries if rev == top)
        best[section] = (top, at_top[0])
        contested += [(at_top[0], loser) for loser in at_top[1:]]

    winners = {fn for _rev, fn in best.values()}
    superseded = {
        e.filename for e in doc_index
        if _revision_key(e) and competes(e) and e.filename not in winners
    }
    revised = {sec: rev for sec, (rev, _fn) in best.items() if rev > 0}
    return superseded, revised, contested


def _why_no_bill(doc_index: list[DocIndexEntry], index_source: str) -> str:
    """WHICH of the four things actually happened — never a guess between them.

    The message used to read "no Schedule of Rates PDF is indexed for this tender (none uploaded, or
    the bill is a workbook, which has no pages to slice)" while a 156 KB index containing one sat on
    disk for that tender. BOTH stated causes were false, and the real one — the wrong directory —
    was not among the options offered. An operator reading it had no way to tell a genuinely empty
    pack from a lookup that went somewhere else.

    Four states, and they are distinguishable from what is in hand:

    * the name is registered to no tender          -> nothing was ever going to be found;
    * an index was searched for and is not there   -> the tender exists, this run has not indexed it;
    * the index is there and holds no bill         -> the pack genuinely has no Schedule of Rates;
    * the index holds a bill with no text layer    -> it is a workbook or a scan, with no pages to
      slice, which is the ONLY case the old sentence's second half was ever about.
    """
    from pathlib import Path

    sr = [e for e in doc_index if e.kind == "schedule_of_rates"]
    if sr:
        return (f"the indexed Schedule of Rates ({sr[0].filename}) has no text layer, so it has no "
                f"pages to slice — a workbook or a scan.")
    if index_source == UNREGISTERED_TENDER:
        return ("this name is not registered to any tender, so no workspace was searched. Register "
                "the tender's names, or dispatch under the name its documents were indexed under.")
    if not index_source:
        return "no document index was supplied to this plan."
    if not Path(index_source).is_file():
        return (f"no document index exists at {index_source} — this tender has not been indexed by "
                f"this run.")
    return (f"the document index at {index_source} contains no Schedule of Rates: the pack that was "
            f"indexed carries none.")


def _priced_return_attachment(
    doc_index: list[DocIndexEntry], *, sections: list[str], trade: str, package_key: str, sor_sheet_name: str,
    index_source: str = "",
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
        # No original Schedule of Rates in the run's doc index. Reachable three ways: DEMO, no
        # upload at all, or a genuinely workbook-only bill (`doc_index._pages_text` returns None
        # for a non-PDF, so an .xlsx is indexed with `text_layer=False` and no section pages).
        #
        # CORRECTION — an earlier version of this comment named ND/2025/04's workbook bill as the
        # cause, and that was WRONG. On that pack the index was empty because the bridge never
        # PERSISTED one: it built a doc index in `bridge/scope.py`, read `sor_section_pages` off it
        # for the provenance guard, and discarded it, while `save_doc_index`'s only call site was
        # `/ingest-upload`. So every archive/bridge tender reached this branch unconditionally —
        # the pack ships `I-ND_2025_04_BQ-0.pdf` beside the workbook and it would have been
        # discarded just the same. Fixed in FIX 10; the diagnosis is corrected here so the wrong
        # one is not left as a landmark.
        return PlanAttachment(
            source_doc=sor_sheet_name, mode="generated", flags=[PRICED_RETURN, SUBSTITUTED],
            reason=(
                "GENERATED sheet, not the original bill — " + _why_no_bill(doc_index, index_source)
                + " The firm will be asked to price this .xlsx and will return a workbook."
            ))
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
        flags=[PRICED_RETURN, SUBSTITUTED,
               "scanned_whole" if scanned else "whole_section_not_located"],
        reason=(
            f"WHOLE bill, not this unit's section — "
            + ("the Schedule of Rates has no text layer (scanned), so its section pages cannot be "
               "located." if scanned else
               f"Section {label} could not be located in the Schedule of Rates' section index.")
            + " The firm receives the entire bill and may price sections it was not enquired on."
        ))


def resolve_section_plan(
    *, package_key: str, trade: str, section_title: str, items: list,
    doc_index: list[DocIndexEntry], sor_sheet_name: str, section: str = "",
    sections: Optional[list[str]] = None,
    page_texts_of: Optional[Callable[[str], list[str]]] = None,
    confirmed_ps_specs: Optional[set[str]] = None,
    unconfirmed_sections: Optional[list[str]] = None,
    index_source: str = "",
) -> SectionPlan:
    """The relevant-only attachment plan for one dispatched SoR section, driven by the clause
    references its items carry (Clause Ref column). See the module docstring for the slicing rules.

    ``page_texts_of`` (filename -> cached OCR page texts) enables the DIRECTED clause search: a
    referenced clause the blind ``clause_index`` missed is located over the doc's cached text,
    engine-independent. Omitted (DEMO / no upload) -> the directed search is skipped and the plan is
    exactly the blind-index behaviour.

    ``confirmed_ps_specs`` is the operator-CONFIRMED bill-section -> PS-section mapping for this
    unit (``bridge/spec_map.py``), and it is a FALLBACK, not a replacement: where the items cite
    clauses those still decide everything, exactly as before. It is consulted only when they cite
    none, which is the case for an issuer whose bill has no Clause Ref column. An unconfirmed
    proposal never reaches here — the caller passes what a person confirmed, or nothing.

    ``unconfirmed_sections`` names this unit's bill sections that have NO confirmation, so a
    PARTIAL map is visible on the gate. A unit spanning bills 1 and 9 with only bill 9 confirmed
    encloses PS 27 and says bill 1 is still unmapped — it does not fall back to the whole
    specification, which would bury the one section somebody actually decided."""
    # THE EFFECTIVE KINDS, APPLIED ONCE AND FIRST — so this function has exactly ONE view of the
    # index. It used to run just before the attachment loop, which left every read ABOVE it on the
    # stored kinds: `all_ps_sections` and `withheld_appendices` both did, so a document that
    # `_effective_kind` rescues (a `-1` reissue stored as a `clarification`, a `PSA` stored as a
    # specification) was absent from the relevant set and then dropped at a bare `continue` in the
    # loop that had already reclassified it. Two views of one list inside one function is the same
    # producer/consumer disagreement as any other seam — it was just close enough together to look
    # like it could not happen.
    doc_index = [e.model_copy(update={"kind": k}) if (k := _effective_kind(e)) != e.kind else e
                 for e in doc_index]

    refs = refs_for_items(items)
    ps_clauses = _dedup([clause_of(r) for r in refs.get("ps", [])])
    gs_clauses = _dedup([clause_of(r) for r in refs.get("gs", [])])
    pb_clauses = [r for r in refs.get("pb", []) if r.startswith("PB ")]  # MM number form "PB 71"
    appendix_clauses = _dedup([clause_of(a) for a in refs.get("appendix", [])])

    ps_ref_specs = {spec_section_of(r) for r in refs.get("ps", []) if spec_section_of(r)}
    gs_ref_specs = {spec_section_of(r) for r in refs.get("gs", []) if spec_section_of(r)}
    cited_ps_specs = ps_ref_specs | gs_ref_specs  # a PS section is relevant if a PS or GS clause in it is cited
    cited_appendices = {spec_section_of(a) for a in refs.get("appendix", []) if spec_section_of(a)}

    # WHERE THE RELEVANT SET COMES FROM — three sources, strictly ordered, and only the source
    # changes. Everything downstream of here slices and reports exactly as it did before.
    #
    # 1. The items' own clause references. The design's intent, and it always wins where it exists.
    # 2. A CONFIRMED bill-section -> PS-section mapping. A fallback for an issuer whose bill carries
    #    no Clause Ref column at all, and only ever what a person confirmed.
    # 3. Neither: the full Particular Specification, whole and flagged. See NO_RELEVANCE_ESTABLISHED
    #    — the alternative was attaching nothing, which is what shipped identical bundles to
    #    different trades with no specification in either.
    all_ps_sections = {e.spec_section_number for e in doc_index
                       if e.kind == "particular_specification" and e.spec_section_number}
    whole_spec_sections: set[str] = set()
    if cited_ps_specs:
        relevant_ps_specs, relevance_source = cited_ps_specs, "clause_refs"
    elif confirmed_ps_specs:
        relevant_ps_specs, relevance_source = set(confirmed_ps_specs), "confirmed_map"
    else:
        relevant_ps_specs, relevance_source = all_ps_sections, ("none" if all_ps_sections else "")
        whole_spec_sections = set(all_ps_sections)
    # ─────────────────────────────────────────────────────────────────────────────────────────────
    # THE INVARIANT: ANYTHING SELECTED BY CLAUSE REFERENCE IS CLOSED WHEN THERE ARE NO CLAUSE
    # REFERENCES. Every branch below is checked against it, once, here:
    #
    #   clarification / general_specification   not clause-driven — issued to all firms, always.
    #   method_of_measurement                   TWO sources. `pb_clauses` (clause-driven, closed);
    #                                           and the bill's own SMM section heading, which is
    #                                           NOT a clause and stays open under every source.
    #   particular_specification                driven by `relevant_ps_specs`, whose source is
    #                                           chosen above — clauses, a confirmed map, or all.
    #   appendix                                clause-driven on BOTH its inputs (`cited_appendices`
    #                                           comes from the items' refs; the parent-section route
    #                                           only makes sense when a clause picked the parent).
    #                                           CLOSED unless clauses drove the selection.
    #   GS amendments (`gs_covered`, `onward`)  clause-driven throughout; naturally empty with no
    #                                           clauses, and nothing is reported missing.
    #
    # The appendix branch is why this is written down. `- whole_spec_sections` closed it on the
    # fallback path only, so under a CONFIRMED map all 25 appendices of PS 1 qualified — a firm
    # received twenty-five appendices narrowed by nothing.
    appendix_relevant_specs = relevant_ps_specs if relevance_source == "clause_refs" else set()
    # What the invariant withheld, so the gate can say so rather than leave a silent absence.
    withheld_appendices = [e for e in doc_index
                           if e.kind == "appendix" and e.spec_section_number
                           and e.spec_section_number in relevant_ps_specs
                           and e.spec_section_number not in appendix_relevant_specs]

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
        # No clause was cited -> there is nothing for a directed search to look for, and reading
        # every PS document's cached text to find nothing is the whole-specification fallback's
        # cost paid twice.
        if not (ps_clauses or gs_clauses):
            break
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
    # The measurement rules each dispatched bill section is priced under, read off the bill's OWN
    # pages (`doc_index.bill_mm_sections`). Number-to-number, and correct here: both are SMM
    # numbers. NOT the Particular Specification rule — see `_BILL_MM_REFERENCE` for why the two must
    # never be merged. Open under every relevance source, because a heading is not a clause.
    mm_ref_sections = _dedup([n for e in doc_index if e.kind == "schedule_of_rates"
                              for code in unit_sections for n in e.bill_mm_sections.get(code, [])])
    plan: list[PlanAttachment] = [
        _priced_return_attachment(
            doc_index, sections=unit_sections, trade=trade, package_key=package_key,
            sor_sheet_name=sor_sheet_name, index_source=index_source),
    ]
    present_ps: set[str] = set()
    present_appendices: set[str] = set()
    mm_present: set[str] = set()     # SMM sections the bill named AND the pack supplies
    gs_covered: set[str] = set()  # GS clauses a present PS doc amends
    unidentified_ps: list[str] = []               # present, but no section could be resolved
    superseded_ps, revised_ps, contested_ps = _ps_revisions(doc_index)
    # THE SAME CONTEST, for the Method of Measurement. The pack ships
    # `TA #1/GP&PP/…-SMM_S02-1.pdf` beside the `-0`, and both were enclosed with identical reasons
    # and nothing saying which governs — the PS branch's defect, repeated on this branch because
    # only the PS branch consulted the rule. One rule now, two populations: see `_revision_contest`.
    superseded_mm, revised_mm, contested_mm = _revision_contest(
        doc_index, lambda e: e.kind == "method_of_measurement")
    # AND THE APPENDICES. Every population that can ship a `-1` beside its `-0` needs the contest,
    # and this one did not have it: the pack reissues `PSA1.12-1` under `TA #1/`, so both revisions
    # were enclosed with byte-identical reasons and nothing to tell a firm which governs.
    superseded_app, revised_app, contested_app = _revision_contest(
        doc_index, lambda e: e.kind == "appendix")

    for e in doc_index:
        if e.kind == "clarification":
            plan.append(PlanAttachment(source_doc=e.filename, mode="whole", reason="Clarification / addendum — issued to all firms"))
        elif e.kind == "general_specification":
            plan.append(PlanAttachment(source_doc=e.filename, mode="whole", reason="General Specification — issued to all firms"))
        elif e.kind == "method_of_measurement":
            if e.filename in superseded_mm:
                continue  # an addendum reissued this measurement section — see `_revision_contest`
            mm_rev = revised_mm.get(e.spec_section_number, 0)
            mm_note = (
                f" · Rev {mm_rev}, superseding the earlier revision of this section "
                f"({REVISION_ASSUMPTION})" if mm_rev else ""
            )
            mm_flags = [SUPERSEDED_BY_ADDENDUM] if mm_rev else []
            # RELEVANT, not merely present. With a PB clause cited this branch had no filter at
            # all, so every Method-of-Measurement document in the pack was enclosed — each under a
            # description ("referenced preamble clauses") that was untrue of most of them. A
            # measurement section is relevant when the BILL names it or when it actually carries a
            # cited preamble clause; anything else is another section's rulebook.
            if pb_clauses and e.spec_section_number and mm_ref_sections:
                if (e.spec_section_number not in mm_ref_sections
                        and not any(c in e.clause_index for c in pb_clauses)):
                    continue
            if not pb_clauses:
                # No preamble clause cited — but the BILL names the measurement section it is
                # priced under, on its own pages, and that section ships in the pack. A firm
                # pricing Bill 2's "moving rigs" needs SMM Section 2 to know what the rate is
                # deemed to include; without it the rate is a guess against unstated rules.
                if e.spec_section_number and e.spec_section_number in mm_ref_sections:
                    mm_present.add(e.spec_section_number)
                    many = len(unit_sections) > 1
                    bills = ((f"Bill{'s' if many else ''} " + ", ".join(unit_sections))
                             if unit_sections else "this unit")
                    plan.append(PlanAttachment(
                        source_doc=e.filename, mode="whole",
                        reason=(f"Method of Measurement Section {e.spec_section_number} — the "
                                f"measurement rules {bills} {'are' if many else 'is'} priced "
                                f"under, named on the bill's own pages ({e.page_count} pages)"
                                + mm_note),
                        flags=(["scanned_whole"] if not e.text_layer else []) + mm_flags))
                continue  # no preamble clause to slice on either way
            # PRESENT is present, whichever branch enclosed it. `mm_present` was written only in
            # the branch above, so a unit that cites a PB clause reported every SMM section the
            # bill names as MISSING FROM THE PACK — about documents this very loop was attaching.
            if e.spec_section_number:
                mm_present.add(e.spec_section_number)
            resolved = [c for c in pb_clauses if c in e.clause_index]
            # No ±1: a PB clause's page span is already precise; ±1 only pulls neighbouring pages.
            pages = _slice_pages(e, resolved, straddle=False) if e.text_layer else []
            if pages:
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages], clauses=resolved,
                    reason="Method of Measurement — referenced preamble clauses" + mm_note,
                    flags=mm_flags))
            else:
                scanned = not e.text_layer
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole", clauses=pb_clauses,
                    reason=(f"Method of Measurement — whole "
                            f"({'scanned' if scanned else 'clause not located'})" + mm_note),
                    flags=(["scanned_whole"] if scanned else ["whole_clause_not_located"]) + mm_flags))
        elif e.kind == "particular_specification":
            if not e.spec_section_number:
                # PRESENT BUT UNIDENTIFIABLE. Page 1 declared no section and the filename convention
                # did not resolve one, so nothing can say whether this document is referenced. It is
                # not attached — attaching an unknown specification to an enquiry is worse than not
                # — but it is NAMED below rather than dropped at a bare `continue`.
                unidentified_ps.append(e.filename)
                continue
            if e.spec_section_number not in relevant_ps_specs:
                continue  # this PS section is not referenced by the dispatched section
            if e.filename in superseded_ps:
                continue  # an addendum reissued this section — see `superseded_ps`
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
            # WHICH VERSION, on the gate, before anything is drafted. A firm pricing against a
            # superseded specification is pricing the wrong scope, and the operator must be able to
            # see which revision went out — including the assumption that decided it.
            rev = revised_ps.get(e.spec_section_number, 0)
            rev_note = (
                f" · Rev {rev}, superseding the earlier revision of this section ({REVISION_ASSUMPTION})"
                if rev else ""
            )
            rev_flags = [SUPERSEDED_BY_ADDENDUM] if rev else []
            if pages:
                reason = f"PS Section {e.spec_section_number} — referenced clauses"
                if directed_ids:
                    reason += f" ({len(directed_ids)} located by directed text search: {', '.join(directed_ids)})"
                if not_located:
                    reason += f" · {len(not_located)} not located: {', '.join(not_located)}"
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages],
                    clauses=located, directed_clauses=directed_ids, clauses_not_located=not_located,
                    reason=reason + rev_note, flags=rev_flags))
            elif e.spec_section_number in whole_spec_sections:
                # Nothing was cited and nothing confirmed, so no clause was ever LOOKED for here —
                # saying "clause not located" would be a false report about a search that never ran.
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole",
                    reason=(f"PS Section {e.spec_section_number} — whole ({e.page_count} pages). No "
                            "per-item relevance established: this bill cites no clauses and no "
                            "specification mapping is confirmed, so the full specification is "
                            "enclosed." + rev_note),
                    flags=[NO_RELEVANCE_ESTABLISHED] + (["scanned_whole"] if not e.text_layer else []) + rev_flags))
            elif relevance_source == "confirmed_map":
                # SELECTED, not fallen back to. Saying "no mapping is confirmed" here was the
                # false sentence on the gate: one IS confirmed, and it is why this document is in
                # the bundle. There is simply no clause reference to slice it down to.
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole",
                    reason=(f"PS Section {e.spec_section_number} — whole ({e.page_count} pages). "
                            "Selected by the CONFIRMED specification map for this bill section; "
                            "the bill cites no clauses, so there is nothing to slice to." + rev_note),
                    flags=(["scanned_whole"] if not e.text_layer else []) + rev_flags))
            else:
                scanned = not e.text_layer
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole",
                    reason=(f"PS Section {e.spec_section_number} — whole "
                            f"({'scanned' if scanned else 'clause not located'})" + rev_note),
                    flags=(["scanned_whole"] if scanned else ["whole_clause_not_located"]) + rev_flags))
        elif e.kind == "appendix":
            if not (e.spec_section_number and (e.spec_section_number in cited_appendices or e.spec_section_number in appendix_relevant_specs)):
                continue
            if e.filename in superseded_app:
                continue  # an addendum reissued this appendix — the `-1` is enclosed instead
            app_rev = revised_app.get(_revision_key(e), 0)
            app_note = (f" · Rev {app_rev}, superseding the earlier revision of this appendix "
                        f"({REVISION_ASSUMPTION})" if app_rev else "")
            app_flags = [SUPERSEDED_BY_ADDENDUM] if app_rev else []
            present_appendices.add(e.spec_section_number)
            pages = _slice_pages(e, appendix_clauses) if e.text_layer else []
            if pages:
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="sliced", pages=[p + 1 for p in pages], clauses=appendix_clauses,
                    reason=f"Appendix {e.spec_section_number} — referenced pages" + app_note,
                    flags=app_flags))
            else:
                scanned = not e.text_layer
                plan.append(PlanAttachment(
                    source_doc=e.filename, mode="whole",
                    reason=(f"Appendix {e.spec_section_number} — whole "
                            f"({'scanned' if scanned else 'referenced'})" + app_note),
                    flags=(["scanned_whole"] if scanned else []) + app_flags))

    missing: list[MissingSpec] = [
        MissingSpec(spec=f"PS Section {spec}", referenced_by="SoR references")
        for spec in sorted(ps_ref_specs - present_ps)
    ]
    # A section a PERSON CONFIRMED, with no document enclosed for it. Reported for the same reason
    # the line above exists, and it had no equivalent: `ps_ref_specs` is the CLAUSE-cited set, so on
    # a bill that cites nothing a confirmed section whose document is absent — or misfiled, or
    # classified as something else — went missing in complete silence. Absent must never be a state
    # a confirmed mapping can reach without saying so.
    if relevance_source == "confirmed_map":
        missing += [MissingSpec(spec=f"PS Section {spec}",
                                referenced_by="confirmed specification map, no document enclosed")
                    for spec in sorted(relevant_ps_specs - present_ps)]
    # A Particular Specification that IS in the pack and could not be identified. Distinct from the
    # line above, which says a referenced section is absent: this one says a document is present and
    # unusable, which is a different thing to go and look at. It used to be a bare `continue`.
    for fn in unidentified_ps:
        missing.append(MissingSpec(
            spec=f"{fn} — a Particular Specification with no identifiable section number",
            referenced_by="present in the pack, not enclosed"))
    # Two documents claiming ONE section at ONE revision. The winner is picked deterministically
    # (lexicographic filename), never by index order — but which one lost is a fact about the pack
    # that the operator has to see, not a decision to make quietly.
    for winner, loser in contested_ps + contested_mm + contested_app:
        missing.append(MissingSpec(
            spec=f"{loser} — claims the same section and revision as {winner}, which was enclosed",
            referenced_by="contested revision, resolved by filename order"))
    # A GS clause with no present PS amendment: the base General Specification text is not
    # enclosed — surface it so the human decides, never a silent omission.
    for g in gs_clauses:
        if g not in gs_covered:
            missing.append(MissingSpec(spec=f"General Specification {g}", referenced_by="SoR references"))
    # An appendix referenced (by an item directly, or onward from a PS clause) but with no matching
    # appendix document present — flagged, not silently dropped.
    for app_sec in sorted(cited_appendices - present_appendices):
        missing.append(MissingSpec(spec=f"Appendix {app_sec}", referenced_by="SoR references"))
    # ONE line on the gate for the whole-specification fallback, not one per enclosed section. It is
    # a single fact about this unit — nothing established which part of the specification applies —
    # and repeating it beside every section would read as thirty problems instead of one decision to
    # make. Named here rather than left implicit in the attachment flags because ``missing_specs``
    # is where the operator looks for what still needs a human.
    if present_ps and whole_spec_sections & present_ps:
        missing.append(MissingSpec(
            spec=(f"No per-item relevance established — the full specification is enclosed "
                  f"({len(whole_spec_sections & present_ps)} PS sections, whole)"),
            referenced_by="this bill cites no clauses and no specification mapping is confirmed"))
    # A PARTIALLY confirmed unit. The confirmed sections were selected; these were not, and the
    # operator is the only one who can close the gap. Named rather than silently absent, and
    # deliberately NOT a reason to discard the confirmations that do exist.
    # A measurement section the bill NAMES and the pack does not supply. Named, never silently
    # omitted: a firm pricing under rules nobody enclosed is pricing against unstated terms.
    for smm in [s for s in mm_ref_sections if s not in mm_present]:
        missing.append(MissingSpec(
            spec=f"Method of Measurement Section {smm}",
            referenced_by="named on the bill's own pages, no matching SMM document in the pack"))
    # What the clause-reference invariant withheld. Counted, named, and given its page total, so an
    # operator can see the size of what they would be sending if they narrowed it — and choose.
    if withheld_appendices:
        by_section: dict[str, list[DocIndexEntry]] = {}
        for e in withheld_appendices:
            by_section.setdefault(e.spec_section_number, []).append(e)
        for sec, entries in sorted(by_section.items()):
            pages = sum(e.page_count for e in entries)
            missing.append(MissingSpec(
                spec=(f"{len(entries)} appendices of PS {sec} available, not enclosed "
                      f"({pages} pages) — no clause reference narrows them"),
                referenced_by="an appendix is selected by citation; this bill cites none"))
    if relevance_source == "confirmed_map" and unconfirmed_sections:
        for code in unconfirmed_sections:
            missing.append(MissingSpec(
                spec=f"Bill section {code} — no specification mapping confirmed",
                referenced_by="confirm it on the specification map, or its scope goes unspecified"))
    return SectionPlan(package_key=package_key, section=section, attachments=plan,
                       missing_specs=missing, relevance_source=relevance_source)


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
