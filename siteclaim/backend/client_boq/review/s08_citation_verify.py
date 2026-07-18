"""REVIEW stage 08 — citation verification (the anti-hallucination guard).

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

from client_boq.models import STATUS_CITATION_FAILED, STATUS_UNRESOLVED, CitationCheck, DepartureRegister, ParsedDocumentSet

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
