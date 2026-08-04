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

import time as _time

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from client_boq import criteria_loader, criteria_store, jobs, models, store
from client_boq.models import (
    HUMAN_VERDICTS,
    STATUS_CANDIDATE,
    STATUS_CITATION_FAILED,
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    STATUS_QUERY,
    STATUS_RULE_FLAGGED,
    STATUS_UNCOVERED,
    STATUS_UNRESOLVED,
    DepartureRegister,
    PartSpec,
    RawUpload,
    RFIBatch,
    RFIItem,
    SplitManifest,
)
from client_boq import outputs
from client_boq.outputs import departure_schedule, qualifications
from client_boq.rfi import letter as rfi_letter
from client_boq.models import Estimate, EstimateSchedule, LetterMeta
from client_boq.ingest import history_workbook, pdfops, s02_interpret
from client_boq.ingest import run as ingest_run
from client_boq.review import run as review_run
from client_boq.review import s08_citation_verify
from client_boq.estimate import run as estimate_run
from client_boq.estimate import workbook as estimate_workbook
from pipeline.llm_client import demo_mode
from pipeline.workspace import Workspace

router = APIRouter(prefix="/client-boq", tags=["client_boq"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Who is doing this? Named profiles, not auth: the header names a team member so ownership and
# verdicts can be attributed, and an absent or unknown value degrades to "" rather than 401 —
# there is no security boundary here to enforce (CLAUDE.md trap 6), only honesty about who acted.
def _actor(x_cboq_actor: str = Header(default="", alias="X-CBOQ-Actor")) -> str:
    return (x_cboq_actor or "").strip()[:64]


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------
class GateState(BaseModel):
    set_id: str
    review_approved: bool
    # Queries deliberately do not block approval, so the count has to travel with the gate state:
    # an open question that stops being visible is the one real risk of the non-blocking choice.
    queries_raised: list[str] = Field(default_factory=list)
    open_queries: int = 0


class JobState(BaseModel):
    job_id: str | None = None
    kind: str = "review"
    status: str = "queued"           # queued | running | done | error
    stage: str = ""
    error: str | None = None
    result: dict | None = None
    warnings: list[str] = Field(default_factory=list)
    # Where this stage sits, and how many there are. `stage_total` 0 means the workflow's length
    # is not certain — show the position alone rather than a total that might be contradicted.
    stage_index: int = 0
    stage_total: int = 0
    done: int = 0                    # per-part progress within the stage; 0/0 when not counted
    total: int = 0
    # Elapsed only. Nothing here can honestly estimate what REMAINS, and a countdown that lies is
    # worse than a bar that says it does not know.
    elapsed_seconds: float = 0.0
    # A cancel has been asked for but the current stage has not finished yet. The distinction
    # matters on screen: "stopping at the next step" is true, "stopped" would not be.
    cancel_requested: bool = False


class ManifestGateState(BaseModel):
    set_id: str
    manifest_approved: bool
    parts: int = 0
    tier: int = 0


# The stage sequence of each workflow, where the sequence is STATIC in the code that runs it.
# `stage_total` is printed from this, so a workflow appears here only if its stages are certain.
_WORKFLOW_STAGES: dict[str, list[str]] = {
    "ingest": ["reading", "inspecting", "planning", "saving"],
    "split": ["splitting", "interpreting", "ingested"],
    "review": ["ingesting", "summarising", "matching", "scope", "program", "cashflow",
               "assembling", "verifying", "locating"],
}
# The review's last stage (`locating`) runs only when the set has parts to locate citations in, so
# its length is 8 OR 9. Rather than print a total the run might contradict two stages later, these
# workflows report the POSITION with no total — "stage 4", not "stage 4 of 9". The estimate and
# scope workflows are absent from `_WORKFLOW_STAGES` entirely because their runners live under
# `client_boq/estimate/`, which this work may not read into.
_UNCERTAIN_LENGTH = frozenset({"review"})


def _count_cb(job_id: str):
    """Progress WITHIN a stage — written as the loop runs, not once at the end.

    `run_split` already knew it was on part 3 of 12; it said so in the stage STRING, where nothing
    could read it as a number. This is that same fact, as numbers."""
    def _cb(done: int, total: int) -> None:
        jobs.JOBS.update(job_id, done=int(done), total=int(total))
    return _cb


def _begin(job_id: str, stage: str) -> None:
    """Mark a job running — unless it was cancelled while it sat in the queue.

    The pool holds two workers, so a job can wait behind another for minutes, and a cancel during
    that wait is the cheapest one there is: nothing has been spent yet. Without this check the
    worker's own `status="running"` would resurrect it and the run would proceed anyway.
    """
    if jobs.JOBS.cancelled(job_id):
        raise jobs.JobCancelled(stage)
    jobs.JOBS.update(job_id, status="running", stage=stage)


def _stage_cb(job_id: str, workflow: str = ""):
    """The progress callback every worker is given: record the stage it just reached, where that
    stage sits in the workflow, and STOP if a cancel was requested while the previous stage ran.

    A stage boundary is the only place a cancel can take effect. The work between boundaries is a
    blocking model call on a pool thread, and Python cannot interrupt one — so cancelling does not
    stop what is running, it stops the next thing from starting. On a run of ~100 calls at 20-120
    seconds each that is nearly all of the saving, and the UI says exactly that rather than
    implying the current call died.
    """
    stages = _WORKFLOW_STAGES.get(workflow, [])
    total = 0 if (workflow in _UNCERTAIN_LENGTH or not stages) else len(stages)

    def _cb(stage: str) -> None:
        if jobs.JOBS.cancelled(job_id):
            raise jobs.JobCancelled(stage)
        # A stage's own count starts unknown: the previous stage's 8/8 must not be left standing
        # over a stage that has not counted anything yet.
        jobs.JOBS.update(
            job_id, stage=stage, done=0, total=0,
            stage_index=(stages.index(stage) + 1) if stage in stages else 0,
            stage_total=total,
        )
    return _cb


def _job_state(job_id: str, job) -> JobState:
    """One shape for every poll endpoint, so all three workflows report progress alike."""
    return JobState(
        job_id=job_id, kind=job.kind, status=job.status, stage=job.stage,
        error=job.error or None, result=job.result if job.status == "done" else None,
        warnings=list(job.warnings), done=job.done, total=job.total,
        stage_index=job.stage_index, stage_total=job.stage_total,
        elapsed_seconds=round(_time.monotonic() - job.started_at, 1),
        cancel_requested=job.cancel_requested,
    )


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


def _parse_mismatch(conn, set_id: str) -> Optional[dict]:
    """Whether the register describes a DIFFERENT document from the one that was uploaded.

    Deterministic, and it exists because of a real and thoroughly confusing failure. In DEMO the
    review parse is a fixture about a fictional subcontract, so every finding cites a clause of a
    document that is not on screen and no quotation can ever be located. The screen looked broken
    when it was working exactly as designed.

    Comparison is on filenames the two sides independently record: the parse's ``documents`` versus
    the source documents the ingest actually cut. Disjoint means they are about different papers.

    Returns None when they correspond — so in LIVE this should never fire, and if it ever does,
    something genuinely is wrong.
    """
    parsed = store.load_parsed(conn, set_id)
    if parsed is None or not parsed.documents:
        return None
    rows = store.load_parts(conn, set_id)
    held = {(spec.source_doc or "").strip().lower() for spec, _p, _c in rows}
    manifest = store.load_manifest(conn, set_id)
    if manifest is not None and manifest.source_doc:
        held.add(manifest.source_doc.strip().lower())
    held.discard("")
    if not held:
        return None  # nothing split, so there is nothing to disagree with

    reviewed = {d.strip().lower() for d in parsed.documents if d.strip()}
    if reviewed & held:
        return None

    return {
        "reviewed": sorted(parsed.documents),
        "uploaded": sorted(d for d in held),
        "note": (
            "The findings below describe "
            + ", ".join(sorted(parsed.documents))
            + ", not the document set that was uploaded ("
            + ", ".join(sorted(held))
            + "). Nothing here can be located in your upload, so no quotation is highlighted. "
            "This is what an offline DEMO run looks like: the review stage returned its bundled "
            "sample instead of reading your files. Run this tender in LIVE mode to review it."
        ),
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
# INGEST — the front door: inspect + plan, the manifest gate, then split + interpret
# ---------------------------------------------------------------------------
def _manifest_payload(manifest: SplitManifest) -> dict:
    """The manifest envelope. The parts list IS the edit surface: the operator changes page
    ranges, titles and categories here and re-splits, which costs no model calls.

    ``coverage`` stays an int for compatibility (it is the covered page count, and callers
    depend on that); ``coverage_detail`` carries where the split actually breaks, from the same
    function the gate's own validation uses — so the manifest screen's gaps/overlaps count can
    never disagree with what the gate would refuse on.
    """
    return {
        "set_id": manifest.set_id,
        "source_doc": manifest.source_doc,
        "pages": manifest.pages,
        "tier": manifest.tier,
        "tier_reason": manifest.tier_reason,
        "approved": manifest.approved,
        "coverage": manifest.coverage(),
        "coverage_detail": pdfops.coverage(manifest, manifest.pages),
        # ``part_id`` is a computed property, so ``model_dump`` drops it — and it is the identity
        # every other endpoint keys on. Adding it here rather than letting a client re-derive the
        # zero-pad-plus-abbreviation rule, which is exactly the sort of duplicated identity rule
        # that drifts. Sending it back in an edited manifest is harmless: it is not a field.
        "parts": [{**p.model_dump(), "part_id": p.part_id} for p in manifest.parts],
    }


def _parts_payload(set_id: str, rows) -> dict:
    # Conditions that change how the tender must be BID, gathered from wherever they were found.
    # Surfaced on the set rather than buried in one part's card: a rule saying qualifications may
    # disqualify changes how the whole review should be run, and it has to be seen on day one
    # rather than discovered at submission when the query cut-off has passed.
    flags = [
        {**flag.model_dump(), "part_id": spec.part_id, "source_doc": spec.source_doc}
        for spec, _path, ctx in rows
        for flag in ctx.strategy_flags
    ]
    return {
        "set_id": set_id,
        "count": len(rows),
        "unreadable": sum(1 for _spec, _path, ctx in rows if not ctx.readable),
        "strategy_flags": flags,
        "penalises_qualifications": any(
            f["kind"] == models.RULE_QUALIFICATIONS_PENALISED for f in flags
        ),
        "parts": [
            {
                "part_id": spec.part_id, "n": spec.n, "abbr": spec.abbr, "title": spec.title,
                "category": spec.category, "pages": f"{spec.start}-{spec.end}",
                "page_count": spec.page_count(), "scanned": spec.scanned,
                "source_doc": spec.source_doc, "readable": ctx.readable,
                "summary": ctx.summary,
            }
            for spec, _path, ctx in rows
        ],
    }


def _run_ingest_job(job_id: str, uploads: list[RawUpload], project_name: str, actor: str = "") -> None:
    try:
        _begin(job_id, "reading")
        manifest = ingest_run.run_inspect(
            uploads, project_name, progress_cb=_stage_cb(job_id, "ingest"),
            on_note=lambda m: jobs.JOBS.add_warning(job_id, m),
        )
        _stamp_new_set(manifest.set_id, actor)
        jobs.JOBS.update(job_id, status="done", stage="awaiting-approval",
                         result=_manifest_payload(manifest))
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except Exception as exc:  # noqa: BLE001 — any failure becomes a job error, not a crash
        jobs.JOBS.update(job_id, status="error", error=str(exc))


def _stamp_new_set(set_id: str, actor: str) -> None:
    """Desk metadata for a set that just entered the app: the uploader owns it (they can hand it
    off on the card), and the close date is honestly ``reading`` until the interpreter has been
    given a chance to quote the deadline clause."""
    conn = store.get_conn()
    try:
        current = store.load_set_meta(conn, set_id)
        fields: dict = {}
        if not current["owner_id"] and actor:
            fields["owner_id"] = actor
        if fields or current["close_date_status"] == "reading":
            store.upsert_set_meta(conn, set_id, **fields)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()


@router.post("/ingest/upload", response_model=JobState)
def post_ingest_upload(
    files: Optional[list[UploadFile]] = File(None),
    project_name: str = Form(""),
    actor: str = Depends(_actor),
) -> JobState:
    """Upload a tender and get back a DRAFT split manifest for review.

    Nothing is cut here and no review runs: this reads the document's own structure, asks the
    planner to refine it, and stops at the manifest so a human can correct the boundaries
    before anything expensive happens. Approve it at ``/ingest/manifest/approve``, then
    ``/ingest/split``."""
    uploads: list[RawUpload] = [
        (f.filename or "document", f.content_type, f.file.read()) for f in (files or [])
    ]
    if not uploads:
        raise HTTPException(status_code=422, detail="Upload at least one PDF tender document.")
    if demo_mode():
        notes: list[str] = []
        try:
            manifest = ingest_run.run_inspect(uploads, project_name, on_note=notes.append)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _stamp_new_set(manifest.set_id, actor)
        # Same envelope as the live path — DEMO has no job to hang warnings off, so they ride
        # the inline JobState. A landing-on-an-existing-tender notice must not depend on mode.
        return JobState(kind="ingest", status="done", stage="awaiting-approval",
                        warnings=notes, result=_manifest_payload(manifest))
    job_id = jobs.JOBS.create("ingest")
    jobs.POOL.submit(_run_ingest_job, job_id, uploads, project_name, actor)
    return JobState(job_id=job_id, kind="ingest", status="queued", stage="uploading")


@router.post("/jobs/{job_id}/cancel", response_model=JobState)
def post_cancel_job(job_id: str) -> JobState:
    """Ask a running job to stop at its next stage boundary.

    ONE endpoint for every workflow, because there is one job store. It is a request, not a kill:
    the work between boundaries is a blocking model call on a pool thread and Python cannot
    interrupt one, so what this buys is that the next call is not started. On a run of ~100 calls
    at 20-120 seconds each that is nearly all of the saving.

    Cancelling a job that has already finished is a no-op rather than an error — by the time a
    person reaches the button the run may have ended, and that is not a failure to report.
    """
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired client_boq job")
    jobs.JOBS.cancel(job_id)
    return _job_state(job_id, jobs.JOBS.get(job_id) or job)


@router.get("/ingest/status/{job_id}", response_model=JobState)
def get_ingest_status(job_id: str) -> JobState:
    """Poll an ingest job (same in-package job store as review and estimate)."""
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired client_boq job")
    return _job_state(job_id, job)


@router.get("/ingest/manifest/{set_id}")
def get_ingest_manifest(set_id: str) -> dict:
    """The persisted split manifest, its confidence tier, and its approval state."""
    conn = store.get_conn()
    try:
        manifest = store.load_manifest(conn, set_id)
    finally:
        conn.close()
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No split manifest for set {set_id!r}.")
    return _manifest_payload(manifest)


class ManifestApproval(BaseModel):
    set_id: str
    # The human's edited part list. Omit it to approve the manifest as drafted.
    parts: list[PartSpec] | None = None
    approved: bool = True


@router.post("/ingest/manifest/approve", response_model=ManifestGateState)
def post_ingest_manifest_approve(req: ManifestApproval, actor: str = Depends(_actor)) -> ManifestGateState:
    """The manifest gate — the ONLY writer of the ingest approval flag, and the first gate of
    the workflow. An edited ``parts`` list replaces the draft and is validated against the
    real page count before it is stored: a split that does not fit the document is refused
    here rather than discovered halfway through a review."""
    conn = store.get_conn()
    try:
        manifest = store.load_manifest(conn, req.set_id)
        if manifest is None:
            raise HTTPException(
                status_code=404,
                detail=f"No split manifest for set {req.set_id!r}; run /ingest/upload first.",
            )
        if req.parts is not None:
            if not req.parts:
                raise HTTPException(status_code=422, detail="A manifest needs at least one part.")
            edited = manifest.model_copy(update={"parts": list(req.parts)})
            for index, part in enumerate(edited.parts, start=1):
                part.n = index
                if not part.source_doc:
                    part.source_doc = manifest.source_doc
            errors, _warnings = pdfops.validate(edited, manifest.pages)
            if errors:
                raise HTTPException(status_code=422, detail="; ".join(errors))
            # Re-stamp the measured text-layer facts onto the human's new boundaries. Whether a
            # page is a scan is a measurement, not an editorial choice.
            pdfops.mark_scanned(edited.parts, manifest.scanned_pages)
            manifest = edited
            store.save_manifest(conn, manifest)
        store.approve_manifest(conn, req.set_id, req.approved)
        store.touch_set(conn, req.set_id, actor)
        return ManifestGateState(
            set_id=req.set_id,
            manifest_approved=store.manifest_is_approved(conn, req.set_id),
            parts=len(manifest.parts), tier=manifest.tier,
        )
    finally:
        conn.close()


def _manifest_gate_or_409(set_id: str) -> None:
    conn = store.get_conn()
    try:
        if not store.manifest_is_approved(conn, set_id):
            raise HTTPException(
                status_code=409,
                detail="Ingest is gated: the split manifest for this document set is not approved yet.",
            )
    finally:
        conn.close()


def _run_split_job(job_id: str, set_id: str, actor: str = "") -> None:
    try:
        _begin(job_id, "splitting")
        ingest_run.run_split(set_id, progress_cb=_stage_cb(job_id, "split"),
                             count_cb=_count_cb(job_id))
        conn = store.get_conn()
        try:
            rows = store.load_parts(conn, set_id)
            # The freshly interpreted parts may quote the submission-deadline clause; turn the
            # quote into the desk's close date (or an honest not_found) while it is hot.
            from client_boq.ingest import close_date as close_date_mod
            close_date_mod.derive(conn, set_id)
            store.touch_set(conn, set_id, actor)
        finally:
            conn.close()
        jobs.JOBS.update(job_id, status="done", stage="ingested",
                         done=len(rows), total=len(rows), result=_parts_payload(set_id, rows))
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except Exception as exc:  # noqa: BLE001
        jobs.JOBS.update(job_id, status="error", error=str(exc))


class SplitRequest(BaseModel):
    set_id: str


@router.post("/ingest/split", response_model=JobState)
def post_ingest_split(req: SplitRequest, actor: str = Depends(_actor)) -> JobState:
    """Cut the approved manifest into parts and interpret each one. REFUSES until the manifest
    is approved (a 409). The cut costs no model calls, so editing the manifest and re-splitting
    is free — only the per-part interpretation is paid for again."""
    _manifest_gate_or_409(req.set_id)
    if demo_mode():
        ingest_run.run_split(req.set_id)
        conn = store.get_conn()
        try:
            rows = store.load_parts(conn, req.set_id)
            # The parts now carry whatever deadline clause the interpreter quoted; read it.
            from client_boq.ingest import close_date as close_date_mod
            close_date_mod.derive(conn, req.set_id)
            store.touch_set(conn, req.set_id, actor)
        finally:
            conn.close()
        return JobState(kind="ingest", status="done", stage="ingested",
                        done=len(rows), total=len(rows), result=_parts_payload(req.set_id, rows))
    job_id = jobs.JOBS.create("ingest")
    jobs.POOL.submit(_run_split_job, job_id, req.set_id, actor)
    return JobState(job_id=job_id, kind="ingest", status="queued", stage="splitting")


@router.get("/ingest/parts/{set_id}")
def get_ingest_parts(set_id: str) -> dict:
    """Every part of a split set, in document order, with its interpreted one-line summary."""
    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No split parts for set {set_id!r}.")
    return _parts_payload(set_id, rows)


# ---------------------------------------------------------------------------
# INGEST — revisions: addenda, corrections, clarifications, and the history
# ---------------------------------------------------------------------------
@router.post("/ingest/document")
def post_ingest_document(
    set_id: str = Form(...),
    kind: str = Form("addendum"),
    ref: str = Form(""),
    files: Optional[list[UploadFile]] = File(None),
) -> dict:
    """Take in a further document against a set already ingested: an **addendum** (the client
    amended the contract), a **correction** (we are replacing a document we uploaded wrong), or a
    **clarification** (the client answered a question and changed nothing).

    Commits nothing. It proposes which held parts the replacements supersede and stops at the
    change-mapping gate — superseding the wrong document is quiet and expensive, and a person can
    spot it in seconds. A clarification is recorded and goes no further, because both reference
    tenders state clarifications are expressly non-contractual.
    """
    uploads: list[RawUpload] = [
        (f.filename or "document", f.content_type, f.file.read()) for f in (files or [])
    ]
    if not uploads:
        raise HTTPException(status_code=422, detail="Upload at least one PDF.")
    try:
        return ingest_run.receive_document(set_id, uploads, kind=kind, ref=ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ChangeMapping(BaseModel):
    filename: str
    part_id: str


class ChangeApproval(BaseModel):
    set_id: str
    doc_id: str
    # The human's confirmed mapping of replacement file -> part it supersedes. Files left out
    # are simply not applied, which is the correct outcome for one nobody could place.
    mappings: list[ChangeMapping] = Field(default_factory=list)


@router.post("/ingest/changes/approve")
def post_ingest_changes_approve(req: ChangeApproval, actor: str = Depends(_actor)) -> dict:
    """The change-mapping gate — the only thing that creates a new revision.

    Each approved replacement becomes a NEW revision of its part. Nothing is overwritten: the
    previous revision stays readable and comparable. Register lines whose clauses came from a
    revised part have their verdicts reopened and flagged, because an approval of wording that
    has since been rewritten is exactly the stale sign-off this gate exists to prevent.
    """
    pairs = [(m.filename, m.part_id) for m in req.mappings if m.filename and m.part_id]
    try:
        applied, reopened, overtaken = ingest_run.apply_document(req.set_id, req.doc_id, pairs)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    conn = store.get_conn()
    try:
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    notes = [f"{len(applied)} part(s) moved to a new revision."]
    if reopened:
        notes.append(f"{len(reopened)} register line(s) were reopened for re-review.")
    if overtaken:
        notes.append(f"{len(overtaken)} open query/queries were overtaken by this document.")
    return {
        "set_id": req.set_id,
        "doc_id": req.doc_id,
        "revised": [{"part_id": p.part_id, "rev": p.rev, "title": p.title} for p in applied],
        "reopened_register_items": reopened,
        "overtaken_queries": overtaken,
        "note": " ".join(notes),
    }


@router.get("/revisions/{set_id}")
def get_revisions(set_id: str) -> dict:
    """The set's document history and every part's revision state.

    ``documents`` are the history's tabs, in arrival order. ``parts`` gives each part's operative
    revision, so it is visible at a glance which few documents an addendum actually touched.
    """
    conn = store.get_conn()
    try:
        record = store.load_set(conn, set_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"No document set {set_id!r}.")
        documents = store.list_documents(conn, set_id)
        rows = store.load_parts(conn, set_id)
        revisions = {
            spec.part_id: store.load_part_revisions(conn, set_id, spec.part_id)
            for spec, _p, _c in rows
        }
    finally:
        conn.close()
    return {
        "set_id": set_id,
        "documents": documents,
        "parts": [
            {
                "part_id": spec.part_id, "n": spec.n, "title": spec.title,
                "category": spec.category, "operative_rev": spec.rev,
                "revisions": revisions.get(spec.part_id, []),
            }
            for spec, _p, _c in rows
        ],
        "amended": [spec.part_id for spec, _p, _c in rows if spec.rev > 0],
    }


@router.get("/revisions/{set_id}/workbook")
def get_revisions_workbook(set_id: str) -> Response:
    """The revision history as an .xlsx: a summary sheet, one worksheet per document event
    showing the tender as it stood at that point, and the declared-changes table.

    Doubles as the evidence behind the addendum-acknowledgement returnable, which must state
    which revision of each document was priced — and which lists the client's addenda only,
    never our own corrections.
    """
    conn = store.get_conn()
    try:
        record = store.load_set(conn, set_id)
    finally:
        conn.close()
    if record is None:
        raise HTTPException(status_code=404, detail=f"No document set {set_id!r}.")
    xlsx = history_workbook.build_history_workbook(set_id)
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="revisions_{set_id}.xlsx"'},
    )


@router.get("/revisions/{set_id}/as-at/{seq}")
def get_revisions_as_at(set_id: str, seq: int) -> dict:
    """The set as it stood after the document at arrival position ``seq`` — one history tab.

    Reconstructed from the revisions rather than stored as a snapshot: each part's latest
    revision introduced at or before that point.
    """
    conn = store.get_conn()
    try:
        documents = store.list_documents(conn, set_id)
        rows = store.load_parts_as_at(conn, set_id, seq)
    finally:
        conn.close()
    if not documents:
        raise HTTPException(status_code=404, detail=f"No document set {set_id!r}.")
    at = next((d for d in documents if d["seq"] == seq), None)
    return {
        "set_id": set_id,
        "as_at": at,
        "parts": [
            {"part_id": spec.part_id, "n": spec.n, "title": spec.title, "rev": spec.rev,
             "pages": f"{spec.start}-{spec.end}", "source_doc": spec.source_doc}
            for spec, _p, _c in rows
        ],
    }


@router.get("/criteria")
def get_criteria() -> dict:
    """The acceptable-terms library — DB-backed, seeded once from ``review_criteria.md``.

    The register stores only a ``criterion_id`` (``PS-01``) plus the clause area, which on screen
    reads as a code nobody can decode. The two fields that make a finding self-explanatory —
    what position we accept, and what the red flag is — live in this library. Exposing it lets
    the register show *what we accept* beside *what the contract says*, which is the difference
    between a reviewer understanding a line and guessing at it.

    The payload shape is unchanged from the file-served version, plus ``rows`` — every criterion
    with its editing metadata (``enabled``, ``updated_by``) for the Criteria screen. ``criteria``
    still lists every populated row including disabled ones, because past registers reference
    ids and no referenced criterion is ever silently dropped; only future REVIEW RUNS skip
    disabled rows.
    """
    conn = store.get_conn()
    try:
        try:
            library = criteria_store.load(conn)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        rows = criteria_store.load_rows(conn)
    finally:
        conn.close()
    return {
        "count": len(library.criteria),
        "criteria": [c.model_dump() for c in library.criteria],
        "placeholders": [c.model_dump() for c in library.placeholders],
        "thresholds": [r.model_dump() for r in library.threshold_rules],
        "rows": rows,
    }


class CriterionEdit(BaseModel):
    """Send what changed. The id is in the path (update) or derived (create)."""
    category_id: str | None = None
    clause_area: str | None = None
    acceptable_position: str | None = None
    why_it_matters: str | None = None
    red_flag: str | None = None
    enabled: bool | None = None


@router.post("/criteria")
def post_criterion(req: CriterionEdit, actor: str = Depends(_actor)) -> dict:
    """Add a criterion. The id derives from the category (``PS-06`` after ``PS-05``) — numbers
    are never reused, because an id may be stamped on a historical register."""
    if not req.category_id or req.category_id not in criteria_loader._CATEGORY_PREFIX.values():
        raise HTTPException(
            status_code=422,
            detail=f"category_id must be one of {sorted(criteria_loader._CATEGORY_PREFIX.values())}",
        )
    if not (req.clause_area or "").strip():
        raise HTTPException(status_code=422, detail="A criterion needs a clause area.")
    category = next(k for k, v in criteria_loader._CATEGORY_PREFIX.items() if v == req.category_id)
    conn = store.get_conn()
    try:
        new_id = criteria_store.next_id(conn, req.category_id)
        row = criteria_store.upsert(
            conn, id=new_id, actor=actor,
            category_id=req.category_id, category=category,
            clause_area=req.clause_area or "",
            acceptable_position=req.acceptable_position or "",
            why_it_matters=req.why_it_matters or "",
            red_flag=req.red_flag or "",
            sort_order=9000,  # new rows go to the end of their category listing
        )
    finally:
        conn.close()
    return {"criterion": row}


@router.post("/criteria/{criterion_id}")
def post_criterion_update(criterion_id: str, req: CriterionEdit, actor: str = Depends(_actor)) -> dict:
    """Edit or disable one criterion. Editing stamps who; disabling keeps the row — future
    reviews stop checking it, past registers keep resolving it."""
    conn = store.get_conn()
    try:
        existing = criteria_store.get(conn, criterion_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"No criterion {criterion_id!r}.")
        fields = {k: v for k, v in req.model_dump().items() if v is not None and k != "category_id"}
        if not fields:
            raise HTTPException(status_code=422, detail="Nothing to change.")
        row = criteria_store.upsert(conn, id=criterion_id, actor=actor, **fields)
    finally:
        conn.close()
    return {"criterion": row}


# ---------------------------------------------------------------------------
# The rate library (Pricing & rates)
# ---------------------------------------------------------------------------
class RateEdit(BaseModel):
    """Send what changed. The id is in the path (update) or required here (create)."""
    rate_id: str = ""
    category: str | None = None
    code: str | None = None
    description: str | None = None
    unit: str | None = None
    rate: float | None = None
    currency: str | None = None
    notes: str | None = None


@router.get("/rates")
def get_rates() -> dict:
    """The rate book — DB-backed, seeded once from ``data/rates.csv``.

    ``rows`` carries editing metadata (``archived``, ``updated_by``); ``seed_duplicates`` names
    any ids the CSV repeated (first-wins was applied), so a cleaned-up seed is visible rather
    than silent. This is the book ``/estimate/run`` prices from.
    """
    from client_boq import rates as rates_mod, rates_store
    conn = store.get_conn()
    try:
        duplicates = rates_store.seed_if_empty(conn)
        rows = rates_store.load_rows(conn)
    finally:
        conn.close()
    return {
        "count": sum(1 for r in rows if not r["archived"]),
        "rows": rows,
        "categories": sorted(rates_mod.KNOWN_CATEGORIES),
        "seed_duplicates": sorted(duplicates),
    }


@router.post("/rates")
def post_rate(req: RateEdit, actor: str = Depends(_actor)) -> dict:
    """Add a rate. The id is the caller's (rate ids are meaningful codes like ``LAB-CONC``,
    not sequence numbers); an id already in the book is refused — edit it instead."""
    from client_boq import rates_store
    rate_id = req.rate_id.strip().upper()
    if not rate_id:
        raise HTTPException(status_code=422, detail="A rate needs a rate_id (e.g. LAB-CONC).")
    if req.rate is None:
        raise HTTPException(status_code=422, detail="A rate needs a numeric rate.")
    conn = store.get_conn()
    try:
        if rates_store.get(conn, rate_id) is not None:
            raise HTTPException(status_code=409, detail=f"Rate {rate_id!r} already exists; edit it instead.")
        fields = {k: v for k, v in req.model_dump().items() if v is not None and k != "rate_id"}
        fields.setdefault("source", "user")
        row = rates_store.upsert(conn, rate_id=rate_id, actor=actor, **fields)
    finally:
        conn.close()
    return {"rate": row}


@router.post("/rates/{rate_id}")
def post_rate_update(rate_id: str, req: RateEdit, actor: str = Depends(_actor)) -> dict:
    """Edit one rate. Editing stamps who and marks the source ``user`` — a number someone
    changed by hand must never still claim to be the seed's."""
    from client_boq import rates_store
    conn = store.get_conn()
    try:
        if rates_store.get(conn, rate_id) is None:
            raise HTTPException(status_code=404, detail=f"No rate {rate_id!r}.")
        fields = {k: v for k, v in req.model_dump().items() if v is not None and k != "rate_id"}
        if not fields:
            raise HTTPException(status_code=422, detail="Nothing to change.")
        fields["source"] = "user"
        row = rates_store.upsert(conn, rate_id=rate_id, actor=actor, **fields)
    finally:
        conn.close()
    return {"rate": row}


@router.delete("/rates/{rate_id}")
def delete_rate(rate_id: str, actor: str = Depends(_actor)) -> dict:
    """Archive a rate — never a delete. An estimate that referenced it will resolve it as
    ``missing_rate`` on a re-run: honestly absent and flagged, rather than priced at a number
    nobody stands behind any more."""
    from client_boq import rates_store
    conn = store.get_conn()
    try:
        if rates_store.get(conn, rate_id) is None:
            raise HTTPException(status_code=404, detail=f"No rate {rate_id!r}.")
        row = rates_store.upsert(conn, rate_id=rate_id, actor=actor, archived=True)
    finally:
        conn.close()
    return {
        "rate": row,
        "note": (f"{rate_id} is archived, not deleted. Any schedule line still referencing it "
                 f"will price at 0 with a missing_rate flag on the next estimate run."),
    }


# ---------------------------------------------------------------------------
# App-wide settings — the AI model
# ---------------------------------------------------------------------------
class LLMSettings(BaseModel):
    provider: str = ""          # "" = auto (env routing) | anthropic | deepseek
    model_anthropic: str = ""   # "" = the env/code default
    model_deepseek: str = ""


@router.get("/settings")
def get_settings() -> dict:
    """The app-wide LLM settings, plus what they actually mean at call time.

    ``effective`` reports the residual truths the stored values cannot override: page images
    always go to Anthropic vision (DeepSeek rejects image input), and an empty value means the
    environment's default, not "off".
    """
    from client_boq import llm as llm_mod
    from pipeline.llm_client import ANTHROPIC_MODEL, DEFAULT_DEEPSEEK_MODEL
    import os
    cfg = llm_mod.current_settings()
    conn = store.get_conn()
    try:
        rows = store.list_settings(conn)
    finally:
        conn.close()
    return {
        **cfg,
        "providers": [p for p in llm_mod.PROVIDERS if p],
        "effective": {
            "text_provider": cfg["provider"] or (
                "deepseek" if os.getenv("DEEPSEEK_API_KEY", "").strip() else "anthropic"),
            "vision_provider": "anthropic",   # always — DeepSeek rejects image input
            "model_anthropic": cfg["model_anthropic"] or os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODEL),
            "model_deepseek": cfg["model_deepseek"] or os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL),
        },
        "rows": rows,
    }


@router.post("/settings")
def post_settings(req: LLMSettings, actor: str = Depends(_actor)) -> dict:
    """Set the app-wide model choice. Applies to every client_boq AI stage from the next run —
    stages construct their client per run, so nothing needs restarting. Procurement is not
    affected: this setting is read only by ``client_boq/llm.py``."""
    from client_boq import llm as llm_mod
    if req.provider not in llm_mod.PROVIDERS:
        raise HTTPException(status_code=422,
                            detail=f"provider must be one of {[p or 'auto' for p in llm_mod.PROVIDERS]}")
    conn = store.get_conn()
    try:
        store.set_setting(conn, llm_mod.SETTING_PROVIDER, req.provider, actor)
        store.set_setting(conn, llm_mod.SETTING_MODEL_ANTHROPIC, req.model_anthropic.strip(), actor)
        store.set_setting(conn, llm_mod.SETTING_MODEL_DEEPSEEK, req.model_deepseek.strip(), actor)
    finally:
        conn.close()
    return get_settings()


@router.get("/sets")
def get_sets(include_archived: bool = False) -> dict:
    """Every document set, newest first, with gate states, desk metadata and the counts the
    home screen needs (undecided verdicts, failed citations, unaccepted fallbacks, open RFIs,
    and the derived ``blocked`` flag).

    Archived tenders leave the shelf by default — the shelf is only what still needs work —
    and come back with ``?include_archived=true`` for the Archived screen.
    """
    conn = store.get_conn()
    try:
        sets = store.list_sets(conn, include_archived=include_archived)
        for entry in sets:
            _backfill_close_date(conn, entry)
    finally:
        conn.close()
    return {"count": len(sets), "sets": sets}


def _backfill_close_date(conn, entry: dict) -> None:
    """Lazily derive the close date for a set still marked ``reading`` that has parts on disk —
    covers sets ingested before this feature existed. Idempotent; never touches ``confirmed``."""
    from client_boq.ingest import close_date as close_date_mod
    if entry["meta"]["close_date_status"] != "reading" or entry["parts"] == 0:
        return
    meta = close_date_mod.derive(conn, entry["set_id"])
    if meta is not None:
        entry["meta"].update(meta)


# ---------------------------------------------------------------------------
# The team, and a tender's desk metadata
# ---------------------------------------------------------------------------
class TeamMember(BaseModel):
    member_id: str = ""
    name: str
    initials: str = ""
    colour: str = ""
    role: str = ""
    archived: bool = False


@router.get("/team")
def get_team(include_archived: bool = False) -> dict:
    """The roster. Named profiles, not accounts — see the module boundary note on ``_actor``."""
    conn = store.get_conn()
    try:
        members = store.list_team(conn, include_archived=include_archived)
    finally:
        conn.close()
    return {"count": len(members), "members": members}


@router.post("/team")
def post_team(member: TeamMember) -> dict:
    """Add a member. The id derives from the name; initials derive when not given."""
    from pipeline.workspace import tender_slug
    member_id = member.member_id or tender_slug(member.name)
    if not member.name.strip():
        raise HTTPException(status_code=422, detail="A member needs a name.")
    initials = member.initials or "".join(w[0] for w in member.name.split()[:2]).upper()
    conn = store.get_conn()
    try:
        store.upsert_team_member(
            conn, member_id=member_id, name=member.name.strip(), initials=initials,
            colour=member.colour, role=member.role, archived=member.archived,
        )
        members = store.list_team(conn, include_archived=True)
    finally:
        conn.close()
    added = next(m for m in members if m["member_id"] == member_id)
    return {"member": added}


@router.post("/team/{member_id}")
def post_team_update(member_id: str, member: TeamMember) -> dict:
    """Update or archive a member. Archiving keeps the row — their name is stamped on history."""
    conn = store.get_conn()
    try:
        existing = {m["member_id"]: m for m in store.list_team(conn, include_archived=True)}
        if member_id not in existing:
            raise HTTPException(status_code=404, detail=f"No team member {member_id!r}.")
        store.upsert_team_member(
            conn, member_id=member_id, name=member.name.strip() or existing[member_id]["name"],
            initials=member.initials or existing[member_id]["initials"],
            colour=member.colour or existing[member_id]["colour"],
            role=member.role, archived=member.archived,
        )
        members = store.list_team(conn, include_archived=True)
    finally:
        conn.close()
    return {"member": next(m for m in members if m["member_id"] == member_id)}


class SetMetaUpdate(BaseModel):
    """Editable desk fields only. The close-date FINDING fields (status/citation/quote) are
    deliberately absent — they are written by derivation or by the confirm endpoint, never as
    plain form fields (a measurement outranks a form)."""
    owner_id: str | None = None
    client: str | None = None
    package: str | None = None
    archived: bool | None = None
    outcome: str | None = None    # live | submitted | won | lost


@router.post("/sets/{set_id}/meta")
def post_set_meta(set_id: str, req: SetMetaUpdate, actor: str = Depends(_actor)) -> dict:
    """Update a tender's desk metadata. An outcome other than ``live`` implies archived — a
    submitted, won or lost tender leaves the shelf, because the shelf is only unfinished work."""
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    if "outcome" in fields:
        if fields["outcome"] not in ("live", "submitted", "won", "lost"):
            raise HTTPException(status_code=422, detail="outcome must be live|submitted|won|lost")
        if fields["outcome"] != "live":
            fields["archived"] = True
    conn = store.get_conn()
    try:
        if store.load_set(conn, set_id) is None:
            raise HTTPException(status_code=404, detail=f"No document set {set_id!r}.")
        meta = store.upsert_set_meta(conn, set_id, **fields)
        store.touch_set(conn, set_id, actor)
        meta = store.load_set_meta(conn, set_id)
    finally:
        conn.close()
    return {"set_id": set_id, "meta": meta}


class CloseDateConfirmation(BaseModel):
    date: str          # ISO YYYY-MM-DD
    query_cutoff: str = ""   # optional; same format


@router.post("/sets/{set_id}/close-date")
def post_close_date(set_id: str, req: CloseDateConfirmation, actor: str = Depends(_actor)) -> dict:
    """A person confirms the close date by hand — the ONLY writer of a typed date.

    This is the other half of treating the date as a finding: when the machine read fails (or in
    DEMO, where reading the fixture would be a lie), the card says ``DATE NOT FOUND — CONFIRM IT``
    and the person who read the clause types what it says. ``confirmed`` outranks any later
    re-derivation, and the confirmation records who made it.
    """
    from datetime import date as date_type
    try:
        date_type.fromisoformat(req.date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Not an ISO date (YYYY-MM-DD): {req.date!r}") from exc
    fields = {
        "close_date": req.date,
        "close_date_status": "confirmed",
        "close_date_confirmed_by": actor,
    }
    if req.query_cutoff:
        try:
            date_type.fromisoformat(req.query_cutoff)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Not an ISO date: {req.query_cutoff!r}") from exc
        fields["query_cutoff"] = req.query_cutoff
    conn = store.get_conn()
    try:
        if store.load_set(conn, set_id) is None:
            raise HTTPException(status_code=404, detail=f"No document set {set_id!r}.")
        store.upsert_set_meta(conn, set_id, **fields)
        store.touch_set(conn, set_id, actor)
        meta = store.load_set_meta(conn, set_id)
    finally:
        conn.close()
    return {"set_id": set_id, "meta": meta}


@router.get("/ingest/parts/{set_id}/{part_id}")
def get_ingest_part(set_id: str, part_id: str) -> dict:
    """One part: its page range in the source, its interpreted context card, and where its
    cut PDF was materialised."""
    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    for spec, path, context in rows:
        if spec.part_id == part_id:
            return {
                "set_id": set_id, "part": spec.model_dump(), "pdf_path": path,
                "context": context.model_dump(),
                "card": s02_interpret.card_markdown(spec, context, spec.source_doc),
            }
    raise HTTPException(status_code=404, detail=f"No part {part_id!r} in set {set_id!r}.")


# --- the document pane: show a page, and look things up on it ---------------
def _part_or_404(set_id: str, part_id: str) -> tuple[PartSpec, bytes]:
    """One part's spec and the bytes of its cut PDF.

    Kept separate from :func:`get_ingest_part` because the viewer needs the file itself, not a
    path: the path is a server-side detail and reading it here is the only place that happens.
    """
    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    for spec, path, _context in rows:
        if spec.part_id != part_id:
            continue
        if not path:
            raise HTTPException(
                status_code=409,
                detail=f"Part {part_id!r} has not been cut yet; run /ingest/split first.",
            )
        try:
            return spec, Path(path).read_bytes()
        except OSError as exc:
            raise HTTPException(
                status_code=410,
                detail=f"The PDF for part {part_id!r} is no longer on disk ({path}).",
            ) from exc
    raise HTTPException(status_code=404, detail=f"No part {part_id!r} in set {set_id!r}.")


@router.get("/ingest/parts/{set_id}/{part_id}/page/{page}.png")
def get_part_page_image(set_id: str, part_id: str, page: int,
                        dpi: int = pdfops.DEFAULT_RENDER_DPI) -> Response:
    """One page of a part, rendered to PNG for the document pane.

    ``page`` is a **source-document** page number, because that is the number everything else in
    this module speaks: manifest ranges, citation pages and highlight rectangles are all in the
    binder's numbering. Asking the viewer to convert would mean two page-number conventions in one
    screen, which is how a highlight ends up on the wrong page.

    A scanned part renders like any other — seeing a page and searching it are different questions.
    """
    spec, data = _part_or_404(set_id, part_id)
    if not (spec.start <= page <= spec.end):
        raise HTTPException(
            status_code=404,
            detail=f"Page {page} is outside part {part_id!r} (pages {spec.start}-{spec.end}).",
        )
    image = pdfops.render_page(data, page - spec.start + 1, dpi)
    if image is None:
        raise HTTPException(status_code=404, detail=f"Page {page} could not be rendered.")
    # Immutable content: a part's pages only change when a revision replaces the part, and that
    # writes a new part row rather than editing this one.
    return Response(content=image, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


class LocateRequest(BaseModel):
    quote: str


@router.post("/ingest/parts/{set_id}/{part_id}/locate")
def post_part_locate(set_id: str, part_id: str, req: LocateRequest) -> dict:
    """Where a quoted claim actually sits in this part — "show me" on a context card.

    Same three verdicts as a register citation, because the question is the same one and inventing
    a second vocabulary for it would be worse than reusing this one:

    * ``located`` — found; the page is measured and rectangles come back;
    * ``unverifiable`` — the part has no text layer, so we could not look;
    * ``not_located`` — searchable, and the words are not on these pages.

    That third verdict earns its keep here. A DEMO fixture broadcasts the same strategy flags onto
    every part of a set, and locating them shows plainly that only one part actually contains
    them — which is exactly the sort of thing a card should not be allowed to assert unchallenged.

    Only use this for QUOTATIONS. A summary or an obligation is a paraphrase; asking where a
    paraphrase "is" has no honest answer, and the search endpoint is the right tool for those.
    """
    spec, data = _part_or_404(set_id, part_id)
    quote = (req.quote or "").strip()
    if not quote:
        raise HTTPException(status_code=422, detail="Nothing to locate.")

    if not pdfops.has_text_layer(data):
        return {
            "verdict": models.UNVERIFIABLE, "page": None, "highlights": [],
            "note": f"{part_id} has no text layer, so this could not be checked against the page.",
        }
    found = pdfops.locate(data, quote, page_offset=spec.start - 1)
    if found is None:
        return {
            "verdict": models.NOT_LOCATED, "page": None, "highlights": [],
            "note": (
                f"These words are not on pages {spec.start}-{spec.end}. The card may be quoting "
                f"another part of the set, or paraphrasing rather than quoting."
            ),
        }
    return {
        "verdict": models.LOCATED, "page": found["page"], "match": found["match"],
        "highlights": found["highlights"], "note": "",
    }


@router.get("/ingest/parts/{set_id}/{part_id}/search")
def get_part_search(set_id: str, part_id: str, q: str = "") -> dict:
    """Find text in one part — the document pane's search field.

    Returns the same page + fractional-rectangle shape as the citation highlights, so the pane
    draws both through one path. ``searchable`` is the honest half: an image-only part returns no
    hits because it could not be looked at, which is a different thing from having none.
    """
    spec, data = _part_or_404(set_id, part_id)
    query = (q or "").strip()
    searchable = pdfops.has_text_layer(data)
    hits = pdfops.search(data, query, page_offset=spec.start - 1) if (query and searchable) else []
    return {
        "set_id": set_id, "part_id": part_id, "query": query,
        "searchable": searchable,
        "pages": f"{spec.start}-{spec.end}",
        "count": len(hits),
        "hits": hits,
        "note": "" if searchable else
                "This part has no text layer, so it cannot be searched — only read by eye.",
    }


@router.post("/ingest/parts/{set_id}/{part_id}/reinterpret")
def post_part_reinterpret(set_id: str, part_id: str, actor: str = Depends(_actor)) -> dict:
    """Read one part again and rewrite its context card — the manifest screen's ``⟳``.

    The retry for a part that came back unread: interpretation is where the vision fallback
    lives, so this is the second attempt at a scan. Its own endpoint rather than "re-split the
    set", which would re-interpret every part to fix one.

    Nothing about the split changes — page bounds, the cut PDF and the revision are untouched,
    because none of them is what failed. And the honest outcome is preserved: a part vision
    still cannot read comes back `readable: false` with a note, never a plausible summary of
    pages nobody has seen.
    """
    try:
        context = ingest_run.run_reinterpret(set_id, part_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    conn = store.get_conn()
    try:
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {
        "set_id": set_id,
        "part_id": part_id,
        "readable": context.readable,
        "context": context.model_dump(),
    }


class ContextEdit(BaseModel):
    """A human's correction of one part's context card. Every field optional — send what changed."""

    summary: str | None = None
    key_points: list[str] | None = None
    obligations: list[str] | None = None
    commercial_flags: list[str] | None = None
    notes: str | None = None


@router.post("/ingest/parts/{set_id}/{part_id}/context")
def post_part_context(set_id: str, part_id: str, req: ContextEdit, actor: str = Depends(_actor)) -> dict:
    """Correct one part's context card.

    The model reads a part and writes a card; that card is a proposal like everything else the
    model produces, and until now it was the only proposal with no way to disagree with it. This
    is that way.

    **Saving stamps the card ``user``** — the same rule as a scope line, for the same reason: a
    model's reading and a person's correction of it must never be mistakable for one another.
    Re-interpreting the part puts ``ai`` back, because that genuinely is a fresh machine reading.

    ``readable`` is NOT editable. Whether a page carries a text layer is a measurement, and the
    module's standing rule is that a measurement is not clearable by an opinion — the same reason
    ``mark_scanned`` is re-applied after the planner and after a manifest edit.
    """
    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
        match = next(((s, p, c) for s, p, c in rows if s.part_id == part_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"No part {part_id!r} in set {set_id!r}.")
        spec, path, context = match

        changes = {k: v for k, v in req.model_dump().items() if v is not None}
        if not changes:
            raise HTTPException(status_code=422, detail="Nothing to change.")
        edited = context.model_copy(update={**changes, "badge": models.BADGE_USER})
        store.save_part_context(conn, set_id, part_id, edited)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()

    # Keep the card on disk in step, or the downloaded ZIP would carry the machine's reading of a
    # part the app now shows as corrected. Same path `run_reinterpret` uses.
    if path:
        try:
            Path(path).with_name("context.md").write_text(
                s02_interpret.card_markdown(spec, edited, spec.source_doc), encoding="utf-8",
            )
        except OSError:
            pass  # the stored context is the source of truth; the card is a convenience copy

    return {"set_id": set_id, "part_id": part_id, "context": edited.model_dump()}


@router.get("/ingest/{set_id}/download")
def get_ingest_download(set_id: str, include_source: bool = False) -> Response:
    """Download the split as a folder tree: one folder per part, each holding the cut PDF and
    its interpreted context card, plus the manifest and a README part table.

    This is the deliverable a user uploads a 400-page binder to get. The tree already exists on
    disk after a split; this packages it. Pass ``include_source=true`` to bundle the original
    uploads too — off by default, since it roughly doubles the size of something the user
    already has.
    """
    conn = store.get_conn()
    try:
        record = store.load_set(conn, set_id)
        manifest = store.load_manifest(conn, set_id)
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    if record is None or not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No split parts for set {set_id!r}; run the ingest and split first.",
        )

    ws = Workspace()
    name = record["name"]
    parts_root = store.parts_dir(ws, name)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if manifest is not None:
            archive.writestr("README.md", ingest_run.split_readme(manifest))
            archive.writestr("split-manifest.json", manifest.model_dump_json(indent=2))
        # Walk the materialised tree so the archive mirrors the on-disk folder-per-part layout
        # exactly, rather than reconstructing a second opinion of what the split looks like.
        for path in sorted(parts_root.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=str(path.relative_to(parts_root)).replace("\\", "/"))
        if include_source:
            docs = ws.docs_dir(name)
            if docs.is_dir():
                for path in sorted(docs.iterdir()):
                    if path.is_file():
                        archive.write(path, arcname=f"source/{path.name}")

    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{set_id}-split.zip"'},
    )


# ---------------------------------------------------------------------------
# REVIEW — run (job in live, inline in DEMO), status, register
# ---------------------------------------------------------------------------
def _run_review_job(job_id: str, uploads: list[RawUpload], project_name: str,
                    set_id: str = "") -> None:
    """Background worker: run the review and record progress/result/error on the job."""
    try:
        _begin(job_id, "ingesting")
        register = review_run.run_review(
            uploads, project_name, set_id=set_id,
            progress_cb=_stage_cb(job_id, "review"),
            count_cb=_count_cb(job_id),
            on_note=lambda m: jobs.JOBS.add_warning(job_id, m),
        )
        jobs.JOBS.update(job_id, status="done", stage="verifying", result=_result_payload(register))
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except Exception as exc:  # noqa: BLE001 — any stage failure becomes a job error, not a crash
        jobs.JOBS.update(job_id, status="error", error=str(exc))


@router.post("/review/run", response_model=JobState)
def post_review_run(
    files: Optional[list[UploadFile]] = File(None),
    project_name: str = Form(""),
    set_id: str = Form(""),
) -> JobState:
    """Run REVIEW (s01→…→s08) over a document set. Live: kick off a background job and poll
    ``/review/status/{job_id}``. DEMO: run inline and return the register offline (no job, no
    network) — the fixtures drive a full register.

    Two ways to name the documents:

    * ``set_id`` of a set already through ``/ingest`` — the review reads its approved parts one
      at a time, and each clause carries the part it came from. Refuses with a 409 if that set's
      split manifest has not been approved.
    * ``files`` — loose documents reviewed directly, for a single document with nothing to split.
    """
    uploads: list[RawUpload] = [
        (f.filename or "document", f.content_type, f.file.read()) for f in (files or [])
    ]
    if set_id:
        _manifest_gate_or_409(set_id)
    if demo_mode():
        register = review_run.run_review(uploads, project_name, set_id=set_id)
        return JobState(status="done", stage="verifying", result=_result_payload(register))

    job_id = jobs.JOBS.create("review")
    jobs.POOL.submit(_run_review_job, job_id, uploads, project_name, set_id)
    return JobState(job_id=job_id, status="queued", stage="uploading")


@router.get("/review/status/{job_id}", response_model=JobState)
def get_review_status(job_id: str) -> JobState:
    """Poll a client_boq background job. Returns the result only when ``status == done``."""
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired client_boq job")
    return _job_state(job_id, job)


@router.get("/review/register/{set_id}")
def get_review_register(set_id: str) -> dict:
    """The persisted departure register for a document set (from the tables — the source of truth)."""
    conn = store.get_conn()
    try:
        register = store.load_register(conn, set_id)
        mismatch = _parse_mismatch(conn, set_id) if register is not None else None
    finally:
        conn.close()
    if register is None:
        raise HTTPException(status_code=404, detail=f"No review register for set {set_id!r}.")
    return {**_result_payload(register), "parse_mismatch": mismatch}


# ---------------------------------------------------------------------------
# REVIEW — the human gate (the ONLY writer of confirmed/dismissed + the gate flag)
# ---------------------------------------------------------------------------
class ReviewApproval(BaseModel):
    set_id: str
    # item number -> "confirmed" | "dismissed" | "query". The only place a verdict is written.
    decisions: dict[int, str] = Field(default_factory=dict)
    # item number -> what we will negotiate instead. Written to ``contractor_response``.
    #
    # This exists because dismissing a clause is rarely the end of it: "we accept it as drafted"
    # and "we will not press this as a departure, but we will ask for X" are different positions,
    # and only the second one has anything to send. Without this the second position had nowhere
    # to live — the column was on the model and nothing wrote it.
    negotiations: dict[int, str] = Field(default_factory=dict)
    approved: bool = True  # open the review→estimate gate


@router.post("/review/approve", response_model=GateState)
def post_review_approve(req: ReviewApproval, actor: str = Depends(_actor)) -> GateState:
    """The human gate. Records each per-line verdict and sets the review→estimate gate flag — no
    other endpoint or stage may write either.

    Three verdicts: ``confirmed`` (we press this departure), ``dismissed`` (we accept the clause),
    and ``query`` (we are asking the client). A queried line stays **open** and raises an RFI, and
    it deliberately does not block approval — the submission deadline does not move because the
    client has not replied, so the forcing function is the freeze gate rather than this one.

    A citation_failed line cannot be confirmed until re-reviewed (its citation is untrustworthy),
    though it may perfectly well be queried — asking about it is often the right response.
    """
    bad = {v for v in req.decisions.values() if v not in HUMAN_VERDICTS}
    if bad:
        raise HTTPException(status_code=422, detail=f"decisions must be one of {sorted(HUMAN_VERDICTS)}; got {sorted(bad)}")

    conn = store.get_conn()
    try:
        register = store.load_register(conn, req.set_id)
        if register is None:
            raise HTTPException(status_code=404, detail=f"No review register for set {req.set_id!r}.")
        parsed = store.load_parsed(conn, req.set_id)
        clause_index = parsed.clause_index() if parsed is not None else {}
        raised: list[str] = []
        for item in register.items:
            # Negotiation text is recorded independently of a verdict, so that editing what you
            # will ask for does not require re-deciding the line — and so that unqueueing the
            # question from an RFI batch leaves the draft text where it was.
            if item.item in req.negotiations:
                item.contractor_response = req.negotiations[item.item]
            verdict = req.decisions.get(item.item)
            if verdict is None:
                continue
            if verdict == STATUS_CONFIRMED and item.status == STATUS_CITATION_FAILED:
                raise HTTPException(
                    status_code=409,
                    detail=f"Item {item.item} has a failed citation and cannot be confirmed until re-reviewed.",
                )
            item.status = verdict
            # Who recorded it — the difference between a "CONFIRMED BY R. LAM" chip that means
            # something and one that decorates. "" when nobody identified themselves.
            item.decided_by = actor
            if verdict == STATUS_QUERY:
                # The line stays open: the question is asked, not answered.
                item.register_status = "open"
                clause = clause_index.get(item.clause)
                rfi = store.save_rfi(conn, req.set_id, RFIItem(
                    origin=models.RFI_FROM_REGISTER,
                    register_item=item.item,
                    part_id=getattr(clause, "part_id", "") if clause else "",
                    clause=item.clause,
                    page=getattr(clause, "page", None) if clause else None,
                    # The human's own words first. `contractor_response` is what they typed into
                    # "what you will negotiate instead"; the fallbacks are the model's phrasing,
                    # which is a reasonable starting point but not what someone chose to ask.
                    question=(item.contractor_response or item.amendment_proposal
                              or item.proposed_position or item.rationale),
                    context=item.cited_text,
                ))
                raised.append(rfi.rfi_id)
            else:
                item.register_status = "closed"
        store.save_register(conn, register)
        store.set_review_approved(conn, req.set_id, req.approved)
        store.touch_set(conn, req.set_id, actor)
        return GateState(
            set_id=req.set_id,
            review_approved=store.review_is_approved(conn, req.set_id),
            queries_raised=raised,
            open_queries=store.open_rfi_count(conn, req.set_id),
        )
    finally:
        conn.close()


@router.get("/gate/{set_id}", response_model=GateState)
def get_gate(set_id: str) -> GateState:
    """The current review→estimate gate state for a document set, with the open-query count."""
    conn = store.get_conn()
    try:
        return GateState(
            set_id=set_id,
            review_approved=store.review_is_approved(conn, set_id),
            open_queries=store.open_rfi_count(conn, set_id),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RFI — raise questions, batch them into a letter, record what comes back
# ---------------------------------------------------------------------------
class RFIRequest(BaseModel):
    set_id: str
    question: str
    origin: str = "manual"          # register | pricing | manual
    register_item: int | None = None
    part_id: str = ""
    clause: str = ""
    page: int | None = None
    context: str = ""


@router.post("/rfi")
def post_rfi(req: RFIRequest, actor: str = Depends(_actor)) -> dict:
    """Raise a question for the client.

    ``origin`` records where it came from. ``pricing`` matters as much as ``register``: many real
    questions surface only when someone tries to put a number on something, long after the
    contract review finished.
    """
    if req.origin not in models.RFI_ORIGINS:
        raise HTTPException(
            status_code=422,
            detail=f"origin must be one of {sorted(models.RFI_ORIGINS)}; got {req.origin!r}",
        )
    if not req.question.strip():
        raise HTTPException(status_code=422, detail="A query needs a question.")
    conn = store.get_conn()
    try:
        item = store.save_rfi(conn, req.set_id, RFIItem(
            origin=req.origin, register_item=req.register_item, part_id=req.part_id,
            clause=req.clause, page=req.page, question=req.question, context=req.context,
        ))
        store.touch_set(conn, req.set_id, actor)
        return {"set_id": req.set_id, "rfi": item.model_dump(),
                "open_queries": store.open_rfi_count(conn, req.set_id)}
    finally:
        conn.close()


@router.get("/rfi/{set_id}")
def get_rfis(set_id: str) -> dict:
    """Every question on this set, its status, and the batches they were sent in.

    ``open`` is the count the freeze gate must see reach zero, and the one a UI should keep in
    front of the user — a queried line does not block pricing, so nothing else makes it visible.
    """
    conn = store.get_conn()
    try:
        items = store.load_rfis(conn, set_id)
        batches = store.load_rfi_batches(conn, set_id)
        open_count = store.open_rfi_count(conn, set_id)
    finally:
        conn.close()
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
    return {
        "set_id": set_id,
        "count": len(items),
        "open": open_count,
        "by_status": by_status,
        "items": [item.model_dump() for item in items],
        "batches": [
            {"batch_id": b.batch_id, "ref": b.ref, "sent_at": b.sent_at,
             "items": [i.rfi_id for i in b.items]}
            for b in batches
        ],
    }


@router.delete("/rfi/{set_id}/{rfi_id}")
def delete_rfi(set_id: str, rfi_id: str, actor: str = Depends(_actor)) -> dict:
    """Take a draft question out of the build it is queued in.

    A withdrawal, not a deletion — the question stays on the record with a ``withdrawn`` status,
    because "we asked and then thought better of it" is part of how a tender was run. It stops
    counting as open, which is correct: nobody is waiting on the client for it any more.

    The draft text it came from is untouched. It lives on the register line
    (``contractor_response``), not on the question, which is exactly why unqueueing can keep it.

    A question that has already been sent cannot be withdrawn here — the client has it, and the
    honest routes from there are an answer or an overtaking amendment.
    """
    conn = store.get_conn()
    try:
        try:
            item = store.withdraw_rfi(conn, set_id, rfi_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if item is None:
            raise HTTPException(status_code=404, detail=f"No query {rfi_id!r} on set {set_id!r}.")
        store.touch_set(conn, set_id, actor)
        return {"set_id": set_id, "rfi": item.model_dump(),
                "open_queries": store.open_rfi_count(conn, set_id)}
    finally:
        conn.close()


class RFIBatchRequest(BaseModel):
    set_id: str
    ref: str = ""                       # e.g. "Technical Query No. 1"
    rfi_ids: list[str] = Field(default_factory=list)   # empty = every draft question


@router.post("/rfi/batch")
def post_rfi_batch(req: RFIBatchRequest) -> dict:
    """Assemble the drafted questions into one numbered letter and mark them sent.

    Batched because that is how tender queries actually go out — one numbered letter per round,
    as the reference package's TC1 and TC2 show — and because a client answering ten scattered
    emails answers them inconsistently.

    Nothing is transmitted: the letter is a draft for a human to send.
    """
    conn = store.get_conn()
    try:
        record = store.load_set(conn, req.set_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"No document set {req.set_id!r}.")
        items = store.load_rfis(conn, req.set_id)
        # Named ids when given, otherwise every question still sitting in draft.
        chosen = [
            i for i in items
            if (i.rfi_id in req.rfi_ids if req.rfi_ids else i.status == models.RFI_DRAFT)
        ]
        if not chosen:
            raise HTTPException(status_code=422, detail="No draft queries to send.")

        existing = store.load_rfi_batches(conn, req.set_id)
        batch_id = f"batch-{len(existing) + 1:02d}"
        ref = req.ref or f"Technical Query No. {len(existing) + 1}"
        for number, item in enumerate(chosen, start=1):
            item.number = number
            item.batch_id = batch_id
            item.status = models.RFI_SENT
            store.save_rfi(conn, req.set_id, item)

        letter = rfi_letter.render_letter(record["name"], ref, chosen)
        store.save_rfi_batch(conn, req.set_id, RFIBatch(
            batch_id=batch_id, ref=ref, sent_at=_now(), letter_md=letter,
        ))
        return {
            "set_id": req.set_id, "batch_id": batch_id, "ref": ref,
            "count": len(chosen), "markdown": letter,
            "open_queries": store.open_rfi_count(conn, req.set_id),
        }
    finally:
        conn.close()


class RFIAnswer(BaseModel):
    set_id: str
    rfi_id: str
    answer: str
    answered_by: str = ""               # the document that carried it, e.g. "Tender Addendum No.1"


@router.post("/rfi/answer")
def post_rfi_answer(req: RFIAnswer) -> dict:
    """Record the client's reply to one question.

    Recording an answer does not by itself change any document. If the reply arrived as an
    addendum, that addendum goes through ``/ingest/document`` and the change-mapping gate like any
    other — an answer is information, a revision is a commitment, and they are not the same act.
    """
    conn = store.get_conn()
    try:
        items = {i.rfi_id: i for i in store.load_rfis(conn, req.set_id)}
        item = items.get(req.rfi_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"No query {req.rfi_id!r} on this set.")
        item.answer = req.answer
        item.answered_by = req.answered_by
        item.status = models.RFI_ANSWERED
        item.answered_at = _now()
        store.save_rfi(conn, req.set_id, item)
        return {"set_id": req.set_id, "rfi": item.model_dump(),
                "open_queries": store.open_rfi_count(conn, req.set_id)}
    finally:
        conn.close()


@router.get("/rfi/{set_id}/batch/{batch_id}")
def get_rfi_batch(set_id: str, batch_id: str) -> dict:
    """One sent batch: its letter and the questions it carried."""
    conn = store.get_conn()
    try:
        batches = {b.batch_id: b for b in store.load_rfi_batches(conn, set_id)}
    finally:
        conn.close()
    batch = batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"No batch {batch_id!r} on set {set_id!r}.")
    return {
        "set_id": set_id, "batch_id": batch.batch_id, "ref": batch.ref,
        "sent_at": batch.sent_at, "markdown": batch.letter_md,
        "items": [i.model_dump() for i in batch.items],
    }


# ---------------------------------------------------------------------------
# ESTIMATE — gated on review approval (workflow itself is a later slice)
# ---------------------------------------------------------------------------
class EstimateRunRequest(BaseModel):
    set_id: str
    margin_pct: float | None = None                 # required in live (the human states it); DEMO uses the fixture margin
    schedule: EstimateSchedule | None = None        # required in live; DEMO uses the fixture schedule
    letter: LetterMeta | None = None                # offer-letter header fields (code-injected); defaults applied


def _flag_counts(estimate: Estimate) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in estimate.flags:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    return counts


def _estimate_payload(estimate: Estimate) -> dict:
    """The estimate envelope — totals + margin readout, a flag breakdown, and the full estimate
    (activities with per-line cost traces, indirects, flags)."""
    return {
        "set_id": estimate.set_id,
        "totals": estimate.totals.model_dump(),
        "flag_counts": _flag_counts(estimate),
        "estimate": estimate.model_dump(),
    }


def _gate_or_409(set_id: str) -> None:
    conn = store.get_conn()
    try:
        if not store.review_is_approved(conn, set_id):
            raise HTTPException(
                status_code=409,
                detail="Estimate is gated: the review register for this document set is not approved yet.",
            )
    finally:
        conn.close()


def _run_estimate_job(job_id: str, set_id: str, margin_pct: float, schedule: EstimateSchedule,
                      letter: LetterMeta | None) -> None:
    try:
        _begin(job_id, "costing")
        estimate = estimate_run.run_estimate(
            set_id, margin_pct, schedule, letter_meta=letter,
            progress_cb=_stage_cb(job_id),
        )
        jobs.JOBS.update(job_id, status="done", stage="persisting", result=_estimate_payload(estimate))
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except Exception as exc:  # noqa: BLE001 — any failure becomes a job error, not a crash
        jobs.JOBS.update(job_id, status="error", error=str(exc))


# --- estimate step 1: scope draft + its human gate (mirrors the review gate) ----------------------
class ScopeRunRequest(BaseModel):
    set_id: str


class ScopeApproval(BaseModel):
    set_id: str
    amended_summary: str = ""      # optional human edit; becomes the approved scope of record
    approved: bool = True


class ScopeGateState(BaseModel):
    set_id: str
    scope_approved: bool
    summary_of_record: str = ""


def _scope_payload(set_id: str, scope) -> dict:
    return {
        "set_id": set_id,
        "review_approved": True,
        "scope_approved": scope.approved,
        "summary_of_record": scope.summary_of_record(),
        "scope": scope.draft.model_dump(),
        "amended_summary": scope.amended_summary,
    }


def _scope_gate_or_409(set_id: str) -> None:
    conn = store.get_conn()
    try:
        if not store.scope_is_approved(conn, set_id):
            raise HTTPException(
                status_code=409,
                detail="Estimate is gated: the estimate scope for this document set is not approved yet.",
            )
    finally:
        conn.close()


def _run_scope_job(job_id: str, set_id: str) -> None:
    try:
        _begin(job_id, "scoping")
        estimate_run.run_scope(set_id, progress_cb=_stage_cb(job_id))
        conn = store.get_conn()
        try:
            scope = store.load_scope(conn, set_id)
        finally:
            conn.close()
        jobs.JOBS.update(job_id, status="done", stage="scoping", result=_scope_payload(set_id, scope))
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except Exception as exc:  # noqa: BLE001
        jobs.JOBS.update(job_id, status="error", error=str(exc))


@router.post("/estimate/scope", response_model=JobState)
def post_estimate_scope(req: ScopeRunRequest) -> JobState:
    """Estimate step 1 — draft the scope (s01). REFUSES until the review register is approved (the
    review→estimate gate) — a 409 otherwise. DEMO runs inline; live runs as a background job."""
    _gate_or_409(req.set_id)
    if demo_mode():
        estimate_run.run_scope(req.set_id)
        conn = store.get_conn()
        try:
            scope = store.load_scope(conn, req.set_id)
        finally:
            conn.close()
        return JobState(kind="scope", status="done", stage="scoping", result=_scope_payload(req.set_id, scope))
    job_id = jobs.JOBS.create("scope")
    jobs.POOL.submit(_run_scope_job, job_id, req.set_id)
    return JobState(job_id=job_id, kind="scope", status="queued", stage="scoping")


@router.post("/estimate/scope/approve", response_model=ScopeGateState)
def post_estimate_scope_approve(req: ScopeApproval, actor: str = Depends(_actor)) -> ScopeGateState:
    """The scope gate — the ONLY writer of scope-approved state. An optional ``amended_summary``
    becomes the approved scope of record (the original draft is retained). Requires a scope draft to
    exist first.

    **The freeze gate.** Approving refuses while any pre-filled fallback is still unaccepted.
    That is the whole reason this gate exists: an unanswered query has to become an answer or a
    stated priced assumption before a number can be committed, and a fallback nobody accepted is
    neither — it is a machine's guess standing where a decision should be. The UI disables the
    button and names the lines, so this 409 is the backstop rather than the normal path.

    An open query does NOT block, and never did (locked decision 8). What blocks is pricing on a
    guess without recording that anyone agreed to it.
    """
    conn = store.get_conn()
    try:
        scope = store.load_scope(conn, req.set_id)
        if scope is None:
            raise HTTPException(status_code=404, detail=f"No scope draft for set {req.set_id!r}; run /estimate/scope first.")
        if req.approved:
            pending = store.unaccepted_fallbacks(conn, req.set_id)
            if pending:
                names = ", ".join(i.title or i.item_id for i in pending)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"{len(pending)} pre-filled fallback"
                        f"{'s are' if len(pending) != 1 else ' is'} still unaccepted: {names}. "
                        f"Each has to become an answer or an assumption you accept before the "
                        f"scope can be frozen — otherwise the price rests on a suggestion nobody "
                        f"agreed to."
                    ),
                )
        store.approve_scope(conn, req.set_id, req.approved, req.amended_summary)
        store.touch_set(conn, req.set_id, actor)
        scope = store.load_scope(conn, req.set_id)
        return ScopeGateState(set_id=req.set_id, scope_approved=scope.approved,
                              summary_of_record=scope.summary_of_record())
    finally:
        conn.close()


@router.get("/estimate/scope/{set_id}")
def get_estimate_scope(set_id: str) -> dict:
    """The persisted scope draft + approval state."""
    conn = store.get_conn()
    try:
        scope = store.load_scope(conn, set_id)
    finally:
        conn.close()
    if scope is None:
        raise HTTPException(status_code=404, detail=f"No scope draft for set {set_id!r}.")
    return _scope_payload(set_id, scope)


# ---------------------------------------------------------------------------
# The scope of record, item by item — the FREEZE gate
# ---------------------------------------------------------------------------
def _seed_text(scope, keywords: tuple[str, ...]) -> str:
    """A line of the s01 draft that plausibly covers this source, or "".

    Only ever a starting point, and it arrives badged ``ai`` precisely because it is one. When
    nothing matches, the line starts empty and badged ``user`` — which is the honest outcome:
    there was no draft prose, so the words will be the person's own.
    """
    if scope is None:
        return ""
    for note in scope.draft.notes:
        text = (note.text or "").lower()
        if any(k in text for k in keywords if len(k) > 4):
            return note.text
    return ""


def _scope_sources(conn, set_id: str) -> list[dict]:
    """Everything the scope could be built from, and whether it already has been.

    Derived on every read, never stored. The register, the open questions and the change log are
    each already the authority on their own contents; a stored copy here would go stale the
    moment a verdict changed or an answer arrived, and the scope would then be built on a
    snapshot nobody took deliberately.
    """
    mapped = {i.source_ref for i in store.load_scope_items(conn, set_id) if i.source_ref}
    scope = store.load_scope(conn, set_id)
    out: list[dict] = []

    # 1. Confirmed departures — the positions the register decided we ARE pressing.
    register = store.load_register(conn, set_id)
    for item in (register.items if register else []):
        if item.status != STATUS_CONFIRMED:
            continue
        ref = f"{models.SOURCE_DEPARTURE}:{item.item}"
        label = item.proposed_position or item.rationale
        out.append({
            "source_ref": ref, "group": models.SOURCE_DEPARTURE,
            "label": label[:180],
            "meta": f"item {item.item}" + (f" · cl. {item.clause}" if item.clause else ""),
            "section": models.SCOPE_QUALIFICATIONS,
            # Confirmed departures already carry the words we intend to send.
            "text": item.proposed_position or item.amendment_proposal or item.rationale,
            "mapped": ref in mapped,
        })

    # 2. Open questions — each one has to become an answer or a stated assumption HERE.
    for rfi in store.load_rfis(conn, set_id):
        if not rfi.is_open():
            continue
        ref = f"{models.SOURCE_RFI}:{rfi.rfi_id}"
        out.append({
            "source_ref": ref, "group": models.SOURCE_RFI,
            "label": rfi.question[:180],
            "meta": f"{rfi.rfi_id} · {rfi.status}" + (f" · cl. {rfi.clause}" if rfi.clause else ""),
            "section": models.SCOPE_FALLBACKS,
            "text": _seed_text(scope, tuple(rfi.question.lower().split())),
            "mapped": ref in mapped,
        })

    # 3. Amendments — what an addendum changed that the price has to reflect.
    for doc in store.list_documents(conn, set_id):
        if doc["kind"] == models.DOC_BASE or not doc["applied"]:
            continue
        ref = f"{models.SOURCE_ADDENDUM}:{doc['doc_id']}"
        out.append({
            "source_ref": ref, "group": models.SOURCE_ADDENDUM,
            "label": doc["ref"] or doc["filename"],
            "meta": f"{doc['kind']} · {(doc['received_at'] or '')[:10]}",
            "section": models.SCOPE_LOGISTICS,
            "text": "",
            "mapped": ref in mapped,
        })
    return out


def _scope_items_payload(conn, set_id: str) -> dict:
    items = store.load_scope_items(conn, set_id)
    pending = [i for i in items if i.is_fallback and not i.accepted]
    return {
        "set_id": set_id,
        "items": [i.model_dump() for i in items],
        "baseline": sum(1 for i in items if not i.is_fallback),
        "fallbacks_active": len(pending),
        "blocking": [
            {"item_id": i.item_id, "title": i.title or i.text[:80]} for i in pending
        ],
    }


@router.get("/estimate/scope/{set_id}/sources")
def get_scope_sources(set_id: str) -> dict:
    """What the scope of record could be built from: confirmed departures, open questions, and
    applied amendments — each with whether it has been mapped in yet.

    Nothing walks into the scope on its own. A source stays on this list until a person maps it,
    because the whole point of the gate is that somebody chose every line that ends up in the
    offer letter.
    """
    conn = store.get_conn()
    try:
        return {
            "set_id": set_id,
            "sources": _scope_sources(conn, set_id),
            **{k: v for k, v in _scope_items_payload(conn, set_id).items() if k != "set_id"},
        }
    finally:
        conn.close()


class ScopeMapRequest(BaseModel):
    set_id: str
    source_ref: str
    section: str = ""     # defaults to the source's natural section


@router.post("/estimate/scope/map")
def post_scope_map(req: ScopeMapRequest, actor: str = Depends(_actor)) -> dict:
    """Map one source into the scope of record.

    The badge is decided here and it is not cosmetic: a line seeded from draft prose is ``ai``,
    and a line that starts empty is ``user`` — because there is no model text in it to own. An
    open question maps as a **fallback**, which is what makes it show up at the gate until
    someone accepts or rewrites it.
    """
    conn = store.get_conn()
    try:
        sources = {s["source_ref"]: s for s in _scope_sources(conn, req.set_id)}
        source = sources.get(req.source_ref)
        if source is None:
            raise HTTPException(
                status_code=404,
                detail=f"{req.source_ref!r} is not a scope source for set {req.set_id!r}.",
            )
        if source["mapped"]:
            raise HTTPException(
                status_code=409, detail=f"{req.source_ref!r} is already in the scope.",
            )
        section = req.section or source["section"]
        if section not in models.SCOPE_SECTIONS:
            raise HTTPException(
                status_code=422,
                detail=f"section must be one of {list(models.SCOPE_SECTIONS)}; got {section!r}",
            )
        text = source["text"]
        item = store.save_scope_item(conn, req.set_id, models.ScopeItem(
            section=section,
            title=source["label"][:120],
            badge=models.BADGE_AI if text else models.BADGE_USER,
            is_fallback=source["group"] == models.SOURCE_RFI,
            accepted=False,
            text=text,
            source_ref=req.source_ref,
        ), now=_now())
        store.touch_set(conn, req.set_id, actor)
        return {"item": item.model_dump(), **_scope_items_payload(conn, req.set_id)}
    finally:
        conn.close()


class ScopeItemUpdate(BaseModel):
    set_id: str
    item_id: str
    text: str | None = None
    section: str | None = None
    title: str | None = None
    accept: bool | None = None       # accept a pre-filled fallback as the priced assumption
    convert_to_user: bool = False    # take ownership of the words without changing them


@router.post("/estimate/scope/item")
def post_scope_item(req: ScopeItemUpdate, actor: str = Depends(_actor)) -> dict:
    """Edit, accept, or take ownership of one scope line.

    **Editing always stamps it ``user``.** You edited it, you own it — there is no state in which
    a person's words are attributed to a model, and no state in which a model's words silently
    become a person's.

    Accepting a fallback is the freeze gate doing its work: an unanswered query stops being a
    machine's guess and becomes a priced assumption somebody stands behind. The words may still
    be the model's — the badge stays ``ai`` — but the decision to price on them is now recorded.
    """
    conn = store.get_conn()
    try:
        existing = next(
            (i for i in store.load_scope_items(conn, req.set_id) if i.item_id == req.item_id), None
        )
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"No scope line {req.item_id!r} on set {req.set_id!r}.",
            )
        update: dict = {}
        if req.text is not None and req.text != existing.text:
            update["text"] = req.text
            update["badge"] = models.BADGE_USER   # edited, therefore owned
        if req.title is not None:
            update["title"] = req.title
        if req.section is not None:
            if req.section not in models.SCOPE_SECTIONS:
                raise HTTPException(
                    status_code=422,
                    detail=f"section must be one of {list(models.SCOPE_SECTIONS)}",
                )
            update["section"] = req.section
        if req.accept is not None:
            update["accepted"] = req.accept
        if req.convert_to_user:
            update["badge"] = models.BADGE_USER

        item = store.save_scope_item(
            conn, req.set_id, existing.model_copy(update=update), now=_now()
        )
        store.touch_set(conn, req.set_id, actor)
        return {"item": item.model_dump(), **_scope_items_payload(conn, req.set_id)}
    finally:
        conn.close()


@router.delete("/estimate/scope/item/{set_id}/{item_id}")
def delete_scope_item(set_id: str, item_id: str, actor: str = Depends(_actor)) -> dict:
    """Unmap a scope line. The source returns to the rail, with nothing lost — sources are
    derived, so un-mapping is genuinely reversible."""
    conn = store.get_conn()
    try:
        if not store.delete_scope_item(conn, set_id, item_id):
            raise HTTPException(
                status_code=404, detail=f"No scope line {item_id!r} on set {set_id!r}.",
            )
        store.touch_set(conn, set_id, actor)
        return _scope_items_payload(conn, set_id)
    finally:
        conn.close()


@router.post("/estimate/run", response_model=JobState)
def post_estimate_run(req: EstimateRunRequest) -> JobState:
    """Run the ESTIMATE deterministic spine (s02→s03→s04→s05 + totals/margin). Two gates: the review
    register must be approved AND the estimate scope must be approved — each a distinct 409.

    Live: requires ``margin_pct`` and a structured ``schedule``; runs as a background job (poll
    ``/estimate/status/{job_id}``). DEMO: loads the fixture schedule + fixture margin and runs inline
    (offline), returning the estimate."""
    _gate_or_409(req.set_id)          # first gate: review approved
    _scope_gate_or_409(req.set_id)    # second gate: scope approved
    if demo_mode():
        estimate = estimate_run.run_estimate(
            req.set_id, estimate_run.DEMO_MARGIN_PCT, estimate_run.load_demo_schedule(),
            letter_meta=req.letter,
        )
        return JobState(kind="estimate", status="done", stage="persisting",
                        result=_estimate_payload(estimate))

    if req.schedule is None or req.margin_pct is None:
        raise HTTPException(status_code=422, detail="margin_pct and schedule are required for a live estimate run.")
    job_id = jobs.JOBS.create("estimate")
    jobs.POOL.submit(_run_estimate_job, job_id, req.set_id, req.margin_pct, req.schedule, req.letter)
    return JobState(job_id=job_id, kind="estimate", status="queued", stage="costing")


@router.get("/estimate/status/{job_id}", response_model=JobState)
def get_estimate_status(job_id: str) -> JobState:
    """Poll a background estimate job (same in-package job store as review)."""
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired client_boq job")
    return _job_state(job_id, job)


@router.get("/estimate/{set_id}")
def get_estimate(set_id: str) -> dict:
    """The persisted estimate for a document set: activities with per-line cost traces, indirects,
    flags, totals, and the margin readout."""
    conn = store.get_conn()
    try:
        estimate = store.load_estimate(conn, set_id)
    finally:
        conn.close()
    if estimate is None:
        raise HTTPException(status_code=404, detail=f"No estimate for set {set_id!r}.")
    return _estimate_payload(estimate)


@router.get("/estimate/{set_id}/workbook")
def get_estimate_workbook(set_id: str) -> Response:
    """The pricing workbook (.xlsx) generated deterministically from the persisted estimate — WBS
    summary, Resources, one sheet per activity, Indirect Costs, and Flags. Every figure equals the
    estimate exactly."""
    conn = store.get_conn()
    try:
        estimate = store.load_estimate(conn, set_id)
    finally:
        conn.close()
    if estimate is None:
        raise HTTPException(status_code=404, detail=f"No estimate for set {set_id!r}.")
    xlsx = estimate_workbook.build_workbook(estimate)
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="estimate_{set_id}.xlsx"'},
    )


