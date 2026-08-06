"""Propose a Particular Specification section for a bill section — by TITLE, never by number.

Layer 1: pure, deterministic, no model call and no network. It produces a PROPOSAL with its
evidence attached. It confirms nothing, persists nothing, and selects nothing; a proposal that
nobody has looked at must not reach a firm (see ``bridge/spec_map.py`` for the gate).

WHY THIS EXISTS
---------------
This issuer's Bill of Quantities has no Clause Ref column, so ``refs_for_items`` returns nothing and
``relevant_ps_specs`` comes out empty — every trade then receives the same bundle with no
specification in it at all. The two title sources needed to do better now both exist: the bill's own
section heading (recovered past a page break by ``ingest.heading_chains`` / ``_section_titles``) and
the PS section titles (read from the issuer's index by ``doc_index.parse_ps_index``).

THE RULE THIS MODULE EXISTS TO NOT BREAK
----------------------------------------
A BILL NUMBER IS NOT A SPECIFICATION NUMBER. A bill is numbered by the Standard Method of
Measurement; a Particular Specification section is numbered by the specification. On CEDD
ND/2025/04 the bill headed "Ground Investigation" is **Bill 2**, while PS **2** is *Site Clearance*
and the specification that governs that bill is PS **28**, *Environmental Ground Investigation*.
Matching 2 to 2 encloses site clearance for a drilling package — the wrong specification, silently.

So :func:`strip_bill_number` removes the leading ``SECTION n`` / ``BILL NO. n`` token DELIBERATELY,
returns the number it discarded so the gate can show that it was discarded, and everything after
that matches on words alone.

CONFIDENCE
----------
Three tiers, and every one of them still requires a human to confirm:

* ``exact``  — the two titles reduce to the same words. "Laboratory Testing" / "Laboratory Testing".
* ``strong`` — one title's DISTINCTIVE words are all present in the other. "Ground Investigation
  Fieldworks" -> {ground, investigation} is contained in "Environmental Ground Investigation".
* ``weak``   — distinctive words are shared but neither contains the other, or both titles reduce to
  nothing but generic words that overlap ("General and Preliminaries" / "General").

NO PROPOSAL AT ALL when the only thing two titles share is a generic construction word. "Builders
Work" and "Geotechnical Works" share "work" and nothing else; offering that as a candidate would
invite a confirming click on a match with no content. A bill section with no proposal is not a
failure — it is the honest answer, and it falls to the whole-specification path.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from pipeline.stage_01_ingest.doc_index import DocIndexEntry

# The leading `SECTION 2 - `, `BILL NO. 2 : `, `Bill 3` token on a bill heading. Group 1 is the
# number, kept ONLY so the gate can show which number was thrown away.
_BILL_NUMBER = re.compile(r"^\s*(?:section|bill)\s*(?:no\.?|number)?\s*(\d{1,3})\s*[:.\-–—]?\s*", re.I)
# Words that carry no meaning of their own in a title.
_FUNCTION_WORDS = frozenset({"and", "of", "the", "to", "for", "in", "on", "a", "an", "or", "with"})
# Words that are real, but are the common currency of every construction bill and specification, so
# sharing ONE of them establishes nothing. A domain judgement, deliberately written down here where
# it can be read and argued with rather than derived from a statistic over eleven strings.
_GENERIC_WORDS = frozenset({
    "work", "fieldwork", "workmanship", "general", "generally", "site", "preliminary",
    "item", "sundry", "miscellaneous", "other", "provisional", "misc", "part", "specification",
})


class SpecProposal(BaseModel):
    """One bill section's proposed Particular Specification section, with the evidence for it.

    Everything an operator needs to disagree is on the object: what the bill heading said, what was
    removed from it, what the PS title said, WHERE that PS title came from, and which words the two
    have in common. A proposal with no ``ps_section`` is a proposal that nothing plausible was found
    — recorded, not omitted, so the gate can say so out loud.
    """

    bill_section: str                       # the bill's own code — "2"
    bill_heading: str = ""                  # verbatim, as recovered: "SECTION 2 - GROUND INVESTIGATION"
    bill_title: str = ""                    # after the number is stripped: "GROUND INVESTIGATION"
    discarded_number: str = ""              # the leading number that was deliberately NOT matched on
    ps_section: str = ""                    # "28" — empty means no plausible counterpart
    ps_title: str = ""
    ps_title_source: str = ""               # "page_1" | "ps_index" — provenance, carried through
    ps_document: str = ""
    confidence: str = "none"                # exact | strong | weak | none
    matched_on: list[str] = Field(default_factory=list)   # the words the two titles share
    evidence: str = ""                      # one sentence, for a person
    # Other sections that also scored, best first — so confirming is a choice, not a yes/no.
    alternatives: list["SpecCandidate"] = Field(default_factory=list)


class SpecCandidate(BaseModel):
    ps_section: str
    ps_title: str
    confidence: str
    matched_on: list[str] = Field(default_factory=list)


SpecProposal.model_rebuild()

_TIER_RANK = {"exact": 0, "strong": 1, "weak": 2}


def strip_bill_number(heading: str) -> tuple[str, str]:
    """``(the title, the leading number that was discarded)``.

    The whole point of the module in one function. ``"SECTION 2 - GROUND INVESTIGATION"`` ->
    ``("GROUND INVESTIGATION", "2")``. A heading with no leading number comes back unchanged with an
    empty number, so a bill that titles its sections plainly is not damaged.
    """
    m = _BILL_NUMBER.match(heading or "")
    if not m:
        return (heading or "").strip(), ""
    return (heading or "")[m.end():].strip(), m.group(1).lstrip("0") or m.group(1)


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"          # preliminaries -> preliminary
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]                # works -> work, trees -> tree, workers -> worker
    return word


def title_words(title: str) -> set[str]:
    """A title reduced to its comparable words: lowercase, punctuation gone, function words gone,
    plurals singularised so ``WORKS`` and ``Work`` are one word."""
    words = re.findall(r"[A-Za-z]+", title or "")
    return {w for raw in words if (w := _singular(raw.lower())) not in _FUNCTION_WORDS}


def _split(words: set[str]) -> tuple[set[str], set[str]]:
    """``(distinctive, generic)`` — the words that can carry a match, and the ones that cannot."""
    generic = words & _GENERIC_WORDS
    return words - generic, generic


def _tier(bill: set[str], ps: set[str]) -> tuple[Optional[str], set[str]]:
    """``(confidence, the shared words)``; ``(None, …)`` when there is no plausible match."""
    if bill and bill == ps:
        return "exact", bill
    bill_d, bill_g = _split(bill)
    ps_d, ps_g = _split(ps)
    shared_d = bill_d & ps_d
    if shared_d:
        contained = bill_d <= ps_d or ps_d <= bill_d
        return ("strong" if contained else "weak"), (bill & ps)
    if not bill_d and not ps_d and (bill_g & ps_g):
        # Both titles are made only of common words, and they overlap. Real, but the weakest thing
        # this module will say: "General and Preliminaries" against "General".
        return "weak", bill_g & ps_g
    return None, set()


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


def _ps_titles(doc_index: Iterable[DocIndexEntry]) -> list[DocIndexEntry]:
    """The PS section documents that carry a title to match against, one per section (the first
    seen wins, which is the order the index was built in)."""
    seen: dict[str, DocIndexEntry] = {}
    for e in doc_index:
        if e.kind == "particular_specification" and e.spec_section_number and e.spec_section_title:
            seen.setdefault(e.spec_section_number, e)
    return list(seen.values())


def propose_for_heading(heading: str, bill_section: str,
                        doc_index: list[DocIndexEntry]) -> SpecProposal:
    """The proposal for ONE bill section. Deterministic and total: a bill section with no plausible
    counterpart still comes back, with ``confidence="none"`` and a reason."""
    title, number = strip_bill_number(heading)
    bill_words = title_words(title)
    base = SpecProposal(bill_section=bill_section, bill_heading=heading or "",
                        bill_title=title, discarded_number=number)

    scored: list[tuple[int, float, int, str, DocIndexEntry, set[str]]] = []
    for e in _ps_titles(doc_index):
        ps_words = title_words(e.spec_section_title)
        tier, shared = _tier(bill_words, ps_words)
        if tier is None:
            continue
        # Section number ONLY as a stable tiebreak between equally-scored candidates — never as
        # evidence of a match. Two titles that score identically have to be ordered somehow.
        order = int(e.spec_section_number) if e.spec_section_number.isdigit() else 999
        scored.append((_TIER_RANK[tier], -_jaccard(bill_words, ps_words), order, tier, e, shared))
    scored.sort(key=lambda r: (r[0], r[1], r[2]))

    if not scored:
        why = ("the bill section declares no heading to match on" if not bill_words else
               "no specification section shares a distinctive word with this heading")
        return base.model_copy(update={
            "evidence": (f"No proposal — {why}. The bill's own number ({number or '—'}) is a method-"
                         "of-measurement number and is never matched against a specification number."),
        })

    _rank, _j, _order, tier, best, shared = scored[0]
    words = ", ".join(sorted(shared)) or "—"
    return base.model_copy(update={
        "ps_section": best.spec_section_number,
        "ps_title": best.spec_section_title,
        "ps_title_source": best.spec_section_title_source,
        "ps_document": best.filename,
        "confidence": tier,
        "matched_on": sorted(shared),
        "evidence": (
            f"Bill {bill_section} {title!r} matched to PS {best.spec_section_number} "
            f"{best.spec_section_title!r} on the word(s) {words} ({tier}). The PS title came from "
            f"{best.spec_section_title_source or 'an undeclared source'}. The bill's leading number"
            f"{f' ({number})' if number else ''} was discarded before matching — a bill number is a "
            "method-of-measurement number, not a specification number."
        ),
        "alternatives": [
            SpecCandidate(ps_section=e.spec_section_number, ps_title=e.spec_section_title,
                          confidence=t, matched_on=sorted(sh))
            for _r, _jj, _o, t, e, sh in scored[1:4]
        ],
    })


def propose_spec_map(bill_headings: dict[str, str],
                     doc_index: list[DocIndexEntry]) -> list[SpecProposal]:
    """``bill section code -> heading`` against the indexed PS titles, in bill order.

    Every bill section gets an entry, including the ones with no counterpart — a mapping screen that
    silently omits the sections it could not match tells the operator the map is complete.
    """
    def _key(code: str) -> tuple[int, str]:
        return (int(code), "") if code.isdigit() else (999, code)

    return [propose_for_heading(bill_headings[c], c, doc_index)
            for c in sorted(bill_headings, key=_key)]


def bill_headings_from_scope(package) -> dict[str, str]:
    """``section code -> the best heading available`` for one package.

    Two sources, and the better one wins. ``SectionMeta.title`` is the bill's own header row as the
    chunker read it (``Bill No. 2 : GROUND INVESTIGATION FIELDWORKS``). Where that is empty — a
    section whose header row never got captured — the heading is recovered from the items'
    ``heading_path``, which is what phase 1 fixed: before that, every item past a section's first
    page carried page furniture instead of its section heading.
    """
    headings: dict[str, str] = {}
    for meta in getattr(package, "sections", []) or []:
        if meta.title:
            headings[meta.code] = meta.title
    for item in getattr(package, "sor_items", []) or []:
        code = (item.section or "").strip().upper()
        if not code or code in headings:
            continue
        for step in item.heading_path or []:
            if strip_bill_number(step)[0]:
                headings[code] = step
                break
    return headings
