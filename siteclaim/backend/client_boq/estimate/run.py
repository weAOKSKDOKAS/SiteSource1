"""Orchestrate the ESTIMATE deterministic spine: s02 → s03 → s04 → s05 + totals/margin.

Pure deterministic assembly (no AI in this slice). Threads the structured schedule through
normalisation, cost build-up, indirects (which need the direct subtotal), and validation, then
computes totals and the margin readout, and persists to the ``client_boq_*`` tables + the artifact.

Margin: ``margin_pct`` is a required run input (the human states it). The math is cost → price →
margin amount; there is NO profitable/not verdict and no threshold flag on margin — the readout is
presented and the human decides.

Idempotent: the same schedule + margin yields byte-identical totals (all rounding is the single
``money`` half-to-even at 2 dp).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from client_boq import store
from client_boq.estimate import (
    money, s01_scope_review, s02_schedule, s03_cost_buildup, s04_indirects, s05_validate, s06_offer,
)
from client_boq.rates import load_rates
from client_boq.models import (
    ContextSummary, DepartureRegister, Estimate, EstimateSchedule, EstimateTotals, LetterMeta, ScopeReviewResult,
)
from pipeline.workspace import Workspace

ProgressCB = Callable[[str], None]
DEMO_MARGIN_PCT = 15.0  # the DEMO fixture margin (the human enters this in a live run)

# backend/client_boq/estimate/run.py -> parents[2] == backend/
_DEMO_SCHEDULE_FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "cases" / "client_boq" / "estimate_schedule.json"
)


def load_demo_schedule() -> EstimateSchedule:
    """The DEMO pricing schedule (offline fixture)."""
    return EstimateSchedule.model_validate_json(_DEMO_SCHEDULE_FIXTURE.read_text(encoding="utf-8"))


def run_scope(set_id: str, *, progress_cb: Optional[ProgressCB] = None) -> ScopeReviewResult:
    """Estimate step 1: draft the scope (s01) from the persisted parsed docs + summary + approved
    register, and persist the draft. Returns the draft. The caller has already checked the review
    gate."""
    if progress_cb:
        progress_cb("scoping")
    ws = Workspace()
    conn = store.get_conn()
    try:
        parsed = store.load_parsed(conn, set_id)
        register = store.load_register(conn, set_id)
        if parsed is None or register is None:
            raise ValueError(f"no reviewed document set for {set_id!r}; run and approve the review first")
        summary = store.load_summary(conn, set_id) or ContextSummary()
        draft = s01_scope_review.review_scope(parsed, summary, register)
        store.save_scope_draft(conn, set_id, draft)
        scope = store.load_scope(conn, set_id)
        if scope is not None:
            store.save_scope_artifact(ws, set_id, scope)
        return draft
    finally:
        conn.close()


def assemble_estimate(set_id: str, margin_pct: float, schedule: EstimateSchedule) -> Estimate:
    """Run the spine and compute totals/margin. Pure — no persistence, no I/O — so it is trivially
    unit-testable and reused by the persisting ``run_estimate``."""
    rates = load_rates()
    norm = s02_schedule.normalize_schedule(schedule)
    activities = s03_cost_buildup.build_cost(norm, rates)
    total_direct = s03_cost_buildup.direct_total(activities)
    indirects = s04_indirects.build_indirects(norm, total_direct)
    total_indirect = s04_indirects.indirect_total(indirects)
    flags = s05_validate.validate(norm, activities, rates)
    unclassified = [i for i in norm.items if i.category not in s02_schedule.VALID_CATEGORIES]

    total_cost = money(total_direct + total_indirect)
    price = money(total_cost * (1 + margin_pct / 100.0))
    margin_amount = money(price - total_cost)
    totals = EstimateTotals(
        total_direct=total_direct, total_indirect=total_indirect, total_cost=total_cost,
        margin_pct=margin_pct, price=price, margin_amount=margin_amount,
    )
    return Estimate(
        set_id=set_id, duration_weeks=norm.duration_weeks, activities=activities,
        indirects=indirects, unclassified=unclassified, flags=flags, totals=totals,
    )


def _resolve_meta(meta: Optional[LetterMeta], set_id: str, register: DepartureRegister) -> LetterMeta:
    """Fill the letter header defaults (project/ref from the reviewed register) around any supplied
    meta. All still code-injected — the AI never sees or writes these."""
    meta = meta or LetterMeta()
    project = meta.project or register.project or set_id
    return meta.model_copy(update={"project": project, "ref": meta.ref or project})


def run_estimate(
    set_id: str, margin_pct: float, schedule: EstimateSchedule, *,
    letter_meta: Optional[LetterMeta] = None, progress_cb: Optional[ProgressCB] = None,
) -> Estimate:
    """Assemble the estimate, then draft the offer letter (s06), and persist both (tables + artifacts).
    Returns the estimate; the letter is fetched via ``/estimate/{set_id}/letter``."""
    def step(stage: str) -> None:
        if progress_cb:
            progress_cb(stage)

    step("costing")
    estimate = assemble_estimate(set_id, margin_pct, schedule)

    step("persisting")
    ws = Workspace()
    conn = store.get_conn()
    try:
        store.save_estimate(conn, estimate)
        store.save_estimate_artifact(ws, set_id, estimate)

        # s06 — offer letter draft (AI prose + code-injected price/fields/schedule + confirmed departures).
        step("drafting letter")
        register = store.load_register(conn, set_id)
        scope = store.load_scope(conn, set_id)
        if register is not None and scope is not None:
            letter = s06_offer.build_letter(scope, estimate, register, _resolve_meta(letter_meta, set_id, register))
            store.save_letter(conn, letter)
            store.save_letter_artifact(ws, set_id, letter)
    finally:
        conn.close()
    return estimate
