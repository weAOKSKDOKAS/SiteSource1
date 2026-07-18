"""HTTP surface for the client_boq module — mounted under ``/client-boq``.

This is the ONE thing ``api.py`` imports from the module: a single ``app.include_router(router)``
line (api.py otherwise declares routes directly on ``app``; this introduces the first APIRouter).
Everything the two workflows expose lives here — the heavy review-ingest kick-off + poll (the
in-package job pattern), the human-gate approval endpoints, and the **review→estimate gate check**
that refuses to run the estimate until the review register for a document set is human-approved.

SCAFFOLD STATE: the workflow-producing handlers (ingest, register build, estimate run) raise
``NotImplementedError`` — no workflow logic yet. The gate MECHANICS are real, because they are
deterministic infra, not workflow logic: the approval write, the approved-state read, and the job
status read all work, so the review→estimate gate is enforceable and testable now.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from client_boq import jobs, models
from db import store

router = APIRouter(prefix="/client-boq", tags=["client_boq"])


# ---------------------------------------------------------------------------
# DB helpers — the gate mechanics (deterministic infra, not workflow logic)
# ---------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    """Open the shared DB and ensure the module's own tables exist (idempotent)."""
    conn = store.get_connection()
    models.init_tables(conn)
    return conn


def review_is_approved(conn: sqlite3.Connection, set_id: str) -> bool:
    """True when the review register for ``set_id`` has been human-approved — the estimate gate."""
    row = conn.execute(
        "SELECT approved FROM client_boq_review_registers WHERE set_id = ?", (set_id,)
    ).fetchone()
    return bool(row and row["approved"])


def _set_review_approved(conn: sqlite3.Connection, set_id: str, approved: bool) -> None:
    """Record the human approval decision on the register (upsert). The gate action itself."""
    conn.execute(
        """
        INSERT INTO client_boq_review_registers (set_id, approved, approved_at)
        VALUES (?, ?, CASE WHEN ? THEN datetime('now') ELSE NULL END)
        ON CONFLICT(set_id) DO UPDATE SET
            approved = excluded.approved,
            approved_at = excluded.approved_at
        """,
        (set_id, 1 if approved else 0, 1 if approved else 0),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------
class ReviewApproval(BaseModel):
    set_id: str
    approved: bool = True


class GateState(BaseModel):
    set_id: str
    review_approved: bool


class JobState(BaseModel):
    job_id: str | None = None
    kind: str = ""
    status: str = "queued"
    stage: str = ""
    error: str | None = None
    result: dict | None = None
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# REVIEW workflow
# ---------------------------------------------------------------------------
@router.post("/review/ingest", response_model=JobState)
def post_review_ingest() -> JobState:
    """Kick off a REVIEW ingest as a background job and return a job id to poll (heavy sync work on
    ``jobs.POOL``, mirroring the procurement ingest). Scaffold: not implemented."""
    raise NotImplementedError("client_boq /review/ingest — scaffold only")


@router.get("/review/status/{job_id}", response_model=JobState)
def get_review_status(job_id: str) -> JobState:
    """Poll a client_boq background job (review or estimate). Real: reads the in-package job store."""
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
    """Return the assembled departure register for a document set. Scaffold: not implemented."""
    raise NotImplementedError("client_boq /review/register — scaffold only")


@router.post("/review/approve", response_model=GateState)
def post_review_approve(req: ReviewApproval) -> GateState:
    """The human gate: approve (or un-approve) the review register for a document set. This is the
    ONLY thing that opens the review→estimate gate. Real deterministic infra."""
    conn = _conn()
    try:
        _set_review_approved(conn, req.set_id, req.approved)
        return GateState(set_id=req.set_id, review_approved=review_is_approved(conn, req.set_id))
    finally:
        conn.close()


@router.get("/gate/{set_id}", response_model=GateState)
def get_gate(set_id: str) -> GateState:
    """The current review→estimate gate state for a document set. Real."""
    conn = _conn()
    try:
        return GateState(set_id=set_id, review_approved=review_is_approved(conn, set_id))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# ESTIMATE workflow — gated on review approval
# ---------------------------------------------------------------------------
class EstimateRunRequest(BaseModel):
    set_id: str


@router.post("/estimate/run", response_model=JobState)
def post_estimate_run(req: EstimateRunRequest) -> JobState:
    """Run the ESTIMATE workflow for a document set. REFUSES until the review register is
    human-approved (the locked review→estimate gate) — a 409 otherwise. The gate check is real;
    the estimate work itself is scaffold-only."""
    conn = _conn()
    try:
        if not review_is_approved(conn, req.set_id):
            raise HTTPException(
                status_code=409,
                detail="Estimate is gated: the review register for this document set is not approved yet.",
            )
    finally:
        conn.close()
    raise NotImplementedError("client_boq /estimate/run — scaffold only (gate passed)")