def _audience_or_422(audience: str) -> str:
    if audience not in outputs.AUDIENCES:
        raise HTTPException(
            status_code=422,
            detail=f"audience must be one of {sorted(outputs.AUDIENCES)}; got {audience!r}",
        )
    return audience


@router.get("/review/{set_id}/citations")
def get_citations(set_id: str) -> dict:
    """Where each cited quotation physically sits in the document.

    Three verdicts, deliberately: ``located`` (page measured, with highlight rectangles as
    fractions of the page so a viewer can overlay them at any zoom), ``unverifiable`` (the part
    has no text layer, so we could not look — not the citation's fault), and ``not_located``
    (searchable, corroborated by neighbouring citations that WERE found, still missing — most
    likely a paraphrase rather than a quotation).
    """
    conn = store.get_conn()
    try:
        register = store.load_register(conn, set_id)
        parsed = store.load_parsed(conn, set_id)
        parts = [(spec, path) for spec, path, _ctx in store.load_parts(conn, set_id) if path]
    finally:
        conn.close()
    if register is None or parsed is None:
        raise HTTPException(status_code=404, detail=f"No reviewed register for set {set_id!r}.")
    if not parts:
        raise HTTPException(
            status_code=409,
            detail="This set has no split parts, so there is no document to search. Ingest it first.",
        )

    # strict=False: reporting only. The verdicts were already applied during the review; a read
    # of them must not quietly re-mark the register.
    checked = [i for i in register.items
               if i.status != models.STATUS_UNRESOLVED and i.clause]
    locations = s08_citation_verify.locate_citations(register, parsed, parts, strict=False)
    counts: dict[str, int] = {}
    for location in locations:
        counts[location.verdict] = counts.get(location.verdict, 0) + 1
    return {
        "set_id": set_id,
        "checked": len(locations),
        "by_verdict": counts,
        "citations": [
            {"item": item.item, "clause": item.clause, "cited_text": item.cited_text,
             **location.model_dump()}
            for item, location in zip(checked, locations)
        ],
    }


