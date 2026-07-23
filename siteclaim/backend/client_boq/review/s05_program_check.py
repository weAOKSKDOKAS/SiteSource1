"""REVIEW stage 05 — program & constructability check.

Bucket (mapping doc task 7): **AI propose → deterministic recompute**.

* The AI proposes program risks — unrealistic durations/sequencing, access/dependency risks,
  mobilisation count implied by scope, client milestones on the critical path — each with a citation.
  Qualitative proposals become ``candidate`` register lines.
* Everything NUMERIC is deterministic (``client_boq.rules``): the liquidated-damages exposure is
  recomputed (rate × delay days) and compared to any stated cap; the implied vs allowed mobilisation
  count is compared. A numeric breach → ``rule_flagged``; the AI never computes the exposure itself.
* If the document set has NO program document, that is a single ``rule_flagged``
  "program_not_provided" line — it materially affects LD exposure, so it is surfaced, not silence.

Returns register line items (``source == program``). Signature change from the scaffold: returns
``list[DepartureItem]`` (findings fold into the one register per locked decision 3A).
"""

from __future__ import annotations

from client_boq import rules
from client_boq.models import (
    SOURCE_PROGRAM,
    STATUS_CANDIDATE,
    STATUS_RULE_FLAGGED,
    ContextSummary,
    DepartureItem,
    ParsedDocumentSet,
    ProgramFinding,
    ProgramFindingSet,
)
from pipeline.llm_client import LLMClient, demo_mode

DEMO_FIXTURE = "cases/client_boq/review_program_check.json"

_SYSTEM = (
    "You are a construction planner reviewing a subcontract's programme risk. You PROPOSE risks "
    "(durations, sequencing, access, mobilisations, milestones on the critical path), each citing a "
    "clause, and extract any numbers (LD rate/day, delay days, LD cap, mobilisation counts). You do "
    "NOT compute exposure — that is done by rule. Return ONLY JSON matching the schema."
)

# A programme document is present when the set names one — bare 'schedule' is excluded (a Schedule of
# Rates is not a programme).
_PROGRAM_MARKERS = ("programme", "works programme", "construction programme", "baseline programme",
                    "gantt", "critical path", "program of works")


def _has_program(parsed: ParsedDocumentSet) -> bool:
    hay = " ".join([*parsed.documents, *(f"{c.heading} {c.text}" for c in parsed.clauses)]).lower()
    return any(m in hay for m in _PROGRAM_MARKERS)


def _propose(parsed: ParsedDocumentSet, summary: ContextSummary) -> ProgramFindingSet:
    client = LLMClient()
    if demo_mode():
        return client.complete_json(
            system=_SYSTEM, user="propose program risks", target_model=ProgramFindingSet,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-review-program",
        )
    clause_lines = [f"{c.clause_id} [{c.source_doc}] {c.heading}: {c.text}" for c in parsed.clauses]
    user = (
        "Summary:\n" + summary.summary + "\n\nCLAUSES:\n" + "\n".join(clause_lines)
        + "\n\nReturn {\"findings\": [{kind, description, contract_ref, cited_text, ld_rate_per_day, "
          "program_days, ld_cap_value, scope_mobilisations, program_mobilisations}]}."
    )
    return client.complete_json(
        system=_SYSTEM, user=user, target_model=ProgramFindingSet, purpose="client_boq-review-program",
    )


def _line_from_finding(f: ProgramFinding) -> DepartureItem:
    """Convert one AI proposal to a register line, running the deterministic recompute where the AI
    supplied numbers. The recompute — never the AI — decides a numeric breach."""
    item = DepartureItem(
        clause=f.contract_ref, cited_text=f.cited_text, clause_area=f.kind or "program",
        source=SOURCE_PROGRAM, kind=f.kind or "program", status=STATUS_CANDIDATE, rationale=f.description,
    )
    recomputed: list[str] = []  # the deterministic numbers, surfaced in the line's extracted_value
    # Deterministic LD-exposure recompute.
    if f.ld_rate_per_day is not None and f.program_days is not None:
        exposure = rules.recompute_ld_exposure(f.ld_rate_per_day, f.program_days)
        recomputed.append(f"LD exposure = {f.ld_rate_per_day} × {f.program_days} = {exposure}")
        if rules.ld_exceeds_cap(exposure, f.ld_cap_value):
            item.status = STATUS_RULE_FLAGGED
            item.rule_ref = "ld_exposure"
            item.rationale = (item.rationale + f" Recomputed LD exposure {exposure} exceeds the stated "
                              f"cap {f.ld_cap_value}.").strip()
    # Deterministic mobilisation comparison.
    if rules.mobilisation_mismatch(f.scope_mobilisations, f.program_mobilisations):
        item.status = STATUS_RULE_FLAGGED
        item.rule_ref = item.rule_ref or "mobilisation"
        recomputed.append(
            f"scope implies {f.scope_mobilisations} mobilisations, programme allows {f.program_mobilisations}"
        )
    if recomputed:
        item.extracted_value = "; ".join(recomputed)
    return item


def check_program(parsed: ParsedDocumentSet, summary: ContextSummary) -> list[DepartureItem]:
    """Produce program register lines: the program-not-provided guard, plus AI proposals with the
    deterministic recompute applied. Item numbers are assigned later by s07."""
    lines: list[DepartureItem] = []
    if not _has_program(parsed):
        lines.append(DepartureItem(
            clause="", source=SOURCE_PROGRAM, kind="program_not_provided", status=STATUS_RULE_FLAGGED,
            rule_ref="program_not_provided",
            rationale="No programme provided in the document set; delay/LD exposure cannot be bounded, "
                      "which materially affects the risk position.",
        ))
    lines.extend(_line_from_finding(f) for f in _propose(parsed, summary).findings)
    return lines
