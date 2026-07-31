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


def _norm(text: str) -> str:
    """Whitespace/case-normalised text for containment comparison."""
    return _WS.sub(" ", (text or "").strip().lower())


def verify_citations(register: DepartureRegister, parsed: ParsedDocumentSet) -> list[CitationCheck]:
    """Verify every cited clause deterministically; mark failures ``citation_failed`` in place."""
    index = parsed.clause_index()
    checks: list[CitationCheck] = []
    for item in register.items:
        # An unresolved criterion cites no clause — nothing to verify.
        if item.status == STATUS_UNRESOLVED or not item.clause:
            continue
        clause = index.get(item.clause)
        if clause is None:
            check = CitationCheck(
                item=item.item, clause=item.clause, found=False, supported=False,
                note=f"cited clause {item.clause!r} is not in the document set",
            )
        elif item.cited_text and _norm(item.cited_text) not in _norm(clause.text):
            check = CitationCheck(
                item=item.item, clause=item.clause, found=True, supported=False,
                note=f"quoted text is not found in clause {item.clause!r}",
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
        clause = index.get(item.clause)
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
