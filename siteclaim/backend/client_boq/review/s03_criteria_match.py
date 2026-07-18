"""REVIEW stage 03 — match each contract clause against the criteria library.

Bucket (mapping doc tasks 5a/5b/5c): **AI propose → rule pre-flag → human gate**.

Three distinct responsibilities, kept strictly separate so no decision value is ever AI-written:

1. **AI proposes** (``DepartureProposalSet``): for each clause it names the matching criterion (or
   ""), extracts the numeric threshold field, quotes the supporting text, and drafts the amendment /
   rationale / proposed position. The proposal model has NO status field — the AI cannot write one.
2. **Rule pre-flags** (``client_boq.rules``): for the 8 numeric threshold criteria, deterministic
   code evaluates the extracted value → ``rule_flagged`` when the acceptable position is breached, or
   *aligned* (no departure line, recorded in ``aligned_criteria``) when it is met.
3. **Everything else is surfaced, nothing dropped:** a qualitative match → ``candidate`` (the human
   decides); a clause that matched no criterion → ``uncovered``; a criterion no clause resolved →
   ``unresolved``. The breach/no-breach *verdict* is set later, only by the human approve endpoint.

Output is a :class:`DepartureSet` (wrapper field ``departures``, plus ``aligned_criteria``).
"""

from __future__ import annotations

from client_boq import rules
from client_boq.models import (
    STATUS_CANDIDATE,
    STATUS_RULE_FLAGGED,
    STATUS_UNCOVERED,
    STATUS_UNRESOLVED,
    AlignedItem,
    ContextSummary,
    CriteriaLibrary,
    DepartureItem,
    DepartureProposal,
    DepartureProposalSet,
    DepartureSet,
    ParsedDocumentSet,
)
from pipeline.llm_client import LLMClient, demo_mode

DEMO_FIXTURE = "cases/client_boq/review_criteria_match.json"

_SYSTEM = (
    "You are a construction contract analyst comparing a contract against a fixed library of "
    "acceptable commercial positions. For each clause you PROPOSE the single best-matching criterion "
    "(or none), EXTRACT the specific field named for that criterion, QUOTE the supporting text, and "
    "DRAFT a departure. You never decide whether a term is acceptable — that is a human's job. "
    "Return ONLY JSON matching the schema; do not include any status or verdict."
)


def _build_prompt(parsed: ParsedDocumentSet, library: CriteriaLibrary) -> str:
    crit_lines = [
        f"{c.id} [{c.category}] {c.clause_area}: acceptable = {c.acceptable_position}; red flag = {c.red_flag}"
        for c in library.criteria
    ]
    thr_lines = [f"{t.id}: extract '{t.extract_field}' — rule: {t.rule}" for t in library.threshold_rules]
    clause_lines = [f"{c.clause_id} [{c.source_doc}] {c.heading}: {c.text}" for c in parsed.clauses]
    return (
        "CRITERIA LIBRARY (acceptable positions):\n" + "\n".join(crit_lines)
        + "\n\nNUMERIC THRESHOLD FIELDS TO EXTRACT (verbatim value string, e.g. 'Retention 10%, "
          "released at final certificate'):\n" + "\n".join(thr_lines)
        + "\n\nCONTRACT CLAUSES — one proposal per clause (criterion_id \"\" if it matches nothing):\n"
        + "\n".join(clause_lines)
        + "\n\nReturn {\"departures\": [ {clause_id, criterion_id, extracted_value, cited_text, "
          "amendment_proposal, rationale, proposed_position}, ... ]}."
    )


def _propose(parsed: ParsedDocumentSet, summary: ContextSummary, library: CriteriaLibrary) -> DepartureProposalSet:
    """The AI proposal pass (offline in DEMO). Proposals only — no status."""
    client = LLMClient()
    if demo_mode():
        return client.complete_json(
            system=_SYSTEM, user="propose departures", target_model=DepartureProposalSet,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-review-match",
        )
    return client.complete_json(
        system=_SYSTEM, user=_build_prompt(parsed, library), target_model=DepartureProposalSet,
        purpose="client_boq-review-match",
    )


def _item_from_proposal(p: DepartureProposal, library: CriteriaLibrary) -> DepartureItem:
    """Carry the AI's drafted fields onto a register line (status filled by the caller)."""
    crit = library.by_id(p.criterion_id) if p.criterion_id else None
    return DepartureItem(
        clause=p.clause_id, criterion_id=p.criterion_id,
        category=crit.category if crit else "", clause_area=crit.clause_area if crit else "",
        extracted_value=p.extracted_value, cited_text=p.cited_text,
        amendment_proposal=p.amendment_proposal, rationale=p.rationale,
        proposed_position=p.proposed_position,
    )


def match_criteria(
    parsed: ParsedDocumentSet, summary: ContextSummary, library: CriteriaLibrary,
) -> DepartureSet:
    """Propose matches, apply the deterministic threshold rules, and surface everything (rule_flagged,
    candidate, uncovered, unresolved, aligned) — no silent drops, no AI-written verdict."""
    proposals = _propose(parsed, summary, library)

    flagged: list[DepartureItem] = []
    candidates: list[DepartureItem] = []
    uncovered: list[DepartureItem] = []
    aligned: list[AlignedItem] = []
    resolved: set[str] = set()

    for p in proposals.departures:
        if not p.criterion_id:
            # A clause that matched no criterion — surfaced, not dropped.
            item = _item_from_proposal(p, library)
            item.status = STATUS_UNCOVERED
            uncovered.append(item)
            continue

        resolved.add(p.criterion_id)
        item = _item_from_proposal(p, library)
        crit = library.by_id(p.criterion_id)
        if rules.is_threshold_criterion(p.criterion_id):
            # Deterministic numeric decision — the rule flags, never the AI.
            if rules.evaluate_threshold(p.criterion_id, p.extracted_value):
                item.status = STATUS_RULE_FLAGGED
                item.rule_ref = p.criterion_id
                flagged.append(item)
            else:
                # Resolved and compliant — no departure line, but surfaced in the aligned section.
                aligned.append(AlignedItem(
                    criterion_id=p.criterion_id,
                    clause_area=crit.clause_area if crit else "",
                    clause=p.clause_id,
                    extracted_value=p.extracted_value,
                    why=f"within the acceptable position: {crit.acceptable_position}" if crit else "compliant",
                ))
        else:
            # Qualitative match the rule cannot judge — a candidate for the human.
            item.status = STATUS_CANDIDATE
            candidates.append(item)

    aligned_ids = {a.criterion_id for a in aligned}
    # Any populated criterion no clause resolved — surfaced as unresolved (never silently dropped).
    unresolved: list[DepartureItem] = []
    for crit in library.criteria:
        if crit.id in resolved or crit.id in aligned_ids:
            continue
        unresolved.append(DepartureItem(
            clause="", criterion_id=crit.id, category=crit.category, clause_area=crit.clause_area,
            rationale=crit.why_it_matters, status=STATUS_UNRESOLVED,
        ))

    ordered = [*flagged, *candidates, *uncovered, *unresolved]
    for i, item in enumerate(ordered, start=1):
        item.item = i
    return DepartureSet(departures=ordered, aligned=sorted(aligned, key=lambda a: a.criterion_id))
