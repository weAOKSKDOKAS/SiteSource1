"""REVIEW stage 08 — citation verification (the anti-hallucination guard).

TWO guards, answering different questions:

1. ``verify_citations`` — the **parse** guard. Does the cited clause exist in the structured parse,
   and does the quoted text sit inside it? An index lookup; no PDF involved.
2. ``locate_citations`` — the **physical** guard. Can the quotation actually be found on a page of
   the document? This turns a page number the model *claimed* into one that was *measured*, and it
   yields the rectangles a viewer highlights.

The physical guard has three outcomes, not two, because a failed search has two very different
causes and lumping them together is what makes a warning worth ignoring:

* ``located`` — found. The page is measured.
* ``unverifiable`` — the part could not be searched at all: image-only, no text layer. Two parts of
  the reference 325 tender are exactly this. Saying "citation failed" here would blame the citation
  for the document's shortcoming.
* ``not_located`` — the part is searchable, **and other citations in the same part were found**, so
  the machinery demonstrably works here; this one still is not. That is a real problem.

That last condition is the important one. **Corroboration before accusation**: a citation is only
called wrong when its neighbours prove the search works on that document. Without it, any mismatch
between the parse and the file — a DEMO fixture, a re-split, the wrong upload — would condemn every
citation at once, which is both wrong and useless.


Bucket (mapping doc task 10): **Deterministic lookup**. For every register line that cites a clause,
confirm (a) the cited ``clause_id`` actually exists in the parsed document set, and (b) the quoted
``cited_text`` is contained in that clause (string/locus containment, NOT semantics). This is never
"ask the AI if the citation is right" — it is an index lookup against the structured parse s01
produced.

A line that fails either check is marked ``citation_failed`` and kept visible (never dropped). A
register that departs against a clause that does not exist is one of the worst outcomes with a
client, so this is the safeguard. Unresolved lines carry no clause and are skipped.

``verify_citations`` returns the per-line :class:`CitationCheck` results AND applies the
``citation_failed`` status to the register in place (documented side effect), so the persisted
register reflects the guard.
"""

from __future__ import annotations

import re
from pathlib import Path

from client_boq.models import (
    HUMAN_VERDICTS,
    LOCATED,
    NOT_LOCATED,
    STATUS_CITATION_FAILED,
    STATUS_UNRESOLVED,
    UNVERIFIABLE,
    CitationCheck,
    CitationLocation,
    DepartureRegister,
    Highlight,
    ParsedDocumentSet,
    PartSpec,
)

_WS = re.compile(r"\s+")

# Everything up to and including the word "Clause"/"Clauses" — a document-name prefix.
_CLAUSE_LEAD = re.compile(r"^.*?\bclauses?\b[\s:.\-]*", re.IGNORECASE)
# The separators a human (or a model writing like one) uses to name several clauses at once.
_REF_SPLIT = re.compile(r"\s*(?:;|,|&|\band\b)\s*", re.IGNORECASE)
# A trailing sub-clause limb: '4.4(b)' -> '4.4', '2.1(a)(ii)' -> '2.1'.
_SUBCLAUSE = re.compile(r"(?:\s*\([0-9a-z]{1,4}\))+\s*$", re.IGNORECASE)
# How a composite quotation joins fragments — ASCII '...' or the real ellipsis character.
# The dots must be CONTIGUOUS. Allowing whitespace between them (`\.\s*\.\s*\.`) makes the pattern
# swallow a sentence-ending period plus the first two dots of the following ellipsis — "cost
# incurred. ... There shall be" then splits into "cost incurred" and ". There shall be", and that
# stray leading period is enough to make an honest fragment fail its containment check. Found
# doing exactly that to 2 of 4 remaining lines on the live register.
_ELLIPSIS = re.compile(r"\s*(?:\.{3,}|…)\s*")


def _norm(text: str) -> str:
    """Whitespace/case-normalised text for containment comparison."""
    return _WS.sub(" ", (text or "").strip().lower())