@router.get("/review/{set_id}/departure-schedule")
def get_departure_schedule(
    set_id: str, audience: str = "internal", format: str = "md",
) -> Response:
    """The Departure Schedule: every contract term we are not accepting as drafted.

    Deterministic — each row traces to a register line a human decided at the gate. Confirmed
    departures and still-open queries are listed; a line whose citation could not be verified is
    **withheld** and reported separately, because asking a client to amend a clause we cannot
    locate is worse than saying nothing.

    ``audience`` defaults to **internal**. Both reference tenders warn that qualifying a tender
    may cause it to be disqualified, so the submission version is opt-in and carries that warning
    quoted from the tender's own conditions.
    """
    _audience_or_422(audience)
    conn = store.get_conn()
    try:
        exists = store.load_register(conn, set_id) is not None
    finally:
        conn.close()
    if not exists:
        raise HTTPException(status_code=404, detail=f"No review register for set {set_id!r}.")

    if format == "xlsx":
        return Response(
            content=departure_schedule.render_xlsx(set_id, audience),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":
                     f'attachment; filename="departures_{set_id}_{audience}.xlsx"'},
        )
    if format != "md":
        raise HTTPException(status_code=422, detail="format must be 'md' or 'xlsx'.")
    return Response(content=departure_schedule.render_markdown(set_id, audience),
                    media_type="text/markdown; charset=utf-8")


