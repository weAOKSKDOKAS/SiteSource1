"""REVIEW stage 04 — scope alignment: contract scope vs the priced scope.

Bucket (mapping doc task 6): **AI propose → precedence rule → human verdict**.

* The AI proposes scope gaps, inconsistencies, silent assumptions and responsibility creep, each with
  a clause citation and a drafted description (``complete_json`` against ``ScopeAlignmentSet``). These
  become register lines with ``status = candidate`` (the human decides).
* The document **order-of-precedence** check is deterministic RULE code (criterion SQD-01): extract
  the contract's stated precedence from its precedence clause and compare to the expected hierarchy
  (Contract → Scope → Drawings → Specifications). A mismatch is a ``rule_flagged`` line — the rule
  decides, not the AI. No precedence clause at all → a ``candidate`` "precedence_not_stated" line.
* Absent inputs (letter of offer, tender clarifications, estimate) are recorded as ``input_missing``
  candidate lines — surfaced, never skipped.

Returns register line items (``source == scope_alignment``); they flow through s08 citation
verification like every other line. (Signature change from the scaffold: returns
``list[DepartureItem]`` rather than ``list[ScopeAlignmentFinding]``, so findings land in the one
register per locked decision 3A.)
"""

from __future__ import annotations

from client_boq import rules
from client_boq.models import (
    SOURCE_SCOPE_ALIGNMENT,
    STATUS_CANDIDATE,
    STATUS_RULE_FLAGGED,
    ContextSummary,
    DepartureItem,
    ParsedDocumentSet,
    ScopeAlignmentSet,
)
from pipeline.llm_client import LLMClient, demo_mode

DEMO_FIXTURE = "cases/client_boq/review_scope_align.json"

_SYSTEM = (
    "You are a construction contract analyst checking whether the contract scope matches what was "
    "priced. You PROPOSE scope gaps, inconsistencies, silent assumptions and responsibility creep, "
    "each citing a clause. You never decide; the order of precedence is judged by rule, not by you. "
    "Return ONLY JSON matching the schema."
)

# Inputs the scope-alignment check expects in the set; absence is recorded, not skipped.
_EXPECTED_INPUTS = [
    ("letter of offer", ("letter of offer", "offer letter")),
    ("tender clarifications", ("clarification", "tender query", "rfi")),
    ("estimate", ("estimate", "priced schedule", "bill of quantities", "boq")),
]
_PRECEDENCE_MARKERS = ("order of precedence", "priority of documents", "document priority", "precedence")


def _propose(parsed: ParsedDocumentSet, summary: ContextSummary) -> ScopeAlignmentSet:
    client = LLMClient()
    if demo_mode():
        return client.complete_json(
            system=_SYSTEM, user="propose scope findings", target_model=ScopeAlignmentSet,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-review-scope",
        )
    clause_lines = [f"{c.clause_id} [{c.source_doc}] {c.heading}: {c.text}" for c in parsed.clauses]
    user = (
        "Summary:\n" + summary.summary + "\n\nCLAUSES:\n" + "\n".join(clause_lines)
        + "\n\nReturn {\"findings\": [{kind, description, contract_ref, cited_text, priced}]}."
    )
    return client.complete_json(
        system=_SYSTEM, user=user, target_model=ScopeAlignmentSet, purpose="client_boq-review-scope",
    )


def _precedence_line(parsed: ParsedDocumentSet) -> DepartureItem:
    """Deterministic SQD-01 check. A precedence clause with an inverted order → rule_flagged; a clause
    present and consistent → no line (caller filters None); none present → a candidate line."""
    for c in parsed.clauses:
        blob = f"{c.heading} {c.text}".lower()
        if any(m in blob for m in _PRECEDENCE_MARKERS):
            order = rules.extract_precedence_order(c.text)
            if rules.precedence_violation(order):
                return DepartureItem(
                    clause=c.clause_id, criterion_id="SQD-01", clause_area="Document Priority",
                    cited_text=c.text[:80], source=SOURCE_SCOPE_ALIGNMENT, kind="precedence",
                    status=STATUS_RULE_FLAGGED, rule_ref="SQD-01",
                    rationale=f"Stated order of precedence {order} inverts the expected hierarchy "
                              f"{rules.PRECEDENCE_EXPECTED} (SQD-01).",
                    proposed_position="Restore precedence: Contract → Scope → Drawings → Specifications.",
                )
            return DepartureItem(status="__aligned__")  # sentinel: consistent precedence, drop below
    # No precedence clause at all — a silent-scope risk (SQD-01 red flag), surfaced as a candidate.
    return DepartureItem(
        clause="", criterion_id="SQD-01", clause_area="Document Priority",
        source=SOURCE_SCOPE_ALIGNMENT, kind="precedence_not_stated", status=STATUS_CANDIDATE,
        rationale="No order-of-precedence clause found; document conflicts would be unresolved (SQD-01).",
    )


def _input_gap_lines(parsed: ParsedDocumentSet) -> list[DepartureItem]:
    haystack = " ".join([*parsed.documents, *(f"{c.heading} {c.text}" for c in parsed.clauses)]).lower()
    lines: list[DepartureItem] = []
    for label, kws in _EXPECTED_INPUTS:
        if not any(k in haystack for k in kws):
            lines.append(DepartureItem(
                clause="", source=SOURCE_SCOPE_ALIGNMENT, kind="input_missing", status=STATUS_CANDIDATE,
                rationale=f"No {label} in the document set — scope alignment cannot be fully confirmed "
                          f"against the priced/offered scope.",
            ))
    return lines


def check_scope_alignment(parsed: ParsedDocumentSet, summary: ContextSummary) -> list[DepartureItem]:
    """Produce scope-alignment register lines: AI-proposed findings (candidate), the deterministic
    precedence result, and input-gap lines. Item numbers are assigned later by s07."""
    lines: list[DepartureItem] = []
    for f in _propose(parsed, summary).findings:
        lines.append(DepartureItem(
            clause=f.contract_ref, cited_text=f.cited_text, clause_area=f.kind or "scope",
            source=SOURCE_SCOPE_ALIGNMENT, kind=f.kind or "scope", status=STATUS_CANDIDATE,
            rationale=f.description,
        ))
    prec = _precedence_line(parsed)
    if prec.status != "__aligned__":
        lines.append(prec)
    lines.extend(_input_gap_lines(parsed))
    return lines
