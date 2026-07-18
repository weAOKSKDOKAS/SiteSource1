"""HTTP surface for the client_boq module — mounted under ``/client-boq``.

The ONE thing ``api.py`` imports from the module: a single ``include_router``. Everything the review
workflow exposes lives here — the heavy review run (background job in live, inline offline in DEMO),
the status poll, the register read, the human-gate approve endpoint (the ONLY writer of a
confirmed/dismissed verdict), and the **review→estimate gate check** that refuses the estimate until
the review register is approved.

Slice 1 implements the review workflow (s01→s02→s03→s07→s08); the estimate handler stays gated +
scaffold.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from client_boq import jobs, store
from client_boq.models import (
    HUMAN_VERDICTS,
    STATUS_CANDIDATE,
    STATUS_CITATION_FAILED,
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    STATUS_RULE_FLAGGED,
    STATUS_UNCOVERED,
    STATUS_UNRESOLVED,
    DepartureRegister,
    RawUpload,
)
from client_boq.review import run as review_run
from pipeline.llm_client import demo_mode

router = APIRouter(prefix="/client-boq", tags=["client_boq"])


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------
class GateState(BaseModel):
    set_id: str
    review_approved: bool


class JobState(BaseModel):
    job_id: str | None = None
    kind: str = "review"
    status: str = "queued"           # queued | running | done | error
    stage: str = ""
    error: str | None = None
    result: dict | None = None
    warnings: list[str] = Field(default_factory=list)


def _status_counts(register: DepartureRegister) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in register.items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


# Presentation order for the actionable line list (locked decision 1A: actionable first).
_ACTIONABLE_ORDER = {
    STATUS_RULE_FLAGGED: 0, STATUS_CITATION_FAILED: 1, STATUS_CANDIDATE: 2,
    STATUS_UNCOVERED: 3, STATUS_CONFIRMED: 4, STATUS_DISMISSED: 5,
}


def _result_payload(register: DepartureRegister) -> dict:
    """The review run's result envelope. Presents the one register (locked decisions 1A/2A/3A):
    actionable line items first, the unresolved criteria as one grouped section, the aligned section,
    and the cash-flow section. ``items`` keeps the full canonical list (stable item numbers the approve
    endpoint references)."""
    items = register.items
    actionable = sorted(
        (i for i in items if i.status != STATUS_UNRESOLVED),
        key=lambda i: (_ACTIONABLE_ORDER.get(i.status, 9), i.item),
    )
    unresolved = [i for i in items if i.status == STATUS_UNRESOLVED]
    return {
        "set_id": register.set_id,
        "slice": review_run.SLICE,
        "status_counts": _status_counts(register),
        "review_approved": register.approved,
        "register": {
            "set_id": register.set_id,
            "project": register.project,
            "package": register.package,
            "line_items": [i.model_dump() for i in actionable],
            "unresolved": {
                "count": len(unresolved),
                "criteria": [
                    {"item": i.item, "criterion_id": i.criterion_id, "clause_area": i.clause_area}
                    for i in unresolved
                ],
            },
            "aligned": [a.model_dump() for a in register.aligned],
            "cashflow": register.cashflow.model_dump() if register.cashflow else None,
            "items": [i.model_dump() for i in items],
        },
    }


# ---------------------------------------------------------------------------
# REVIEW — run (job in live, inline in DEMO), status, register
# ---------------------------------------------------------------------------
def _run_review_job(job_id: str, uploads: list[RawUpload], project_name: str) -> None:
    """Background worker: run the review and record progress/result/error on the job."""
    jobs.JOBS.update(job_id, status="running", stage="ingesting")
    try:
        register = review_run.run_review(
            uploads, project_name, progress_cb=lambda s: jobs.JOBS.update(job_id, stage=s),
        )
        jobs.JOBS.update(job_id, status="done", stage="verifying", result=_result_payload(register))
    except Exception as exc:  # noqa: BLE001 — any stage failure becomes a job error, not a crash
        jobs.JOBS.update(job_id, status="error", error=str(exc))


@router.post("/review/run", response_model=JobState)
def post_review_run(
    files: Optional[list[UploadFile]] = File(None),
    project_name: str = Form(""),
) -> JobState:
    """Run REVIEW (s01→s02→s03→s07→s08) over an uploaded document set. Live: kick off a background job
    and poll ``/review/status/{job_id}``. DEMO: run inline and return the register offline (no job, no
    network) — the fixtures drive a full register. s04–s06 are skipped (slice 1); the result names
    them in ``slice2_pending``."""
    uploads: list[RawUpload] = [
        (f.filename or "document", f.content_type, f.file.read()) for f in (files or [])
    ]
    if demo_mode():
        register = review_run.run_review(uploads, project_name)
        return JobState(status="done", stage="verifying", result=_result_payload(register))

    job_id = jobs.JOBS.create("review")
    jobs.POOL.submit(_run_review_job, job_id, uploads, project_name)
    return JobState(job_id=job_id, status="queued", stage="uploading")


@router.get("/review/status/{job_id}", response_model=JobState)
def get_review_status(job_id: str) -> JobState:
    """Poll a client_boq background job. Returns the result only when ``status == done``."""
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired client_boq job")
    return JobState(
        job_id=job_id, kind=job.kind, status=job.status, stage=job.stage,
        error=job.error or None, result=job.result if job.status == "done" else None,
        warnings=list(job.warnings),
    )


@router.get("/review/register/{set_id}")
def get_review_register(set_id: str) -> dict:
    """The persisted departure register for a document set (from the tables — the source of truth)."""
    conn = store.get_conn()
    try:
        register = store.load_register(conn, set_id)
    finally:
        conn.close()
    if register is None:
        raise HTTPException(status_code=404, detail=f"No review register for set {set_id!r}.")
    return _result_payload(register)


# ---------------------------------------------------------------------------
# REVIEW — the human gate (the ONLY writer of confirmed/dismissed + the gate flag)
# ---------------------------------------------------------------------------
class ReviewApproval(BaseModel):
    set_id: str
    # item number -> "confirmed" | "dismissed". The only place a verdict is written.
    decisions: dict[int, str] = Field(default_factory=dict)
    approved: bool = True  # open the review→estimate gate


@router.post("/review/approve", response_model=GateState)
def post_review_approve(req: ReviewApproval) -> GateState:
    """The human gate. Records each per-line verdict (confirmed/dismissed) — no other endpoint or
    stage may write these — and sets the review→estimate gate flag. A citation_failed line cannot be
    confirmed until re-reviewed (its citation is untrustworthy)."""
    bad = {v for v in req.decisions.values() if v not in HUMAN_VERDICTS}
    if bad:
        raise HTTPException(status_code=422, detail=f"decisions must be one of {sorted(HUMAN_VERDICTS)}; got {sorted(bad)}")

    conn = store.get_conn()
    try:
        register = store.load_register(conn, req.set_id)
        if register is None:
            raise HTTPException(status_code=404, detail=f"No review register for set {req.set_id!r}.")
        for item in register.items:
            verdict = req.decisions.get(item.item)
            if verdict is None:
                continue
            if verdict == "confirmed" and item.status == STATUS_CITATION_FAILED:
                raise HTTPException(
                    status_code=409,
                    detail=f"Item {item.item} has a failed citation and cannot be confirmed until re-reviewed.",
                )
            item.status = verdict
            item.register_status = "closed"
        store.save_register(conn, register)
        store.set_review_approved(conn, req.set_id, req.approved)
        return GateState(set_id=req.set_id, review_approved=store.review_is_approved(conn, req.set_id))
    finally:
        conn.close()


@router.get("/gate/{set_id}", response_model=GateState)
def get_gate(set_id: str) -> GateState:
    """The current review→estimate gate state for a document set."""
    conn = store.get_conn()
    try:
        return GateState(set_id=set_id, review_approved=store.review_is_approved(conn, set_id))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ESTIMATE — gated on review approval (workflow itself is a later slice)
# ---------------------------------------------------------------------------
class EstimateRunRequest(BaseModel):
    set_id: str


@router.post("/estimate/run", response_model=JobState)
def post_estimate_run(req: EstimateRunRequest) -> JobState:
    """Run ESTIMATE for a document set. REFUSES until the review register is human-approved (the
    locked review→estimate gate) — a 409 otherwise. The gate is real; the estimate workflow is a
    later slice."""
    conn = store.get_conn()
    try:
        if not store.review_is_approved(conn, req.set_id):
            raise HTTPException(
                status_code=409,
                detail="Estimate is gated: the review register for this document set is not approved yet.",
            )
    finally:
        conn.close()
    raise NotImplementedError("client_boq /estimate/run — estimate workflow is a later slice (gate passed)")