@router.get("/estimate/{set_id}/qualifications")
def get_qualifications(set_id: str, audience: str = "internal") -> Response:
    """The Letter of Qualifications: the assumptions the price depends on.

    Assembled from confirmed departures, still-open queries (an unanswered question is a priced
    assumption whether or not anyone writes it down), and the approved scope of record. Every line
    carries its source in the internal version.

    Distinct from the Departure Schedule by design: that document is about contract TERMS, this
    one is about SCOPE and price. Internal by default, for the same reason.
    """
    _audience_or_422(audience)
    conn = store.get_conn()
    try:
        exists = store.load_set(conn, set_id) is not None
    finally:
        conn.close()
    if not exists:
        raise HTTPException(status_code=404, detail=f"No document set {set_id!r}.")
    return Response(content=qualifications.render_markdown(set_id, audience),
                    media_type="text/markdown; charset=utf-8")


@router.get("/estimate/{set_id}/letter")
def get_estimate_letter(set_id: str) -> dict:
    """The offer-letter DRAFT for a document set — the rendered markdown plus its structured pieces
    (price, inclusions/exclusions, pricing schedule, and Appendix A bullets with their source tags).
    A draft for human editing; nothing sends it."""
    conn = store.get_conn()
    try:
        letter = store.load_letter(conn, set_id)
    finally:
        conn.close()
    if letter is None:
        raise HTTPException(status_code=404, detail=f"No offer letter for set {set_id!r}; run the estimate first.")
    return {
        "set_id": set_id,
        "price": letter.price,
        "price_str": letter.price_str,
        "markdown": letter.markdown,
        "letter": letter.model_dump(),
    }