def clause_candidates(ref: str) -> list[str]:
    """Every clause id a written reference might mean, most specific first.

    The clause index is keyed by bare ids (``'4.13'``, ``'4.4(b)'``), but the stages that produce
    register lines do not all write references that way. Measured on the first live run:

        s04 scope-align  '8.1; 2.3; 10.1'                        three clauses in one string
        s05 programme    'CIC Conditions of Tender, Clause 4.13' the document name, then the id

    An exact ``index.get()`` misses both, and the line is then reported as citing a clause that is
    "not in the document set" — which is false, and provably so: clause 4.13 RESOLVES from the
    criteria stage's ``'4.13'`` and FAILS from the programme stage's prose form, in the same
    register. Ten of seventy-five lines failed this way on the live CIC tender.

    That is worth fixing carefully rather than loosening: a citation guard that cries wolf on 13%
    of a register is one people learn to click past, and it exists to catch the case that really
    matters — a register departing against a clause that does not exist. So this only normalises
    the *lookup key*. Whether the quoted text is actually in the clause is a separate check and is
    untouched.
    """
    ref = (ref or "").strip()
    if not ref:
        return []
    # The whole string first: an index that genuinely keys on it must still win.
    out = [ref]
    body = _CLAUSE_LEAD.sub("", ref).strip()
    if body and body not in out:
        out.append(body)
    for piece in _REF_SPLIT.split(body or ref):
        piece = piece.strip().strip(".,;:")
        if not piece:
            continue
        if piece not in out:
            out.append(piece)
        # s01 indexes clauses at the numbered level — the live CIC parse holds '4.4' and '1.2',
        # never '4.4(b)' or '1.2(d)'. A sub-clause letter must fall back to its parent, or a
        # perfectly ordinary reference to a lettered limb resolves to nothing.
        parent = _SUBCLAUSE.sub("", piece).strip()
        if parent and parent != piece and parent not in out:
            out.append(parent)
    return out


def resolve_clauses(index: dict, ref: str) -> tuple[list, list[str]]:
    """Every clause the reference names that the index actually holds, and the keys used.

    Plural on purpose. A finding about a CONFLICT cites several clauses at once
    (``'1.2(d); 2.1; 4.3'``) and quotes a fragment from each, so "the clause this line cites" is
    not a single thing and pretending otherwise is what made those lines unverifiable.
    """
    clauses, keys = [], []
    for candidate in clause_candidates(ref):
        clause = index.get(candidate)
        if clause is not None and candidate not in keys:
            clauses.append(clause)
            keys.append(candidate)
    return clauses, keys


def resolve_clause(index: dict, ref: str):
    """``(clause, key)`` for the first candidate present in the index, else ``(None, "")``."""
    clauses, keys = resolve_clauses(index, ref)
    return (clauses[0], keys[0]) if clauses else (None, "")


def unsupported_fragments(quote: str, clauses: list) -> list[str]:
    """The quoted fragments that appear in NONE of the cited clauses. Empty means supported.

    A composite quotation joins fragments from different clauses with an ellipsis:

        "The tender documents consist of: ... d) Assignment Brief and its Annexes;
         ... Tenderers are invited ... to submit proposal and bid for ..."

    Asking whether all of that sits inside any ONE clause has no possible right answer — the
    fragments came from three. So each fragment is checked against the combined text of every
    clause the line cites. This is not a loosening: an invented fragment is in none of them and
    still fails, which is the thing the check exists to catch. It only stops failing honest
    quotations for a reason unrelated to whether they are true.

    A quotation with no ellipsis is one fragment, so single-clause lines behave exactly as before.
    """
    haystack = _norm("\n".join(getattr(c, "text", "") or "" for c in clauses))
    if not haystack:
        return [quote] if (quote or "").strip() else []
    missing = []
    for fragment in _ELLIPSIS.split(quote or ""):
        fragment = fragment.strip()
        if fragment and _norm(fragment) not in haystack:
            missing.append(fragment)
    return missing


def verify_citations(register: DepartureRegister, parsed: ParsedDocumentSet) -> list[CitationCheck]:
    """Verify every cited clause deterministically; mark failures ``citation_failed`` in place."""
    index = parsed.clause_index()
    checks: list[CitationCheck] = []
    for item in register.items:
        # An unresolved criterion cites no clause — nothing to verify.
        if item.status == STATUS_UNRESOLVED or not item.clause:
            continue
        # A recorded human verdict is never overwritten. `locate_citations` has always guarded
        # this (see `strict` below); this function did not, because in the normal flow it runs
        # once, before anyone has decided anything. It stops being true the moment s08 is run a
        # second time over a register someone has worked — a re-verify would silently turn a
        # person's `dismissed` into `citation_failed` and lose the decision with no trace.
        # Caught doing exactly that to two dismissed lines on the live CIC register.
        if item.status in HUMAN_VERDICTS:
            continue
        clauses, keys = resolve_clauses(index, item.clause)
        missing = unsupported_fragments(item.cited_text, clauses) if (clauses and item.cited_text) else []
        if not clauses:
            # Name what was tried, so a genuine miss stays legible rather than looking like the
            # formatting problem `clause_candidates` exists to absorb.
            tried = ", ".join(repr(c) for c in clause_candidates(item.clause))
            check = CitationCheck(
                item=item.item, clause=item.clause, found=False, supported=False,
                note=f"cited clause {item.clause!r} is not in the document set (tried {tried})",
            )
        elif missing:
            where = " / ".join(keys)
            check = CitationCheck(
                item=item.item, clause=item.clause, found=True, supported=False,
                note=(f"quoted text is not found in clause {where!r}: "
                      f"{missing[0][:80]!r}" + (f" (+{len(missing) - 1} more)" if len(missing) > 1 else "")),
            )
        else:
            check = CitationCheck(item=item.item, clause=item.clause, found=True, supported=True, note="")
        checks.append(check)
        if not check.ok:
            item.status = STATUS_CITATION_FAILED
            item.citation_note = check.note
    return checks


