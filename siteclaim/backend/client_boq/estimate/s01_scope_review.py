"""ESTIMATE stage 01 — tender & scope review.

Bucket (mapping doc estimate task 1/2): **AI draft** (behind the review gate, before the scope gate).
The AI drafts the scope per the estimating doc step 1 — a scope ``summary`` plus notes tagged
inclusion / exclusion / ambiguity / conflict / assumption, and clarifying questions. Draft only: no
verdicts, no numbers.

Register→estimate wiring (deterministic, not left to the model): the APPROVED register's **confirmed**
departures are context the scope must reflect, so each confirmed departure's agreed position is
injected as a ``register``-sourced assumption note (the code injects it, verbatim). **Dismissed**
items are deliberately NOT carried, so a departure the human rejected can never resurface as a scope
risk. This makes the wiring testable regardless of the AI draft.

Signature change from the scaffold: ``review_scope(parsed, summary, register) -> ScopeReviewResult``.
"""

from __future__ import annotations

from client_boq.models import (
    STATUS_CONFIRMED,
    ContextSummary,
    DepartureRegister,
    ParsedDocumentSet,
    ScopeReviewNote,
    ScopeReviewResult,
)
from pipeline.llm_client import LLMClient, demo_mode

DEMO_FIXTURE = "cases/client_boq/estimate_scope_review.json"

_SYSTEM = (
    "You are a construction estimator performing a tender & scope review. You draft the scope: a "
    "concise scope summary, then notes tagged inclusion/exclusion/ambiguity/conflict/assumption, and "
    "clarifying questions. You draft only — no prices, no verdicts. Return ONLY JSON matching the schema."
)


def _draft(parsed: ParsedDocumentSet, summary: ContextSummary) -> ScopeReviewResult:
    client = LLMClient()
    if demo_mode():
        return client.complete_json(
            system=_SYSTEM, user="draft the scope review", target_model=ScopeReviewResult,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-estimate-scope",
        )
    clause_lines = [f"{c.clause_id} {c.heading}: {c.text}" for c in parsed.clauses]
    user = (
        "Commercial-risk summary:\n" + summary.summary + "\n\nCLAUSES:\n" + "\n".join(clause_lines)
        + "\n\nReturn {\"summary\": ..., \"notes\": [{kind, text}], \"clarifying_questions\": [...]}."
    )
    return client.complete_json(
        system=_SYSTEM, user=user, target_model=ScopeReviewResult, purpose="client_boq-estimate-scope",
    )


def review_scope(
    parsed: ParsedDocumentSet, summary: ContextSummary, register: DepartureRegister,
) -> ScopeReviewResult:
    """Draft the scope, then inject the approved register's confirmed departures as register-sourced
    assumptions (dismissed items are never carried)."""
    draft = _draft(parsed, summary)

    injected: list[ScopeReviewNote] = []
    for item in register.items:
        if item.status != STATUS_CONFIRMED:
            continue  # only CONFIRMED departures are scope context; dismissed/others are not carried
        position = (item.proposed_position or item.amendment_proposal or item.rationale).strip()
        label = item.clause_area or item.criterion_id or item.clause or "agreed departure"
        if position:
            injected.append(ScopeReviewNote(
                kind="assumption", source="register",
                text=f"Priced on the agreed position for {label}: {position}",
            ))

    return draft.model_copy(update={"notes": [*draft.notes, *injected]})