def locate_citations(
    register: DepartureRegister,
    parsed: ParsedDocumentSet,
    parts: list[tuple[PartSpec, str]],
    *,
    strict: bool = True,
) -> list[CitationLocation]:
    """Physically look for each cited quotation in the document it claims to come from.

    ``parts`` pairs each split part with the path of its cut PDF. Returns one location per checked
    register line, in register order, and (when ``strict``) marks a line ``citation_failed`` only
    where the corroboration rule below is satisfied.

    **Corroboration before accusation.** Within one part, a citation is called ``not_located`` only
    if at least one OTHER citation from that same part WAS located. That proves the text layer,
    the page range and the parse all line up for this document, so a remaining miss is about the
    quotation rather than the machinery. Where nothing in a part could be found, every citation in
    it is ``unverifiable`` instead — the honest reading of "we could not check", which is also
    exactly what happens offline, where the fixture parse has no relationship to the uploaded file.
    """
    from client_boq.ingest import pdfops  # local: keeps the parse-only guard free of PDF cost

    index = parsed.clause_index()
    by_part = {spec.part_id: (spec, path) for spec, path in parts}
    cache: dict[str, bytes] = {}

    def part_bytes(part_id: str) -> bytes:
        if part_id not in cache:
            _spec, path = by_part[part_id]
            file = Path(path)
            cache[part_id] = file.read_bytes() if path and file.is_file() else b""
        return cache[part_id]

    # Pass one: look for everything, and remember which parts proved searchable.
    found_in: dict[str, int] = {}
    attempts: list[tuple] = []
    for item in register.items:
        if item.status == STATUS_UNRESOLVED or not item.clause:
            continue
        # Same resolution as verify_citations, deliberately via the same helper: if these two
        # disagreed about what a reference means, a line could pass verification and then have
        # nowhere to look, or vice versa.
        clause, _key = resolve_clause(index, item.clause)
        needle = (item.cited_text or "").strip() or (getattr(clause, "text", "") or "").strip()
        part_id = getattr(clause, "part_id", "") if clause is not None else ""
        if not needle or part_id not in by_part:
            attempts.append((item, part_id, None, False))
            continue
        spec, _path = by_part[part_id]
        data = part_bytes(part_id)
        searchable = pdfops.has_text_layer(data)
        hit = pdfops.locate(data, needle, page_offset=spec.start - 1) if searchable else None
        if hit:
            found_in[part_id] = found_in.get(part_id, 0) + 1
        attempts.append((item, part_id, hit, searchable))

    # Pass two: decide, now that we know which parts the search demonstrably works on.
    locations: list[CitationLocation] = []
    for item, part_id, hit, searchable in attempts:
        if hit:
            location = CitationLocation(
                verdict=LOCATED, page=hit["page"], match=hit["match"],
                matched_text=hit["matched_text"],
                highlights=[Highlight(**h) for h in hit["highlights"]],
                note=("found on page {p}".format(p=hit["page"]) if hit["match"] == "exact"
                      else f"a distinctive fragment was found on page {hit['page']}"),
            )
        elif part_id not in by_part:
            # Either the clause carries no part, or it names one this set does not hold. Both
            # mean the same thing here: there is no document to search.
            location = CitationLocation(
                verdict=UNVERIFIABLE,
                note="this line cites no clause that maps to a split part, so there is nowhere to look",
            )
        elif not searchable:
            location = CitationLocation(
                verdict=UNVERIFIABLE,
                note=("the part this clause comes from has no text layer, so the quotation could "
                      "not be searched for. Read the page to check it."),
            )
        elif found_in.get(part_id):
            location = CitationLocation(
                verdict=NOT_LOCATED,
                note=("this quotation was not found in the part it cites, although other "
                      "citations from the same part were found. The wording is likely a "
                      "paraphrase rather than a quotation."),
            )
        else:
            location = CitationLocation(
                verdict=UNVERIFIABLE,
                note=("no citation from this part could be located, so the parse and the file may "
                      "not correspond. Not treated as a citation failure."),
            )
        location = location.model_copy(update={"page": location.page})
        locations.append(location)

        if strict and location.verdict == NOT_LOCATED and item.status not in HUMAN_VERDICTS:
            item.status = STATUS_CITATION_FAILED
            item.citation_note = location.note
        # A measured page beats a claimed one, always.
        if location.verdict == LOCATED and location.page:
            item.page = location.page
    return locations
