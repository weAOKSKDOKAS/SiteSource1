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

import base64
import io
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from client_boq import criteria_loader, criteria_store, jobs, models, rates_store, store
from client_boq.boq import access as boq_access
from client_boq.boq import allocate as boq_allocate
from client_boq.boq import ask as boq_ask
from client_boq.boq import assumptions as boq_assumptions
from client_boq.boq import buildup as boq_buildup
from client_boq.boq import carry as boq_carry
from client_boq.boq import checks as boq_checks
from client_boq.boq import conditions as boq_conditions
from client_boq.boq import conservation as boq_conservation
from client_boq.boq import costing as boq_costing
from client_boq.boq import costing_workbook as boq_costing_workbook
from client_boq.boq import coverage as boq_coverage
from client_boq.boq import derive as boq_derive
from client_boq.boq import diff as boq_diff
from client_boq.boq import empirical as boq_empirical
from client_boq.boq import hk1980 as boq_hk1980
from client_boq.boq import optimiser as boq_optimiser
from client_boq.boq import docmap as boq_docmap
from client_boq.boq import model as boq_model
from client_boq.boq import georef as boq_georef
from client_boq.boq import roads as boq_roads
from client_boq.boq import groups as boq_groups
from client_boq.boq import outputs as boq_outputs
from client_boq.boq import photos as boq_photos
from client_boq.boq import pricing as boq_pricing
from client_boq.boq import production as boq_production
from client_boq.boq import programme as boq_programme
from client_boq.boq import reader as boq_reader
from client_boq.boq import schedule as boq_schedule
from client_boq.boq import schedule_paste as boq_schedule_paste
from client_boq.ingest import pdfops as boq_pdfops
from client_boq.ingest import schedule_read as boq_schedule_read
from client_boq.ingest import schedule_sheets as boq_sheets
from client_boq.boq import trace as boq_trace
from client_boq.boq import unbilled as boq_unbilled
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
from pipeline.workspace import UnsafeUploadPath, Workspace, safe_relative_path

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
    #
    # THREE numbers, because two of them were being added together and reported as one. The pool
    # holds two workers shared by every workflow, so a job can wait minutes behind another having
    # spent nothing — and `elapsed_seconds` counts from enqueue, so that wait was being shown as
    # run time. A 34-minute review that queued for 20 was doing 14 minutes of work.
    #
    # `elapsed_seconds` keeps its meaning (total since the request) so nothing reading it changes
    # under it; the split is additive. `queued_seconds` freezes when the work starts.
    elapsed_seconds: float = 0.0
    queued_seconds: float = 0.0      # waiting for a pool worker; frozen once running
    running_seconds: float = 0.0     # actually working; 0 while still queued
    # A cancel has been asked for but the current stage has not finished yet. The distinction
    # matters on screen: "stopping at the next step" is true, "stopped" would not be.
    cancel_requested: bool = False


class LiveJobsState(BaseModel):
    """Every job in flight for one set, so a screen can pick the one its tab owns.

    The singular answer was being asked to carry a choice it could not make: the pool is two wide,
    so an ingest and a review genuinely run at once, and whichever the server named was the one the
    strip described — regardless of which tab the operator was looking at.
    """

    set_id: str
    jobs: list[JobState] = Field(default_factory=list)


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
    "archive": ["reading", "extracting", "recording", "ingested"],   # bridge/archive.py
    # The drawing read reports per SHEET, and how many sheets triage found is not known
    # until it has run — so it names its stages dynamically and carries no fixed list.
    "review": ["ingesting", "summarising", "matching", "scope", "program", "cashflow",
               "assembling", "verifying", "locating"],
    "brain": ["grounding", "reading", "proposing"],
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
    # `mark_running` rather than `update(status="running")`: this is the moment the queue clock
    # stops and the run clock starts, and it is the only place in the system that knows it.
    jobs.JOBS.mark_running(job_id, stage)


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
    now = _time.monotonic()
    # Still queued: the queue clock is live and nothing has been spent. Running or finished: the
    # queue clock froze at `running_at`, and the run clock has been going since.
    queued = (job.running_at if job.running_at is not None else now) - job.started_at
    running = (now - job.running_at) if job.running_at is not None else 0.0
    return JobState(
        job_id=job_id, kind=job.kind, status=job.status, stage=job.stage,
        error=job.error or None, result=job.result if job.status == "done" else None,
        warnings=list(job.warnings), done=job.done, total=job.total,
        stage_index=job.stage_index, stage_total=job.stage_total,
        elapsed_seconds=round(now - job.started_at, 1),
        queued_seconds=round(max(0.0, queued), 1),
        running_seconds=round(max(0.0, running), 1),
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
        "uploaded": sorted(held),
        "note": (
            f"The findings below describe {_name_a_few(sorted(parsed.documents))} — not the "
            f"{len(held)} document(s) that were uploaded ({_name_a_few(sorted(held))}). Nothing "
            f"here can be located in your upload, so no quotation is highlighted. This is what an "
            f"offline DEMO run looks like: the review stage returned its bundled sample instead of "
            f"reading your files. Run this tender in LIVE mode to review it."
        ),
    }


def _name_a_few(names: list[str], limit: int = 3) -> str:
    """Name a couple and count the rest.

    The sentence used to inline every filename on both sides. That read fine for a binder plus two
    annexes and became a wall of text for a folder of 203 — the warning grew until it hid the
    findings it was warning about. The full lists are returned beside this as ``reviewed`` and
    ``uploaded``, so the screen can show them on demand; repeating them here bought nothing.
    """
    if not names:
        return "nothing"
    shown = ", ".join(Path(n).name for n in names[:limit])
    rest = len(names) - limit
    return shown if rest <= 0 else f"{shown} and {rest} more"


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
    from client_boq.ingest import folder as folder_mod

    # A folder set has no binder, so page coverage is not a fact about it: `coverage()` would report
    # "0 of 0 pages" against a set where every page is present. It reports files instead — which is
    # the thing that actually exists — and says the split was never in question.
    is_folder = manifest.tier == folder_mod.TIER_FOLDER
    # A TENDER PACK still inside its ZIP. `bridge.archive.plan_manifest` proposes one part per
    # content file with the manifest's own `source_doc` empty and each part carrying its own —
    # documented there as the shape `run_split` resolves with `part.source_doc or
    # manifest.source_doc`. That shape is the contract, so it is what this reads.
    #
    # It matters because the two layouts are unpacked by different code: a binder is CUT by
    # `/ingest/split`, and a pack is EXTRACTED by `/bridge/archive/extract`. Without this the
    # screen would offer to slice pages out of a document that is still a zip entry.
    is_archive = (not is_folder and not manifest.source_doc and bool(manifest.parts)
                  and all(p.source_doc for p in manifest.parts))
    return {
        "set_id": manifest.set_id,
        "source_doc": manifest.source_doc,
        "pages": manifest.pages,
        "tier": manifest.tier,
        "tier_reason": manifest.tier_reason,
        "approved": manifest.approved,
        "layout": "folder" if is_folder else "archive" if is_archive else "binder",
        "auto_approved": is_folder and manifest.approved,
        "file_count": len(manifest.parts) if is_folder else 0,
        "file_pages": sum(p.page_count() for p in manifest.parts) if is_folder else 0,
        "coverage": manifest.coverage(),
        "coverage_detail": ({"pages": 0, "covered": 0, "gaps": [], "overlaps": []} if is_folder
                            else pdfops.coverage(manifest, manifest.pages)),
        # ``part_id`` is a computed property, so ``model_dump`` drops it — and it is the identity
        # every other endpoint keys on. Adding it here rather than letting a client re-derive the
        # zero-pad-plus-abbreviation rule, which is exactly the sort of duplicated identity rule
        # that drifts. Sending it back in an edited manifest is harmless: it is not a field.
        "parts": [{**p.model_dump(), "part_id": p.part_id} for p in manifest.parts],
    }


def _folder_payload(plan) -> dict:
    """What a folder ingest returns: the manifest, plus what was routed and what is merely held.

    ``held`` is the point. Ingest is PDF-only, and until now a workbook or a Word file was written
    to disk and then silently absent from everything the screen shows. A file may be un-read; it may
    not be un-mentioned.
    """
    return {
        **_manifest_payload(plan.manifest),
        "summary": plan.summary(),
        "bills": [b.model_dump() for b in plan.bills],
        "held": [h.model_dump() for h in plan.held],
        "problems": plan.problems,
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


def _run_folder_job(job_id: str, uploads: list[RawUpload], project_name: str,
                    actor: str = "") -> None:
    """Ingest an organised folder end to end: list it, then materialise and interpret every part.

    Both halves in one job because a folder has no gate between them. Stopping after the manifest
    would leave a set that says "ingested" with nothing in it — which is exactly what it did before
    this existed, and it looked to the user like a broken split rather than a missing step.
    """
    jobs.JOBS.update(job_id, status="running", stage="reading")
    try:
        plan = ingest_run.run_folder_inspect(
            uploads, project_name, progress_cb=lambda s: jobs.JOBS.update(job_id, stage=s),
        )
        _stamp_new_set(plan.manifest.set_id, actor)
        ingest_run.run_split(
            plan.manifest.set_id,
            progress_cb=lambda s: jobs.JOBS.update(job_id, stage=s),
            # The count as NUMBERS, same as the plain split job: a two-hundred-file folder on one
            # unchanging word is indistinguishable from a hang.
            count_cb=_count_cb(job_id),
        )
        conn = store.get_conn()
        try:
            rows = store.load_parts(conn, plan.manifest.set_id)
            # The freshly interpreted parts may quote the submission-deadline clause; turn the
            # quote into the desk's close date (or an honest not_found) while it is hot.
            from client_boq.ingest import close_date as close_date_mod
            close_date_mod.derive(conn, plan.manifest.set_id)
            store.touch_set(conn, plan.manifest.set_id, actor)
        finally:
            conn.close()
        jobs.JOBS.update(job_id, status="done", stage="ingested",
                         done=len(rows), total=len(rows), result=_folder_payload(plan))
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


LAYOUT_BINDER = "binder"
LAYOUT_FOLDER = "folder"


@router.post("/ingest/upload", response_model=JobState)
def post_ingest_upload(
    files: Optional[list[UploadFile]] = File(None),
    project_name: str = Form(""),
    layout: str = Form(LAYOUT_BINDER),
    relative_paths: Optional[list[str]] = Form(None),
    actor: str = Depends(_actor),
) -> JobState:
    """Upload a tender and get back a split manifest.

    Two shapes, and the caller says which:

    ``binder`` (the default) — one monolithic PDF. Nothing is cut here and no review runs: this
    reads the document's own structure, asks the planner to refine it, and stops at the manifest so
    a human can correct the boundaries before anything expensive happens. Approve it at
    ``/ingest/manifest/approve``, then ``/ingest/split``.

    ``folder`` — a tree somebody already organised. Each file becomes its own part, the paths are
    kept, nothing is split and there is nothing to approve. ``relative_paths`` carries each file's
    place in the tree, index-aligned with ``files``, because a browser does not send
    ``webkitRelativePath`` over multipart and the paths would otherwise be lost.
    """
    mode = (layout or LAYOUT_BINDER).strip().lower()
    if mode not in (LAYOUT_BINDER, LAYOUT_FOLDER):
        raise HTTPException(status_code=422,
                            detail=f"layout must be {LAYOUT_BINDER!r} or {LAYOUT_FOLDER!r}.")

    incoming = list(files or [])
    paths = list(relative_paths or [])
    if mode == LAYOUT_FOLDER and paths and len(paths) != len(incoming):
        raise HTTPException(
            status_code=422,
            detail=(f"{len(paths)} relative paths for {len(incoming)} files. They are matched by "
                    f"position, so a mismatch would file documents under the wrong names."))

    uploads: list[RawUpload] = [
        (paths[i] if i < len(paths) and paths[i] else (f.filename or "document"),
         f.content_type, f.file.read())
        for i, f in enumerate(incoming)
    ]
    if not uploads:
        raise HTTPException(status_code=422, detail="Upload at least one PDF tender document.")

    if mode == LAYOUT_FOLDER:
        # Validate the paths HERE, before anything is queued. A rejected path is a fault in the
        # request, and answering it with a job the caller has to poll before learning that would
        # be a worse answer than a 400.
        for relative_path, _ct, _data in uploads:
            try:
                safe_relative_path(relative_path)
            except UnsafeUploadPath as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Queued, not inline. There is no gate to stop at, so the job runs all the way to
        # interpreted parts — and on a real package that is two hundred files to copy and read,
        # which no request should be holding open. The caller polls /ingest/status.
        job_id = jobs.JOBS.create("ingest")
        jobs.POOL.submit(_run_folder_job, job_id, uploads, project_name, actor)
        return JobState(job_id=job_id, kind="ingest", status="queued", stage="uploading")

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
    # No `set_id` here, and that is correct rather than an omission: this job CREATES the set. Its
    # id is not known until the manifest is planned, so there is nothing for `live_any_for` to
    # match on and a set that does not exist cannot have a job recovered for it.
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


@router.get("/jobs/live/{set_id}", response_model=JobState)
def get_live_job(set_id: str) -> JobState:
    """Whatever this set is doing right now, of any kind — or ``job_id: null`` if nothing.

    The screen's recovery route. Every other status endpoint needs a job id, which a browser that
    has just loaded does not have: the id lived in the closure of a poll loop in a component that
    unmounted, or in a tab that was never open. So a review would be running on the server while
    the Register tab rendered a Run button, and pressing it produced a 409 the UI had invited.

    NEVER 404s. "This set has no job" is a state, not an error — the same reasoning as
    ``/route/proposal`` returning an empty list rather than 404ing on a set that has not been
    routed. A 404 here would make the caller distinguish "no job" from "no set" on every poll, and
    both answers mean the same thing to a screen: render normally.
    """
    live = jobs.JOBS.live_all_for(set_id)
    job_id = live[0] if live else None
    job = jobs.JOBS.get(job_id) if job_id else None
    if job_id is None or job is None:
        # `job_id` stays None and the status enum is NOT widened — the client reads a null id as
        # "nothing running" rather than learning a sixth status that means the same thing.
        return JobState(status="queued", stage="")
    return _job_state(job_id, job)


@router.get("/jobs/live-all/{set_id}", response_model=LiveJobsState)
def get_live_jobs(set_id: str) -> LiveJobsState:
    """EVERY job in flight for this set, oldest first — the plural of ``/jobs/live/{set_id}``.

    The pool is two wide, so an ingest and a review genuinely run at the same time. The singular
    endpoint hands back the oldest, and the strip then named whichever that was: observed live
    reading ``INGEST · INTERPRETING · STAGE 2 OF 3`` while a review ran on the same set and the
    banner beside it discussed the review.

    With the list, a screen can show the job belonging to the tab in view, fall back to the most
    recently started when none maps to it, and — where more than one is live — SAY SO rather than
    silently picking one and presenting it as the answer.

    Never 404s, for the same reason as the singular: no job is a state, not an error.
    """
    live = jobs.JOBS.live_all_for(set_id)
    states = [_job_state(jid, job) for jid in live if (job := jobs.JOBS.get(jid)) is not None]
    return LiveJobsState(set_id=set_id, jobs=states)


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
    payload = _manifest_payload(manifest)
    if payload["layout"] == "folder":
        # What else arrived. `_folder_payload` puts these on the UPLOAD response only, so before
        # this the whole "what came in that is not a part" panel — the bills you have to pick from
        # and the held files — lasted exactly until the page was refreshed. A promise that a file
        # is never un-mentioned cannot be kept for one render.
        payload.update(_what_else_arrived(set_id, manifest))
    return payload


def _what_else_arrived(set_id: str, manifest) -> dict:
    """The bills and the held files of a folder set, recovered from what is on disk.

    Derived rather than stored, for the same reason the candidate route is: no table to migrate and
    no second copy of the truth to drift. A part is a file the manifest claims; anything else under
    ``docs/`` is either a bill, a signature for something present, or held.
    """
    from client_boq.ingest import folder as folder_mod

    docs = Workspace().docs_dir(set_id)
    if not docs.is_dir():
        return {"bills": [], "held": [], "problems": []}

    parts = {p.source_doc for p in manifest.parts}
    present = {p.relative_to(docs).as_posix() for p in docs.rglob("*") if p.is_file()}
    bills = get_bill_candidates(set_id)["candidates"]
    billed = {b["relative_path"] for b in bills}

    held = []
    for path in sorted(p for p in docs.rglob("*") if p.is_file()):
        relative = path.relative_to(docs).as_posix()
        if relative in parts or relative in billed:
            continue
        suffix = path.suffix.lower()
        if suffix in folder_mod._SIGNATURE_SUFFIXES and relative[: -len(suffix)] in present:
            continue          # proof about a file that IS here, not a file nobody read
        held.append({"relative_path": relative, "suffix": suffix,
                     "bytes": path.stat().st_size, "note": folder_mod.HELD_NOTE})

    problems = []
    if len(bills) > 1 and not any(b["already_imported"] for b in bills):
        proposed = next((b for b in bills if b["proposed"]), None)
        problems.append(
            f"{len(bills)} workbooks parse as a bill of quantities. Which one is operative is a "
            f"decision, so none was imported"
            + (f" — {proposed['relative_path']} looks current ({proposed['why']})." if proposed else "."))
    return {"bills": bills, "held": held, "problems": problems}


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
                detail=f"No split manifest for set {req.set_id!r}; upload the tender "
                       f"documents first.",
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


def _no_review_in_flight_or_409(set_id: str) -> None:
    """Refuse a second review on a set that already has one running or queued.

    REFUSED, not queued. Four reviews were once started on one set — four separate POSTs, four
    real job ids — because the Run button's `busy` flag lived in a tab component that unmounts
    when you navigate away, so leaving the tab and coming back re-armed it. Nothing on the server
    objected: `/review/run` created and submitted unconditionally.

    Queueing the second one would be the wrong repair. The pool has two workers shared by every
    workflow, so duplicates do not merely waste a run — they occupy a worker the FIRST review's
    successor stages need, and they push unrelated ingest and estimate work behind them. And two
    reviews of one set race to write the same register: the second overwrites the first's verdicts
    with its own, which is the same document reviewed twice and the operator's own judgement lost.

    A cancelled or finished job is not in flight and does not block a re-run. The id is named so
    the answer is actionable — the caller can poll it, or cancel it, rather than guess.
    """
    live = jobs.JOBS.live_for("review", set_id)
    if live:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A review is already running on this document set (job {live}). Starting a "
                "second one would overwrite the first's register, so it was refused rather than "
                "queued. Wait for it, or cancel it and start again."
            ),
        )


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
    job_id = jobs.JOBS.create("ingest", set_id=req.set_id)
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
# The output book (Outputs and norms)
#
# The rate book's sibling: rates say what a crew costs an hour, outputs say how many hours the work
# takes. Both are the COMPANY's, not a job's — a tender inherits them and may override any line, and
# client_boq.boq.outputs.resolve is the single place BOOK/YOURS/MISSING is decided.
# ---------------------------------------------------------------------------
class OutputEdit(BaseModel):
    """One norm. The key is in the path; only the value is editable."""
    value: float | None = None


@router.get("/library/outputs")
def get_outputs() -> dict:
    """The output book — every declared norm, its value, and whether that value is the shipped
    default or one somebody set.

    Returns the declarations alongside the values so the screen has the label, unit, block and the
    `⌞` explanation without a second source of truth to keep in step. Adding a norm is one entry in
    ``outputs.NORMS`` and it appears here.
    """
    from client_boq.boq import outputs as outputs_mod
    conn = store.get_conn()
    try:
        book = store.load_output_book(conn)
        meta = store.output_norm_meta(conn)
    finally:
        conn.close()
    return {
        "blocks": [
            {
                "id": block,
                "title": outputs_mod.BLOCK_TITLE[block],
                "rows": [
                    {
                        "key": norm.key,
                        "label": norm.label,
                        "unit": norm.unit,
                        "note": norm.note,
                        "value": book.get(norm.key),
                        "default": norm.default,
                        # `seed` mirrors the rate book's source column: a number nobody has
                        # touched should not claim to be somebody's decision.
                        "source": "you" if norm.key in meta else "seed",
                        "updated_by": meta.get(norm.key, {}).get("updated_by", ""),
                        "updated_at": meta.get(norm.key, {}).get("updated_at"),
                    }
                    for norm in outputs_mod.NORMS if norm.block == block
                ],
            }
            for block in outputs_mod.BLOCK_ORDER
        ],
        "count": len(outputs_mod.NORMS),
    }


@router.post("/library/outputs/{key}")
def post_output_norm(key: str, req: OutputEdit, actor: str = Depends(_actor)) -> dict:
    """Set one norm. Refuses a key the book does not declare.

    A norm is not free-form the way a rate id is: rates are the company's own codes, but an output
    only means anything because the engine reads it, so an undeclared key would be a number nobody
    ever consults sitting on a screen looking authoritative.
    """
    from client_boq.boq import outputs as outputs_mod
    norm = outputs_mod.NORM_INDEX.get(key)
    if norm is None:
        raise HTTPException(
            status_code=404,
            detail=(f"There is no norm {key!r}. The book declares: "
                    f"{', '.join(sorted(outputs_mod.NORM_INDEX))}."))
    if req.value is None:
        raise HTTPException(status_code=422, detail=f"{norm.label} must be a number.")
    conn = store.get_conn()
    try:
        store.save_output_norm(conn, key, req.value, unit=norm.unit, actor=actor)
        book = store.load_output_book(conn)
    finally:
        conn.close()
    return {"key": key, "value": book.get(key), "default": norm.default}


@router.delete("/library/outputs/{key}")
def delete_output_norm(key: str) -> dict:
    """Put one norm back to the shipped default by forgetting your value.

    Not an archive, unlike a rate: a norm cannot be removed from the book — the engine reads it
    whatever happens — so the only meaningful undo is to stop overriding the default.
    """
    from client_boq.boq import outputs as outputs_mod
    norm = outputs_mod.NORM_INDEX.get(key)
    if norm is None:
        raise HTTPException(status_code=404, detail=f"There is no norm {key!r}.")
    conn = store.get_conn()
    try:
        conn.execute("DELETE FROM client_boq_outputs WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()
    return {"key": key, "value": norm.default, "default": norm.default, "source": "seed"}


# ---------------------------------------------------------------------------
# App-wide settings — the AI model
# ---------------------------------------------------------------------------
class LLMSettings(BaseModel):
    provider: str = ""          # "" = auto (env routing) | anthropic | deepseek | openai
    # THE DRAWING READ IS ITS OWN QUESTION. It runs once or twice per tender, reads a
    # legal-quality drawing, and everything downstream rests on what it returns — so it is the one
    # call where the strongest model is worth its cost and its latency, and picking it here must
    # not also change the model that classifies a document or drafts an enquiry. `model_drawing`
    # names a MODEL rather than a provider, which is the shape that did not exist: every other
    # model setting is per provider.
    provider_drawing: str = ""
    model_drawing: str = ""
    # THE BRAIN IS ITS OWN QUESTION for the same reason: it runs rarely, reads everything at
    # once, and steers where a person looks next — "one strong model to understand it all" must
    # not also change the model that classifies a document. Falls through to `provider`, not to
    # ingest: the brain reasons over what was read; it reads no pages.
    provider_brain: str = ""
    model_brain: str = ""
    # Who reads the documents. Separate because reading the tender is a different job from the
    # stages that reason about what was read, and it decides what all of them are looking at.
    # "" falls through to EXTRACTION_PROVIDER, then to `provider`.
    provider_ingest: str = ""
    model_anthropic: str = ""   # "" = the env/code default
    model_deepseek: str = ""
    model_openai: str = ""


class CompanySettings(BaseModel):
    """The letterhead the offer letter goes out on.

    App-wide, because it is the same on every tender. The CLIENT's name and the project come from
    that tender's own desk metadata instead, so nothing is typed twice — and the date is stamped at
    run time rather than stored, because a letter's date is the day it was produced.
    """

    company_name: str = ""
    company_address: str = ""
    contact_name: str = ""
    contact_number: str = ""


# The keys the letterhead lives under, prefixed so the settings table stays legible as it grows.
COMPANY_KEYS = ("letter.company_name", "letter.company_address",
                "letter.contact_name", "letter.contact_number")


def _company_settings(conn) -> dict:
    """The stored letterhead, as the field names ``LetterMeta`` uses. Blank means unset, which the
    Offer screen says out loud rather than papering over with a plausible company name."""
    return {key.split(".", 1)[1]: store.get_setting(conn, key) for key in COMPANY_KEYS}


@router.get("/settings")
def get_settings() -> dict:
    """The app-wide LLM settings, plus what they actually mean at call time.

    ``effective`` reports what the stored values actually resolve to at call time — including the
    one thing no setting can override: page images go to a provider that can read one, and a
    text-only provider falls back rather than pretending to have read a scanned page.
    """
    from client_boq import llm as llm_mod
    from pipeline.llm_client import (
        VISION_CAPABLE,
        VISION_FALLBACK,
        model_for_provider,
        provider_key,
    )
    cfg = llm_mod.current_settings()
    conn = store.get_conn()
    try:
        rows = store.list_settings(conn)
        company = _company_settings(conn)
    finally:
        conn.close()

    text_provider = cfg["provider"] or ("deepseek" if provider_key("deepseek") else "anthropic")
    ingest_provider = llm_mod.resolve_provider(cfg, llm_mod.STAGE_INGEST) or text_provider
    drawing_provider = llm_mod.resolve_provider(cfg, llm_mod.STAGE_DRAWING) or ingest_provider
    return {
        **cfg,
        "company": company,
        "providers": [p for p in llm_mod.PROVIDERS if p],
        "effective": {
            "text_provider": text_provider,
            # Who reads the documents, and who reads a SCANNED one — which are the same provider
            # unless it cannot take images, in which case the fallback is named rather than implied.
            "ingest_provider": ingest_provider,
            "vision_provider": (ingest_provider if ingest_provider in VISION_CAPABLE
                                else VISION_FALLBACK),
            "vision_capable": sorted(VISION_CAPABLE),
            "model_anthropic": cfg["model_anthropic"] or model_for_provider("anthropic"),
            "model_deepseek": cfg["model_deepseek"] or model_for_provider("deepseek"),
            "model_openai": cfg["model_openai"] or model_for_provider("openai"),
            "model_ingest": (cfg.get(llm_mod.MODEL_KEY.get(ingest_provider, ""))
                             or model_for_provider(ingest_provider)),
            # WHO READS THE DRAWING, resolved the same way the reader resolves it — so the screen
            # shows what will actually happen rather than what was typed.
            "drawing_provider": drawing_provider,
            "model_drawing": (cfg.get("model_drawing")
                              or cfg.get(llm_mod.MODEL_KEY.get(drawing_provider, ""))
                              or model_for_provider(drawing_provider)),
            # WHO IS THE BRAIN, resolved the same way the run resolves it.
            "brain_provider": (llm_mod.resolve_provider(cfg, llm_mod.STAGE_BRAIN)
                               or text_provider),
            "model_brain": (cfg.get("model_brain")
                            or cfg.get(llm_mod.MODEL_KEY.get(
                                llm_mod.resolve_provider(cfg, llm_mod.STAGE_BRAIN)
                                or text_provider, ""))
                            or model_for_provider(llm_mod.resolve_provider(
                                cfg, llm_mod.STAGE_BRAIN) or text_provider)),
        },
        "rows": rows,
    }


class ModeRequest(BaseModel):
    """Demo or live. ``None`` clears the operator's override back to the deployment's default."""
    demo: Optional[bool] = None
    #: A person typing the word, because this decides whether a tender is a real tender and
    #: whether an enquiry is a real email. Nothing about this should be one click.
    confirm: str = ""


def _mode_payload() -> dict:
    """What mode the app is in, where that came from, and whether the other mode would work.

    THE MISSING-KEY CHECK IS THE POINT of doing this here rather than at the first model call. In
    demo there is no key to have, so nothing complains — and the first thing live mode does is a
    document read, which is minutes into a job and looks like a failure of the tender rather than
    of the configuration.
    """
    from pipeline.llm_client import (
        PROVIDER_KEY_ENV,
        demo_mode,
        demo_mode_source,
        provider_key,
    )
    from client_boq import llm as llm_mod

    cfg = llm_mod.current_settings()
    text_provider = cfg["provider"] or ("deepseek" if provider_key("deepseek") else "anthropic")
    ingest = llm_mod.resolve_provider(cfg, llm_mod.STAGE_INGEST) or text_provider
    needed = sorted({text_provider, ingest})
    missing = [p for p in needed if not provider_key(p)]
    return {
        "demo": demo_mode(),
        "source": demo_mode_source(),
        # Says plainly that the switch is for this process. A restart returns to the deployment's
        # own answer, which is the safe direction: nobody can leave a server in demo by forgetting.
        "reverts_on_restart": True,
        "env_default": os.getenv("DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"},
        "providers_needed": needed,
        "providers_missing": missing,
        "live_ready": not missing,
        "set_to_go_live": {p: list(PROVIDER_KEY_ENV.get(p, ())) for p in missing},
        "blocked_because": ("" if not missing else
                            f"live mode would call {' and '.join(missing)} and no key is set for "
                            f"{'either' if len(missing) > 1 else 'it'}. Set "
                            f"{' or '.join(n for p in missing for n in PROVIDER_KEY_ENV.get(p, ()))}"
                            f" in siteclaim/backend/.env and restart, or pick a provider that has "
                            f"a key on Settings."),
    }


@router.get("/mode")
def get_mode() -> dict:
    """Demo or live, and what it would take to change it. A pure read."""
    return _mode_payload()


@router.post("/mode")
def post_mode(req: ModeRequest, actor: str = Depends(_actor)) -> dict:
    """Switch the whole app between demo and live. **The only writer of the override.**

    Refuses to go live with no key rather than letting the first model call discover it, and
    refuses without the word typed — this decides whether outbound email is real, whether a tender
    is a real tender, and whether a token is spent. Turning demo ON is never refused: going offline
    is always safe, and a switch that can be hard to reach in the safe direction is a switch people
    route around.
    """
    from pipeline.llm_client import set_demo_mode

    if req.demo is False:
        state = _mode_payload()
        if not state["live_ready"]:
            raise HTTPException(status_code=409, detail=state["blocked_because"])
        if req.confirm.strip().upper() != "LIVE":
            raise HTTPException(
                status_code=409,
                detail=("Going live means real API spend, real outbound email and real tenders. "
                        "Type LIVE to confirm."))
    set_demo_mode(req.demo)
    return {**_mode_payload(), "changed_by": actor}


@router.post("/company")
def post_company(req: CompanySettings, actor: str = Depends(_actor)) -> dict:
    """Save the letterhead. Blank fields are allowed and stay blank — the offer letter renders a
    visible placeholder for anything unset rather than inventing a company name, which is the same
    rule the rest of this product follows about not filling gaps on a person's behalf."""
    conn = store.get_conn()
    try:
        for key, value in zip(COMPANY_KEYS, (req.company_name, req.company_address,
                                             req.contact_name, req.contact_number)):
            store.set_setting(conn, key, value.strip(), actor)
    finally:
        conn.close()
    return get_settings()


@router.post("/settings")
def post_settings(req: LLMSettings, actor: str = Depends(_actor)) -> dict:
    """Set the app-wide model choice. Applies to every client_boq AI stage from the next run —
    stages construct their client per run, so nothing needs restarting. Procurement is not
    affected: this setting is read only by ``client_boq/llm.py``."""
    from client_boq import llm as llm_mod
    for field, value in (("provider", req.provider), ("provider_ingest", req.provider_ingest),
                         ("provider_drawing", req.provider_drawing),
                         ("provider_brain", req.provider_brain)):
        if value not in llm_mod.PROVIDERS:
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be one of "
                       f"{[p or 'auto' for p in llm_mod.PROVIDERS]}")
    conn = store.get_conn()
    try:
        store.set_setting(conn, llm_mod.SETTING_PROVIDER, req.provider, actor)
        store.set_setting(conn, llm_mod.SETTING_PROVIDER_INGEST, req.provider_ingest, actor)
        store.set_setting(conn, llm_mod.SETTING_MODEL_ANTHROPIC, req.model_anthropic.strip(), actor)
        store.set_setting(conn, llm_mod.SETTING_MODEL_DEEPSEEK, req.model_deepseek.strip(), actor)
        store.set_setting(conn, llm_mod.SETTING_MODEL_OPENAI, req.model_openai.strip(), actor)
        store.set_setting(conn, llm_mod.SETTING_PROVIDER_DRAWING, req.provider_drawing, actor)
        store.set_setting(conn, llm_mod.SETTING_MODEL_DRAWING, req.model_drawing.strip(), actor)
        store.set_setting(conn, llm_mod.SETTING_PROVIDER_BRAIN, req.provider_brain, actor)
        store.set_setting(conn, llm_mod.SETTING_MODEL_BRAIN, req.model_brain.strip(), actor)
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
    from pipeline.llm_client import demo_mode

    conn = store.get_conn()
    try:
        sets = store.list_sets(conn, include_archived=include_archived)
        for entry in sets:
            _backfill_close_date(conn, entry)
    finally:
        conn.close()
    # DEMO AND LIVE TENDERS CANNOT MIX, and the reason is structural rather than a filter: in demo
    # `store.get_conn` opens a different DATABASE FILE (`store.py:72`), so this list is only ever
    # one or the other. What it could not do until now is SAY which — and `set_id = tender_slug(
    # name)`, so a demo tender and a live tender sharing a name share an id in two different files.
    # Flipping the switch would then swap which one an open screen is showing, silently.
    #
    # Derived per read, never stored: a stored flag would say "demo" about a row in the live DB the
    # moment somebody copied one across, which is exactly when you need it to be right.
    demo = demo_mode()
    for entry in sets:
        entry["demo"] = demo
    return {"count": len(sets), "sets": sets, "demo": demo}


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


class LocateInSetRequest(BaseModel):
    quote: str
    #: The part to try first — normally whatever the viewer is already showing. An optimisation
    #: and nothing more: the answer is identical either way, it just arrives sooner when the
    #: guess is right.
    prefer_part_id: str = ""


@router.post("/ingest/{set_id}/locate")
def post_set_locate(set_id: str, req: LocateInSetRequest) -> dict:
    """Find a quotation **anywhere in the set**, and say which part it is in.

    The per-part route above answers "is this quote on these pages". That is the wrong question for
    a "show me on the page" button, and answering the wrong question is what made the button
    confusing: it searched whichever document happened to be open, so on a 203-part set it reported
    "not found" 202 times out of 203 while the words sat in a file it never looked at. The user then
    has to guess the right document by hand — which is the job they clicked the button to avoid.

    So this searches every part and reports **where** the words are. Same three verdicts, one extra
    fact (``part_id``), and the caller switches the viewer to it.

    Ordering is by part, first hit wins, so the common case is fast. A complete miss is the
    expensive case because it has to look everywhere before it can honestly say "nowhere" —
    measured at 6.5s over the reference set's 203 parts / 131 MB. That is the price of the honest
    answer, and it is paid on an explicit click, not on render.
    """
    quote = (req.quote or "").strip()
    if not quote:
        raise HTTPException(status_code=422, detail="Nothing to locate.")

    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No parts in set {set_id!r}.")

    # The preferred part first; everything else in its own order behind it.
    ordered = sorted(rows, key=lambda r: r[0].part_id != req.prefer_part_id)

    searched = 0        # parts we could actually look inside
    unsearchable = 0    # parts with no text layer — looked at, could not be read
    for spec, path, _context in ordered:
        if not path:
            continue
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        if not pdfops.has_text_layer(data):
            unsearchable += 1
            continue
        searched += 1
        found = pdfops.locate(data, quote, page_offset=spec.start - 1)
        if not found:
            continue
        return {
            "verdict": models.LOCATED, "part_id": spec.part_id, "part_title": spec.title,
            "page": found["page"], "match": found["match"], "highlights": found["highlights"],
            "note": (f"found on page {found['page']} of {spec.part_id}"
                     if found["match"] == "exact"
                     else f"a distinctive fragment was found on page {found['page']} of {spec.part_id}"),
        }

    if not searched:
        # Nothing in the whole set could be read. Calling that "not found" would blame the
        # quotation for a set of scans.
        return {
            "verdict": models.UNVERIFIABLE, "part_id": "", "part_title": "", "page": None,
            "highlights": [],
            "note": (f"none of the {unsearchable} document(s) in this set have a text layer, so "
                     f"the quotation could not be searched for. Read the pages to check it."),
        }
    return {
        "verdict": models.NOT_LOCATED, "part_id": "", "part_title": "", "page": None,
        "highlights": [],
        "note": (f"these words are not in any of the {searched} searchable document(s) in this set"
                 + (f" ({unsearchable} more could not be read)" if unsearchable else "")
                 + ". The finding is quoting a document that is not in this upload, or "
                   "paraphrasing rather than quoting."),
    }


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
        "highlights": found["highlights"],
        # An exact hit and a fragment hit are both `located`, and they are not equally strong: a
        # fragment means the search fell back to the most distinctive run of words in the quote,
        # so the highlight proves *that phrase* is on the page, not the whole sentence. Saying so
        # costs one line and is the same wording s08 uses for the precomputed marks.
        "note": (f"found on page {found['page']}" if found["match"] == "exact"
                 else f"a distinctive fragment was found on page {found['page']}"),
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
            detail=f"No split parts for set {set_id!r}; split the binder into parts on "
                   f"Documents first.",
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
                    set_id: str = "", include_specifications: bool = False) -> None:
    """Background worker: run the review and record progress/result/error on the job."""
    try:
        _begin(job_id, "ingesting")
        register = review_run.run_review(
            uploads, project_name, set_id=set_id,
            progress_cb=_stage_cb(job_id, "review"),
            count_cb=_count_cb(job_id),
            on_note=lambda m: jobs.JOBS.add_warning(job_id, m),
            include_specifications=include_specifications,
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
    include_specifications: bool = Form(False),
) -> JobState:
    """Run REVIEW (s01→…→s08) over a document set. Live: kick off a background job and poll
    ``/review/status/{job_id}``. DEMO: run inline and return the register offline (no job, no
    network) — the fixtures drive a full register.

    Two ways to name the documents:

    * ``set_id`` of a set already through ``/ingest`` — the review reads its approved parts one
      at a time, and each clause carries the part it came from. Refuses with a 409 if that set's
      split manifest has not been approved.
    * ``files`` — loose documents reviewed directly, for a single document with nothing to split.

    ``include_specifications`` reads the specification tree too. Off by default: on CEDD
    ND/2025/04 that category is ~150 of 206 parts and is mostly appendices — borehole logs, test
    schedules — which carry no contractual position. The deferred parts are NAMED in the run's
    notes rather than dropped, and re-running with this set reads them.
    """
    uploads: list[RawUpload] = [
        (f.filename or "document", f.content_type, f.file.read()) for f in (files or [])
    ]
    if set_id:
        _manifest_gate_or_409(set_id)
        _no_review_in_flight_or_409(set_id)
    if demo_mode():
        register = review_run.run_review(
            uploads, project_name, set_id=set_id,
            include_specifications=include_specifications,
        )
        return JobState(status="done", stage="verifying", result=_result_payload(register))

    job_id = jobs.JOBS.create("review", set_id=set_id)
    jobs.POOL.submit(_run_review_job, job_id, uploads, project_name, set_id,
                     include_specifications)
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


class ScheduleSaveRequest(BaseModel):
    set_id: str
    schedule: EstimateSchedule
    margin_pct: float = 0.0


@router.get("/estimate/schedule/{set_id}")
def get_estimate_schedule(set_id: str) -> dict:
    """The pricing schedule a live estimate will be run FROM — quantities, resources, the margin.

    `/estimate/run` takes the schedule in its request body and DEMO fills it from a fixture, so
    until a person had to type one, nothing persisted it. A bill of quantities is far too much work
    to retype for every re-run — and a re-run is exactly what a corrected quantity or an edited rate
    causes. `saved` is false when this set has never had one, which is a state the screen shows
    rather than an error.
    """
    conn = store.get_conn()
    try:
        schedule, margin = store.load_schedule(conn, set_id)
        meta = store.schedule_meta(conn, set_id)
    finally:
        conn.close()
    return {
        "set_id": set_id,
        "saved": schedule is not None,
        "schedule": (schedule or EstimateSchedule()).model_dump(),
        "margin_pct": margin,
        **meta,
    }


@router.post("/estimate/schedule")
def post_estimate_schedule(req: ScheduleSaveRequest, actor: str = Depends(_actor)) -> dict:
    """Save the schedule and margin for a set. Stores the INPUT to the estimate, never its output —
    the priced result is still computed only by the deterministic spine, on `/estimate/run`."""
    conn = store.get_conn()
    try:
        store.save_schedule(conn, req.set_id, req.schedule, req.margin_pct, actor)
        meta = store.schedule_meta(conn, req.set_id)
    finally:
        conn.close()
    return {
        "set_id": req.set_id,
        "saved": True,
        "schedule": req.schedule.model_dump(),
        "margin_pct": req.margin_pct,
        **meta,
    }


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


def _gate_or_409(set_id: str) -> Optional[str]:
    """The review→estimate gate. Returns a warning in soft mode, ``None`` when there is none.

    **V1 DELIBERATE DEPARTURE from the locked review→estimate hard-gate decision.** Default
    ``REVIEW_GATE=soft`` lets the estimate run on an unapproved register and warns instead of
    409ing; ``REVIEW_GATE=hard`` restores the original behaviour exactly. See ``client_boq/gates.py``.

    The caller must surface the return value — both do, onto the job's warnings. A soft gate that
    says nothing is worse than no gate, because silence reads as approval.

    ``_scope_gate_or_409`` below is NOT affected and must not be: the scope freeze is a DATA
    dependency (the estimate cannot price a scope that does not exist), not a review gate.
    """
    from client_boq.gates import SOFT_GATE_WARNING, review_gate_is_soft

    conn = store.get_conn()
    try:
        if store.review_is_approved(conn, set_id):
            return None
        if review_gate_is_soft():
            return SOFT_GATE_WARNING
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
    """Estimate step 1 — draft the scope (s01). Behind the review→estimate gate: a 409 under
    ``REVIEW_GATE=hard``, a warning on the response under the V1 default ``soft``. DEMO runs
    inline; live runs as a background job."""
    gate_note = _gate_or_409(req.set_id)
    if demo_mode():
        estimate_run.run_scope(req.set_id)
        conn = store.get_conn()
        try:
            scope = store.load_scope(conn, req.set_id)
        finally:
            conn.close()
        return JobState(kind="scope", status="done", stage="scoping",
                        warnings=[gate_note] if gate_note else [],
                        result=_scope_payload(req.set_id, scope))
    job_id = jobs.JOBS.create("scope", set_id=req.set_id)
    # Attached BEFORE submit, so the warning is on the job from its first poll rather than racing
    # the worker — a bypass the operator only learns about at the end is one they already acted on.
    if gate_note:
        jobs.JOBS.add_warning(job_id, gate_note)
    jobs.POOL.submit(_run_scope_job, job_id, req.set_id)
    return JobState(job_id=job_id, kind="scope", status="queued", stage="scoping",
                    warnings=[gate_note] if gate_note else [])


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
            raise HTTPException(status_code=404, detail=f"No scope draft for set "
                                f"{req.set_id!r}; draft the scope on the Scope tab first.")
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
    # First gate: review approved. Soft by default in V1 — warns rather than refusing.
    gate_note = _gate_or_409(req.set_id)
    # Second gate: scope approved. UNCHANGED and deliberately so — the scope freeze is a data
    # dependency, not a review gate, and there is nothing to price without it.
    _scope_gate_or_409(req.set_id)
    if demo_mode():
        estimate = estimate_run.run_estimate(
            req.set_id, estimate_run.DEMO_MARGIN_PCT, estimate_run.load_demo_schedule(),
            letter_meta=req.letter,
        )
        return JobState(kind="estimate", status="done", stage="persisting",
                        warnings=[gate_note] if gate_note else [],
                        result=_estimate_payload(estimate))

    if req.schedule is None or req.margin_pct is None:
        raise HTTPException(status_code=422, detail="margin_pct and schedule are required for a live estimate run.")
    job_id = jobs.JOBS.create("estimate", set_id=req.set_id)
    if gate_note:
        jobs.JOBS.add_warning(job_id, gate_note)
    jobs.POOL.submit(_run_estimate_job, job_id, req.set_id, req.margin_pct, req.schedule, req.letter)
    return JobState(job_id=job_id, kind="estimate", status="queued", stage="costing",
                    warnings=[gate_note] if gate_note else [])


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


# ---------------------------------------------------------------------------
# BOQ — the client's bill of quantities: import it, diff it, price it, check it
# ---------------------------------------------------------------------------
# Everything below is deterministic. There is no job polling here and no DEMO/LIVE fork, because
# nothing in this surface calls a model: reading a workbook, comparing two revisions and multiplying
# a quantity by a rate are all things arithmetic settles. See boq/__init__.py.
class BillRateRequest(BaseModel):
    set_id: str
    full_ref: str
    rev: Optional[int] = None
    rate: Optional[float] = None
    build_up: Optional[models.ScheduleItem] = None
    basis: str = ""
    needs_review: bool = False
    review_note: str = ""


class AssumptionRequest(BaseModel):
    set_id: str
    rev: Optional[int] = None
    assumption: models.ItemAssumption


class CarryRequest(BaseModel):
    set_id: str
    from_rev: int
    to_rev: int
    apply: bool = False


def _bill_or_404(conn, set_id: str, rev: Optional[int] = None) -> models.ClientBill:
    bill = store.load_bill(conn, set_id, rev)
    if bill is None:
        where = "" if rev is None else f" at revision {rev}"
        raise HTTPException(
            status_code=404,
            detail=f"No bill of quantities for set {set_id!r}{where}. Import the client's "
                   f"workbook on the Price tab first.")
    return bill


def _reprice_gate_or_409(conn, set_id: str, rev: int) -> None:
    """A revision cannot be signed off while a carried rate is still unlooked-at.

    The mirror of the rule the review side already applies to clauses: when an addendum rewrites
    wording somebody had approved, the approval is torn up rather than quietly inherited. Here it is
    a rate. GCT App C 2.2(v) carries a rate onto a changed quantity without comment, which is legal
    and is not the same as being right — the reference addendum multiplied three monitoring
    quantities by 2.17 under exactly that rule.
    """
    pending = store.bill_review_pending(conn, set_id, rev)
    if pending:
        names = ", ".join(entry["full_ref"] for entry in pending[:8])
        more = f" and {len(pending) - 8} more" if len(pending) > 8 else ""
        raise HTTPException(
            status_code=409,
            detail=(f"{len(pending)} item{'s' if len(pending) != 1 else ''} carried into revision "
                    f"{rev} still to be looked at: {names}{more}. A rate carried onto a changed "
                    f"quantity or a reworded item is what the correction rules do, not a decision "
                    f"anyone made — confirm each before this revision stands behind a price."))


def _import_workbook(set_id: str, filename: str, payload: bytes, *,
                     doc_id: str, rev: Optional[int], actor: str) -> dict:
    """Read one workbook into a bill revision. The single path both import routes go through.

    Two routes reach here — a browser upload, and "the copy already in this set" — and they must
    produce byte-for-byte the same revision. Factored rather than duplicated because the one thing
    that must never differ between them is what ends up in the database.
    """
    if not payload:
        raise HTTPException(status_code=422, detail="Empty upload.")
    if not (filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status_code=422,
            detail=f"{filename!r} is not an Excel workbook. The bill of quantities is issued and "
                   f"submitted as .xlsx (GCT Appendix A paragraphs 9-11).")

    conn = store.get_conn()
    try:
        target_rev = store.next_bill_rev(conn, set_id) if rev is None else int(rev)
        # The client's own file is kept, not just what we read out of it. Their workbook is the
        # document the tender is submitted in (GCT App A 10), so a future write-back has to have it.
        path = store.bill_dir(Workspace(), set_id) / f"rev-{target_rev}-{Path(filename).name}"
        path.write_bytes(payload)
        try:
            bill = boq_reader.read_workbook(path, set_id=set_id, rev=target_rev)
        except Exception as exc:                                  # noqa: BLE001 — reported, not swallowed
            raise HTTPException(status_code=422,
                                detail=f"Could not read {filename!r} as a bill of quantities: {exc}")
        store.save_bill_revision(conn, bill, doc_id=doc_id)
        store.touch_set(conn, set_id, actor)
        return {
            "set_id": set_id, "rev": target_rev, "items": len(bill.items),
            "bills": sorted({item.bill_no for item in bill.items}),
            "priceable": sum(1 for i in bill.items if not i.is_parent and not i.pre_priced),
            "pre_priced": sum(1 for i in bill.items if i.pre_priced),
            "notes": bill.notes,
            "item_notes": [{"full_ref": i.full_ref, "notes": i.notes} for i in bill.items if i.notes],
        }
    finally:
        conn.close()


@router.post("/boq/import")
async def import_bill(
    set_id: str = Form(...),
    doc_id: str = Form(default=""),
    rev: Optional[int] = Form(default=None),
    file: UploadFile = File(...),
    actor: str = Depends(_actor),
) -> dict:
    """Read the client's bill-of-quantities workbook into a new revision.

    Excel is not a convenience here — GCT Appendix A 9 requires the bill to be submitted "only ... in
    Editable File format, i.e. the Microsoft Excel format", using the client's own file, so the
    workbook is the document, not an export of one.
    """
    return _import_workbook(set_id, file.filename or "", await file.read(),
                            doc_id=doc_id, rev=rev, actor=actor)


# --- the bills that arrived with the upload ---------------------------------
#
# A folder ingest already finds these: `plan_folder` tries every workbook through the bill reader
# and lists the ones that parse. What it could not do was let anybody ACT on the list — the
# candidates were returned once, in the upload response, and the screen that reloads from
# `/ingest/manifest/{set_id}` never saw them. So the app said "pick one on the Price step" and then
# offered nowhere to pick, which is why a set with three perfectly good bills in it could not be
# priced at all.
#
# Found on demand rather than stored: no table, no migration, and a workbook dropped into the set
# later shows up without a re-ingest. Three files is a cheap read.
_WORKBOOK_SUFFIXES = (".xlsx", ".xlsm")

# How a package names its addenda. `TA #2/BQ/E-ND_2025_04-BQ-2.xlsx` is the second technical
# addendum's bill; the base bill has neither marking. Ranking on this is what lets the app PROPOSE
# an operative bill instead of leaving a three-way choice with no help in it.
_ADDENDUM_IN_PATH = re.compile(r"\bTA\s*#?\s*(\d+)", re.IGNORECASE)
_TRAILING_INDEX = re.compile(r"[-_](\d+)$")


def _addendum_rank(relative_path: str) -> tuple[int, str]:
    """How late in the sequence this workbook is, and the reason to show for it."""
    match = _ADDENDUM_IN_PATH.search(relative_path)
    if match:
        return int(match.group(1)), f"latest addendum: TA #{match.group(1)}"
    stem = Path(relative_path).stem
    match = _TRAILING_INDEX.search(stem)
    if match:
        return int(match.group(1)), f"highest revision marking on the filename: {stem}"
    return 0, "the only bill found, or the base bill with no addendum marking"


@router.get("/boq/{set_id}/candidates")
def get_bill_candidates(set_id: str) -> dict:
    """Every workbook in this set's upload that reads as a bill of quantities.

    "Reads as" by trying, never by the filename: the reference corpus holds `E-ND_2025_04-BQ-2.xlsx`
    and would equally hold a `Summary.xlsx` that is not a bill. The reader either finds priceable
    items or it does not — the same test `plan_folder` applies at ingest.

    One candidate is marked ``proposed`` with the sentence that explains it. Proposed, never
    automatic: which file is newest is very nearly clerical, and being wrong about it prices the
    wrong bill, so the app shows its reasoning and a person clicks.
    """
    docs = Workspace().docs_dir(set_id)
    conn = store.get_conn()
    try:
        revisions = store.list_bill_revisions(conn, set_id)
    finally:
        conn.close()
    # `source_file` is the name of the COPY kept beside the revision, which `_import_workbook`
    # writes as `rev-2-E-ND_2025_04-BQ-2.xlsx`. Comparing the raw names would never match, and the
    # screen would offer to import a bill that is already in.
    imported = {re.sub(r"^rev-\d+-", "", row.get("source_file") or "") for row in revisions}

    candidates: list[dict] = []
    if docs.is_dir():
        for path in sorted(p for p in docs.rglob("*") if p.suffix.lower() in _WORKBOOK_SUFFIXES):
            relative = path.relative_to(docs).as_posix()
            try:
                bill = boq_reader.read_workbook(path)
            except Exception:                     # noqa: BLE001 — not a bill is an answer, not a fault
                continue
            priceable = [i for i in bill.items if not i.is_parent and not i.pre_priced]
            if not priceable:
                continue
            rank, why = _addendum_rank(relative)
            candidates.append({
                "relative_path": relative, "name": path.name, "bytes": path.stat().st_size,
                "items": len(bill.items), "priceable": len(priceable),
                "notes": list(bill.notes[:4]),
                "already_imported": path.name in imported,
                "rank": rank, "why": why, "proposed": False,
            })

    if candidates:
        best = max(candidates, key=lambda c: (c["rank"], c["relative_path"]))
        best["proposed"] = True
    return {"set_id": set_id, "count": len(candidates), "candidates": candidates}


class ImportFromSetRequest(BaseModel):
    relative_path: str
    doc_id: str = ""
    rev: Optional[int] = None


@router.post("/boq/{set_id}/import-from-set")
def import_bill_from_set(set_id: str, req: ImportFromSetRequest,
                         actor: str = Depends(_actor)) -> dict:
    """Import a bill the app already holds, by its path inside this set's upload.

    Uploading a file the server already has on disk is work for no reason, and on a folder ingest it
    means going back to find the original in a 441-file tree. Same import, same revision, no
    round trip.
    """
    docs = Workspace().docs_dir(set_id)
    try:
        # Refuses `..`, an absolute path and a drive letter rather than trimming them — a traversal
        # attempt is not a typo. Written for the folder upload; the same rule applies to any path a
        # client hands us.
        relative = safe_relative_path(req.relative_path)
    except UnsafeUploadPath as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    path = docs / relative
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No file {req.relative_path!r} in this set's upload. The Price tab's "
                   f"import list shows every workbook that is here.")
    return _import_workbook(set_id, path.name, path.read_bytes(),
                            doc_id=req.doc_id, rev=req.rev, actor=actor)


@router.get("/boq/{set_id}")
def get_bill(set_id: str, rev: Optional[int] = None) -> dict:
    """The bill at ``rev``, or the operative one (highest revision) when rev is not given."""
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, set_id, rev)
        rates = store.load_bill_rates(conn, set_id, bill.rev)
        revisions = store.list_bill_revisions(conn, set_id)
    finally:
        conn.close()
    return {
        "set_id": set_id, "rev": bill.rev, "source_file": bill.source_file,
        "revisions": revisions,
        "items": [item.model_dump() for item in bill.items],
        "summary": [line.model_dump() for line in bill.summary],
        "notes": bill.notes,
        "rates": {ref: {k: v for k, v in row.items() if k != "build_up"} for ref, row in rates.items()},
    }


@router.get("/boq/{set_id}/diff/{from_rev}/{to_rev}")
def get_bill_diff(set_id: str, from_rev: int, to_rev: int) -> dict:
    """What changed between two revisions of the bill.

    The reason this endpoint exists at all: the workbook marks nothing. No fill, no bold, no comment,
    no tracked change — and the addendum's own summary of itself is disclaimed as "neither
    exhaustive nor guaranteed to be accurate".
    """
    conn = store.get_conn()
    try:
        before = _bill_or_404(conn, set_id, from_rev)
        after = _bill_or_404(conn, set_id, to_rev)
        priced = {ref: row["rate"] for ref, row in store.load_bill_rates(conn, set_id, from_rev).items()}
    finally:
        conn.close()
    diff = boq_diff.diff_bills(before, after)
    carried = boq_carry.carry_rates(diff, before, after, priced)
    return {
        "set_id": set_id, "from_rev": from_rev, "to_rev": to_rev,
        "counts": diff.counts(), "unchanged": diff.unchanged,
        "moved_only": diff.moved_only,
        "changes": [change.model_dump() for change in diff.changes],
        "worklist": [entry.model_dump() for entry in boq_carry.pending_review(carried)],
    }


@router.post("/boq/carry")
def carry_bill_rates(req: CarryRequest, actor: str = Depends(_actor)) -> dict:
    """Propose — or, with ``apply``, write — the rates for a new revision.

    A proposal until somebody says otherwise. Every entry names the rule that produced it, and every
    entry that needs a person to look holds the new revision's gate shut until they have.
    """
    conn = store.get_conn()
    try:
        before = _bill_or_404(conn, req.set_id, req.from_rev)
        after = _bill_or_404(conn, req.set_id, req.to_rev)
        priced = store.load_bill_rates(conn, req.set_id, req.from_rev)
        diff = boq_diff.diff_bills(before, after)
        carried = boq_carry.carry_rates(diff, before, after,
                                        {ref: row["rate"] for ref, row in priced.items()})
        if req.apply:
            for entry in carried:
                if entry.basis == models.CARRY_DELETED:
                    continue
                store.save_bill_rate(
                    conn, req.set_id, req.to_rev, entry.full_ref, rate=entry.rate,
                    build_up=priced.get(entry.full_ref, {}).get("build_up"),
                    basis=entry.basis,
                    # It stays the estimator's rate: App C 2.2(v) carries THEIR number forward, it
                    # does not invent one. What is not yet theirs is the decision that the number is
                    # still right at the new quantity, and `needs_review` is what says so.
                    badge=priced.get(entry.full_ref, {}).get("badge") or models.BADGE_USER,
                    needs_review=entry.needs_review, review_note=entry.reason, actor=actor,
                )
        pending = boq_carry.pending_review(carried)
    finally:
        conn.close()
    return {
        "set_id": req.set_id, "from_rev": req.from_rev, "to_rev": req.to_rev,
        "applied": req.apply,
        "carried": [entry.model_dump() for entry in carried],
        "needs_review": [entry.model_dump() for entry in pending],
    }


@router.post("/boq/rate")
def save_bill_rate(req: BillRateRequest, actor: str = Depends(_actor)) -> dict:
    """Save one item's rate and the build-up behind it. Editing always transfers ownership."""
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        item = bill.index().get(req.full_ref)
        if item is None:
            raise HTTPException(status_code=404,
                                detail=f"No item {req.full_ref!r} in revision {bill.rev} of the bill.")
        if item.pre_priced:
            raise HTTPException(
                status_code=409,
                detail=(f"Item {req.full_ref} is pre-priced by the client at "
                        f"{item.client_rate}. GCT App C 2.2(vi) reinstates the client's figure at "
                        f"examination, so a rate entered here would be discarded."))
        amount = None
        if req.rate is not None:
            amount = req.rate if item.lump else round(req.rate * (item.qty or 0), 2)
        store.save_bill_rate(
            conn, req.set_id, bill.rev, req.full_ref, rate=req.rate, amount=amount,
            build_up=req.build_up, basis=req.basis or "built", badge=models.BADGE_USER,
            needs_review=req.needs_review, review_note=req.review_note, actor=actor,
        )
        store.touch_set(conn, req.set_id, actor)
        pending = store.bill_review_pending(conn, req.set_id, bill.rev)
    finally:
        conn.close()
    return {"set_id": req.set_id, "rev": bill.rev, "full_ref": req.full_ref,
            "rate": req.rate, "amount": amount, "badge": models.BADGE_USER,
            "outstanding_review": len(pending)}


@router.post("/boq/assumption")
def save_bill_assumption(req: AssumptionRequest, actor: str = Depends(_actor)) -> dict:
    """Save how one item's given quantity is assumed to split, and price it from that.

    The mix has to reconcile to the client's quantity. It is not scaled to fit: the total is fixed
    by the bill and may not be altered (GCT 6), so a mix that disagrees is an error in the mix, and
    a rate built from a silently corrected mix is indistinguishable from one that is right.
    """
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        item = bill.index().get(req.assumption.full_ref)
        if item is None:
            raise HTTPException(
                status_code=404,
                detail=f"No item {req.assumption.full_ref!r} in revision {bill.rev} of the bill.")
        try:
            build_up = boq_production.expand(req.assumption, item)
        except boq_production.AssumptionMismatch as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        assumption = req.assumption.model_copy(update={"badge": models.BADGE_USER})
        store.save_item_assumption(conn, req.set_id, bill.rev, assumption, actor=actor)
        store.save_bill_rate(
            conn, req.set_id, bill.rev, item.full_ref, build_up=build_up, basis="built",
            badge=models.BADGE_USER, actor=actor,
        )
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    return {
        "set_id": req.set_id, "rev": bill.rev, "full_ref": item.full_ref,
        "shifts": [{"condition": label, "shifts": shifts}
                   for label, shifts in boq_production.shifts_for(assumption)],
        "weighted_output": boq_production.weighted_output(assumption),
        "unpriced_conditions": boq_production.unpriced_conditions(assumption),
        "build_up": build_up.model_dump(),
    }


def _rate_inputs(stored: dict) -> tuple[dict, dict]:
    """Split the stored bill rates into the two things ``price_bill`` takes.

    A row with a build-up is priced from it; a row with only a rate was priced in an earlier
    revision and carried. The two are different facts and the split is the same everywhere it is
    made, so it is made once.
    """
    build_ups = {ref: row["build_up"] for ref, row in stored.items() if row["build_up"] is not None}
    carried = {ref: row["rate"] for ref, row in stored.items()
               if row["rate"] is not None and row["build_up"] is None}
    return build_ups, carried


@router.get("/boq/{set_id}/priced")
def get_priced_bill(set_id: str, rev: Optional[int] = None, margin_pct: float = 0.0) -> dict:
    """The bill, priced from the stored build-ups and rates."""
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, set_id, rev)
        stored = store.load_bill_rates(conn, set_id, bill.rev)
        rate_rows = rates_store.load(conn)
        # THE POOL REACHES THE RATES. `price_bill` has taken a `spread=` argument since it was
        # written and was never given one, because nothing converted a routed-SPREAD `UnbilledCost`
        # into the `SpreadLine` it wants. So every item's share was 0.0 and `tendered_total` omitted
        # the pool — for costs the contract explicitly orders INTO the rates ("There shall be no
        # measurement or separate payment"). A cost with no bill item is not saved by having
        # nowhere to go.
        sweep = store.load_sweep(conn, set_id, bill.rev)
    finally:
        conn.close()
    build_ups, carried = _rate_inputs(stored)
    priced = boq_pricing.price_bill(bill, build_ups, rates=rate_rows, margin_pct=margin_pct,
                                    carried=carried, spread=sweep.spread_lines(),
                                    loadings=sweep.loadings())
    return {"set_id": set_id, "rev": bill.rev, **priced.model_dump()}


@router.get("/boq/{set_id}/checks")
def get_bill_checks(set_id: str, rev: Optional[int] = None, margin_pct: float = 0.0,
                    fee_pct: Optional[float] = None) -> dict:
    """Run the deterministic guards over the priced bill. Each names the clause it enforces."""
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, set_id, rev)
        stored = store.load_bill_rates(conn, set_id, bill.rev)
        rate_rows = rates_store.load(conn)
        pending = store.bill_review_pending(conn, set_id, bill.rev)
        sweep = store.load_sweep(conn, set_id, bill.rev)
        checks_groups = store.load_hole_groups(conn, set_id, bill.rev)
        station_classes = store.load_station_classes(conn, set_id)
        _criteria, class_refs = store.load_site_criteria(conn, set_id)
        costing_model = boq_model.effective(store.load_library_model(conn),
                                            store.load_set_model(conn, set_id))
        costing_state = store.load_costing_state(conn, set_id, bill.rev)
    finally:
        conn.close()
    build_ups, carried = _rate_inputs(stored)
    priced = boq_pricing.price_bill(bill, build_ups, rates=rate_rows, margin_pct=margin_pct,
                                    carried=carried, spread=sweep.spread_lines(),
                                    loadings=sweep.loadings())
    issued = {line.code: line.amount for line in bill.summary
              if line.client_inserted and line.code in {"B", "D", "E"} and line.amount is not None}
    flags = boq_checks.run_checks(priced, bill, issued_sums=issued, fee_pct=fee_pct)
    # `loading_unapplied` is computed INSIDE `price_bill` — it needs the loadings map, which
    # `run_checks` never sees, so it cannot re-derive the flag the way it re-derives
    # `unpriced_item`. Merging just that kind keeps the two surfaces symmetric without
    # double-counting the kinds both already emit.
    flags += [f for f in priced.flags if f.kind == "loading_unapplied"]
    # The platform money typed on the Site groups, NET of what the active wiring actually
    # carries — so the guard goes quiet by construction, not by decree, when the money truly
    # lands in a rate. Two honest routes exist and both are netted:
    #   * the per-class rig-move basis (engine 2): active the moment any item is pointed at a
    #     derived class variant, at which point the Class-B platform total is inside the Class B
    #     move rate (SMM S02 ¶2.08(h)) — platforms typed on non-B groups stay flagged, because
    #     a Class A move must not carry a platform it does not need;
    #   * a sweep cost routed LOAD onto a rig-move item (engine 1's manual route, the interim
    #     path the guard's own message points at).
    class_keys = {v.key for b in costing_model.basis_rows for v in boq_model.class_variants(b)}
    overrides = costing_state["mapping"].get("items") or {}
    split_active = any((o.get("basis_key") or "") in class_keys for o in overrides.values())
    platform_total = boq_groups.access_build_total(boq_groups.GroupPlan(groups=checks_groups))
    consumed = _class_b_platform_total(checks_groups, station_classes) if split_active else 0.0
    consumed += sum(v for k, v in sweep.loadings().items() if k in set(class_refs.values()))
    flags += boq_checks.platform_cost_unconsumed(max(0.0, round(platform_total - consumed, 2)))
    return {
        "set_id": set_id, "rev": bill.rev,
        "tendered_total": priced.tendered_total,
        "counts": {kind: sum(1 for f in flags if f.kind == kind)
                   for kind in sorted({f.kind for f in flags})},
        "flags": [flag.model_dump() for flag in flags],
        "outstanding_review": pending,
    }


@router.post("/boq/{set_id}/revision/{rev}/sign-off")
def sign_off_bill_revision(set_id: str, rev: int, actor: str = Depends(_actor)) -> dict:
    """Declare a bill revision priced. Refused while any carried rate is still unlooked-at."""
    conn = store.get_conn()
    try:
        _bill_or_404(conn, set_id, rev)
        _reprice_gate_or_409(conn, set_id, rev)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {"set_id": set_id, "rev": rev, "signed_off": True, "by": actor}


# ---------------------------------------------------------------------------
# The take-off (Site) — the drawing's half of the estimate
#
# Everything the bill of quantities does not say: where the 91 holes are, what the general-notes
# drawing rules about them, which of them a rig can reach, and which of them drill alike.
#
# There is NO GATE on this step. An unassigned hole cannot stop you pricing — but the Price step
# carries the count live, and the sweep will not settle while one is open. The block is where the
# money is decided, not where the reading is.
# ---------------------------------------------------------------------------
class StationScheduleRequest(BaseModel):
    """The schedule read off the drawing. ``confirm`` is a person saying they have checked it."""
    set_id: str
    schedule: boq_schedule.StationSchedule
    source_sheet: str = ""
    confirm: bool = False


class StationPasteRequest(BaseModel):
    """A table of stations as it came off a spreadsheet or a PDF, for reading — not for saving."""
    set_id: str
    text: str
    source_sheet: str = ""


class StationClassRequest(BaseModel):
    set_id: str
    station: str
    access_class: str = ""          # A | B | C, or "" to un-decide it
    group_id: Optional[str] = None  # None leaves the existing grouping alone


class HoleGroupRequest(BaseModel):
    set_id: str
    rev: Optional[int] = None
    group_id: str
    group: boq_groups.HoleGroup


class GroupPreviewRequest(BaseModel):
    """One group's inputs, for the live arithmetic under the Groups screen."""
    set_id: str
    group: boq_groups.HoleGroup


def _schedule_or_404(conn, set_id: str) -> boq_schedule.StationSchedule:
    schedule, _meta = store.load_station_schedule(conn, set_id)
    if schedule is None:
        raise HTTPException(
            status_code=404,
            detail=f"No station schedule for set {set_id!r}. Read it off the borehole details "
                   f"drawing (GI/210 on the reference contract) and save it first.")
    return schedule


def _billed_class_counts(bill: models.ClientBill, class_refs: dict) -> dict:
    """How many rig moves of each class the client actually billed.

    Read from the bill rather than typed, because it is the only external check on a judgement the
    estimator otherwise makes alone — and a number he typed himself cannot check him.
    """
    index = bill.index()
    counts = {}
    for name, ref in class_refs.items():
        item = index.get(ref)
        if item is not None and item.qty:
            counts[name] = int(item.qty)
    return counts


@router.get("/site/{set_id}/schedule")
def get_station_schedule(set_id: str) -> dict:
    """The stations, and whether every row adds up.

    ``bad_rows`` is the first thing the screen shows: a hole whose length does not equal its soil
    plus its rock has been misread, and no quantity derived from it means anything. They are named,
    never silently dropped and never repaired.

    Three siblings say the things arithmetic cannot: ``unread_rows`` (a cell nobody could make out —
    a blank is not a zero), ``empty_rows`` (a hole that drills no metres, invisible to every total)
    and ``duplicate_names`` (a repeated station name, which the schedule's own index would swallow).
    """
    conn = store.get_conn()
    try:
        schedule, meta = store.load_station_schedule(conn, set_id)
        classes = store.load_station_classes(conn, set_id)
    finally:
        conn.close()
    if schedule is None:
        return {"set_id": set_id, "stations": [], "trial_pits": [], "classes": {},
                "bad_rows": [], "unread_rows": [], "empty_rows": [], "duplicate_names": [],
                "problems": [], "usable": False, "totals": {}, "meta": meta,
                "waiting_on": "the borehole details schedule has not been read yet"}
    return {
        "set_id": set_id,
        "meta": meta,
        "stations": [s.model_dump() for s in schedule.stations],
        "trial_pits": [p.model_dump() for p in schedule.trial_pits],
        "classes": classes,
        "bad_rows": schedule.bad_rows(),
        "unread_rows": schedule.unread_rows(),
        "empty_rows": schedule.empty_rows(),
        "duplicate_names": schedule.duplicate_names(),
        "problems": schedule.problems(),
        "usable": schedule.usable(),
        "totals": {
            "holes": schedule.hole_count(), "soil_m": schedule.soil_m(),
            "rock_m": schedule.rock_m(), "hard_m": schedule.hard_m(),
            "standpipes": schedule.standpipes(), "piezometers": schedule.piezometers(),
            "instruments": schedule.instruments(), "deepest": schedule.deepest(),
            "trial_pits": len(schedule.trial_pits),
        },
    }


@router.get("/site/{set_id}/positions")
def get_station_positions(set_id: str) -> dict:
    """Every located station in WGS84, with a keyless per-point map link — the Site map's data.

    Deterministic (EPSG:2326 → 4326 in `boq/hk1980.py`, ~1 m — the accuracy of the published
    transformation). A coordinate that converts to somewhere outside Hong Kong is REFUSED into the
    list and named in ``problems``: a wrong point plotted confidently on satellite imagery is
    exactly the picture somebody trusts. ``providers`` is the config seam — the Lands Department
    basemap is keyless and always on; everything Google lights up only when a key is configured,
    and its absence never blocks the map.
    """
    conn = store.get_conn()
    try:
        schedule, _meta = store.load_station_schedule(conn, set_id)
    finally:
        conn.close()
    if schedule is None:
        return {"set_id": set_id, "positions": [], "problems": [],
                "providers": boq_hk1980.provider_config(),
                "waiting_on": "the borehole details schedule has not been read yet"}
    placed, problems = boq_hk1980.positions(schedule)
    return {
        "set_id": set_id,
        "positions": [p.model_dump() for p in placed],
        "problems": problems,
        "providers": boq_hk1980.provider_config(),
    }


@router.get("/site/{set_id}/access")
def get_access_board(set_id: str, radius_m: float = 250.0) -> dict:
    """The access board: proximity clusters over the map, and the evidence for reaching each.

    Assembles; never concludes. ``proposed_class`` is on every cluster and is permanently empty —
    the access class is worth real money (80 Class A rig moves against 11 Class B, and a platform
    lands on the rig-move item), no document in the tender says which hole is which, and a machine
    reading a photograph would be guessing at something a person is accountable for.
    """
    conn = store.get_conn()
    try:
        schedule, _meta = store.load_station_schedule(conn, set_id)
        classes = store.load_station_classes(conn, set_id) if schedule else {}
        registrations = store.load_sheet_registrations(conn, set_id) if schedule else []
        board_road_points = store.load_road_points(conn, set_id) if schedule else []
    finally:
        conn.close()
    if schedule is None:
        return {"set_id": set_id, "clusters": [], "radius_m": radius_m, "unlocated": [],
                "problems": [], "providers": boq_hk1980.provider_config(),
                "waiting_on": "the borehole details schedule has not been read yet"}
    # Which stations land on a registered, usable site-plan sheet — by COORDINATES, because
    # Station.sheet is the SCHEDULE sheet (GI/210) and registrations are of the site-plan
    # sheets (GI/201…): the two name families never intersect.
    located_stations = {
        s.station for s in schedule.stations
        if s.easting is not None and s.northing is not None
        and boq_georef.sheet_for(s.easting, s.northing, registrations) is not None}
    board = boq_access.board(
        schedule, set_id=set_id, radius_m=radius_m,
        classes={name: (row.get("access_class") or "") for name, row in classes.items()},
        located_stations=located_stations, road_points=board_road_points)
    return {"set_id": set_id, **board.model_dump()}


@router.get("/site/{set_id}/access/still")
def get_access_still(set_id: str, lat: float, lon: float, kind: str = "satellite") -> Response:
    """A keyed still (satellite or Street View), fetched SERVER-SIDE.

    The key never reaches the browser. A URL with a credential in it, handed to a page, is a
    published credential whatever the referrer policy says — so the client asks this path and the
    key stays here. With no key configured this is a 503 naming the missing thing, which the card
    renders as its unavailable reason rather than as a broken image.
    """
    key = (os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail=("No GOOGLE_MAPS_API_KEY is configured, so this kind of evidence is dark. The "
                    "map, the Lands Department imagery and the drawing crop need no key and are "
                    "unaffected."))
    if kind not in {"satellite", "street_view"}:
        raise HTTPException(status_code=400, detail=f"unknown still kind {kind!r}")
    if not boq_hk1980.in_hong_kong(lat, lon):
        raise HTTPException(
            status_code=400,
            detail=f"({lat:.5f}, {lon:.5f}) is outside Hong Kong — refusing to fetch a picture of "
                   f"somewhere the works are not.")

    url = ("https://maps.googleapis.com/maps/api/streetview" if kind == "street_view"
           else "https://maps.googleapis.com/maps/api/staticmap")
    params = ({"size": "600x400", "location": f"{lat},{lon}", "key": key}
              if kind == "street_view" else
              {"center": f"{lat},{lon}", "zoom": "18", "size": "600x400",
               "maptype": "satellite", "scale": "2", "key": key})
    try:
        import httpx

        reply = httpx.get(url, params=params, timeout=20.0)
    except Exception as exc:                                    # network, DNS, timeout
        raise HTTPException(status_code=502,
                            detail=f"could not reach the imagery provider: {exc}") from exc
    if reply.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"the imagery provider answered {reply.status_code}")
    return Response(content=reply.content,
                    media_type=reply.headers.get("content-type", "image/png"))


@router.post("/site/schedule")
def post_station_schedule(req: StationScheduleRequest, actor: str = Depends(_actor)) -> dict:
    """Save the schedule, and optionally confirm it.

    Confirming is not sticky. A re-read lands unconfirmed again, because the thing somebody checked
    is no longer the thing on the screen — the same rule the register applies when an addendum
    rewrites a clause somebody had already ruled on.
    """
    conn = store.get_conn()
    try:
        store.save_station_schedule(conn, req.set_id, req.schedule,
                                    source_sheet=req.source_sheet, confirmed=req.confirm,
                                    actor=actor)
        _schedule, meta = store.load_station_schedule(conn, req.set_id)
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "meta": meta,
            "bad_rows": req.schedule.bad_rows(),
            "unread_rows": req.schedule.unread_rows(),
            "empty_rows": req.schedule.empty_rows(),
            "duplicate_names": req.schedule.duplicate_names(),
            "problems": req.schedule.problems(),
            "usable": req.schedule.usable()}


@router.post("/site/schedule/parse")
def post_parse_station_schedule(req: StationPasteRequest) -> dict:
    """Read a pasted table of stations. Returns a proposal; **saves nothing.**

    The take-off had no way in. `POST /site/schedule` has always accepted a schedule and nothing in
    this application ever produced one — no frontend call, no backend constructor, zero rows in the
    demo database — so the screen's instruction to "read it off the drawing and save it first" was
    one the app gave no means of following. Behind that dead end sat the bill-vs-drawing check, the
    access map, and the only place a hole is ever given its class.

    This is the door. Ninety-one rows and twelve columns is a thousand form fields, and whatever the
    estimator is reading from is already tabular, so the paste is the honest shape.

    Separate from the save on purpose: what comes back is what was *understood*, including every
    cell that could not be read, and a person decides whether that is the schedule. Deterministic —
    no model is involved at any point.
    """
    report = boq_schedule_paste.parse(req.text, set_id=req.set_id, source_sheet=req.source_sheet)
    schedule = report.schedule
    return {
        "set_id": req.set_id,
        "schedule": schedule.model_dump(),
        "headline": report.headline(),
        "header_found": report.header_found,
        "delimiter": report.delimiter,
        "mapping": report.mapping,
        "unmapped_columns": report.unmapped_columns,
        "missing_columns": report.missing_columns,
        "skipped_lines": report.skipped_lines,
        "cells_unread": report.cells_unread(),
        "bad_rows": schedule.bad_rows(),
        "unread_rows": schedule.unread_rows(),
        "empty_rows": schedule.empty_rows(),
        "duplicate_names": schedule.duplicate_names(),
        "problems": schedule.problems(),
        "usable": schedule.usable(),
        "totals": {
            "holes": schedule.hole_count(), "soil_m": schedule.soil_m(),
            "rock_m": schedule.rock_m(), "hard_m": schedule.hard_m(),
            "standpipes": schedule.standpipes(), "piezometers": schedule.piezometers(),
            "instruments": schedule.instruments(), "deepest": schedule.deepest(),
            "trial_pits": len(schedule.trial_pits),
        },
    }


def _set_drawing_files(set_id: str) -> list[tuple[str, bytes]]:
    """The tender's own drawings, as ``(filename, bytes)`` — the same shape an upload arrives in.

    THE READER COULD NOT SEE DRAWINGS THE APP ALREADY HELD. An archive ingest classifies `DRG/`
    into parts with ``category == "drawings"`` (35 sheets on the reference pack), each with its cut
    PDF on disk — and `/site/schedule/read` took only `UploadFile`s, so the Site importer asked the
    operator to go find those same PDFs in a Downloads folder and upload them again. The bill
    already had the fix (`/boq/import-from-set`); this is the drawing set's copy of it.

    The name handed to the triage is the part's ``source_doc`` — the original filename, which is
    what the register's sheet numbers match against. A binder-cut drawing part (one part, many
    pages, one shared source name) will not match per-sheet numbers, and the triage then says so
    honestly rather than guessing; uploading the loose sheets remains the way in for that shape.
    Parts whose PDF is not on disk yet are skipped, never invented.
    """
    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    out: list[tuple[str, bytes]] = []
    for spec, path, _context in rows:
        if spec.category != "drawings" or not path:
            continue
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue                     # a part whose file left the disk is a gap, not a crash
        out.append(((spec.source_doc or spec.title or spec.part_id), data))
    return out


@router.get("/site/{set_id}/drawings")
def get_site_drawings(set_id: str) -> dict:
    """What this tender already holds that the drawing reader could open. A pure read.

    Exists so the Site importer can offer "read from this tender's own drawings" only when there
    are any — and say how many — instead of asking for an upload the server does not need.
    """
    conn = store.get_conn()
    try:
        rows = store.load_parts(conn, set_id)
    finally:
        conn.close()
    names = [(spec.source_doc or spec.title or spec.part_id)
             for spec, path, _context in rows
             if spec.category == "drawings" and path]
    return {
        "set_id": set_id, "count": len(names), "names": names,
        "waiting_on": ("" if names else
                       "no ingested part is classified as a drawing — upload the schedule "
                       "sheets and the register instead"),
    }


@router.post("/site/schedule/read")
def post_read_station_schedule(
    files: list[UploadFile] = File(default=[]),
    set_id: str = Form(...),
    bands: int = Form(0),
) -> dict:
    """Read the take-off off the borehole details drawing(s). Returns a proposal; **saves nothing.**

    WITH NO FILES ATTACHED it reads the tender's OWN drawings — the parts an archive ingest already
    classified as `drawings` and materialised on disk — so the ordinary case costs the operator one
    click, not a trip to a Downloads folder for 35 PDFs the server already holds. An upload still
    works exactly as before, and is the way in for a drawing that arrived outside the archive.
    The register triage runs identically over both sources, so this costs no extra model call.

    Hand it the drawing folder — or just the schedule sheets and the register — and it works out
    which sheets carry a station table before opening any of them. That triage is free: the issuer
    ships a drawing register (`GI-COVER`) and it is the one document in the whole drawing set with
    a real text layer (2,582 characters against 28 on every sheet), so the titles are simply read
    and the ones ending "- COORDINATE" kept, minus the WORKING AREA sheets, which are the site
    boundary rather than the holes.

    THERE ARE TWO SCHEDULE SHEETS on the reference pack — `GI/210` for the engineering boreholes
    and `GI/310` for the environmental ones, which are billed under Bills 3 and 5. Both are read
    and merged. A reader that finds the first and stops has under-read the tender, and every check
    downstream would agree with it, because they all measure what was read against what was read.

    The reading itself is a vision call per sheet: the sheets are flattened raster (48 images, 28
    characters), and at the API's own downscale ceiling the table is legible cell by cell, so one
    call reads one sheet. What comes back is a PROPOSAL — unconfirmed, with every cell the reader
    could not make out marked unread rather than filled with a zero, and the two arithmetic checks
    it cannot influence still in front of it: each row against its own stated length, and the
    totals against Bill No.2's own quantities.
    """
    uploads = [(f.filename or "drawing.pdf", f.file.read()) for f in files]
    source = "upload" if uploads else "set"
    if not uploads:
        uploads = _set_drawing_files(set_id)
    if not uploads:
        raise HTTPException(
            status_code=404,
            detail=("No drawings were uploaded and this tender holds no ingested part classified "
                    "as a drawing. Upload the schedule sheets (and the drawing register, if there "
                    "is one) instead."))

    # The register, if one came with the drawings. Its text layer is the whole triage.
    #
    # `page_text(data, 1, 2)`, and the old argument was a live bug: this read `page_text(data, 1,
    # 0)`, and that function's page range is `range(start-1, min(end, pages))` — with `end=0` an
    # EMPTY range, so the register text was always "" and the register tier never fired. Every
    # read, upload path included, silently ran on the weaker filename tier — which cannot tell a
    # WORKING AREA coordinate sheet from a station schedule, because that difference lives only in
    # the register's titles. (`has_text_layer` treats `end=0` as "all pages"; `page_text` does
    # not. The mismatch is the trap.) Found by the first test that drove triage through this
    # endpoint rather than calling `sheets.plan()` directly.
    register_text = ""
    register_name = ""
    for name, data in uploads:
        if not boq_pdfops.has_text_layer(data):
            continue
        text = boq_pdfops.page_text(data, 1, 2)
        if len(text.strip()) >= 500 and text.upper().count("GI") >= 3:
            register_text, register_name = text, name
            break

    plan = boq_sheets.plan(register_text, [name for name, _ in uploads])
    by_name = dict(uploads)
    reports: list = []

    # PROGRESS, on a request that blocks for a QUARTER OF AN HOUR. A vision read of these sheets
    # took ~17 minutes on the first live run, and this endpoint returned only at the end — so the
    # operator watched a spinner with no way to tell reading from hung. The response shape is
    # deliberately unchanged (every caller and test still reads the same dict); instead the run
    # registers an ordinary job and stamps its stage per sheet, and the browser polls the job
    # endpoints it already has while the POST is still in flight.
    job_id = jobs.JOBS.create("drawing", set_id=set_id)
    jobs.JOBS.mark_running(job_id, f"triaged {len(plan.sheets)} sheet(s)")
    try:
        for n, entry in enumerate(plan.sheets, start=1):
            jobs.JOBS.update(job_id, stage=f"reading {entry.number} ({n} of {len(plan.sheets)})",
                             done=n - 1, total=len(plan.sheets))
            data = by_name.get(entry.filename)
            if data is None:
                reports.append(boq_schedule_read.ReadReport(
                    sheet=entry.number,
                    problem=("the register lists this sheet but its file was not among the "
                             "drawings uploaded")))
                continue
            # `bands` per request, so one sheet can be tried whole and then in slices against two
            # providers without a restart or an edit. 0 keeps the adaptive default; the module
            # reads `SCHEDULE_READ_BANDS` when nothing is passed here.
            reports.append(boq_schedule_read.read_sheet(
                data, set_id=set_id, sheet=f"{entry.number}", bands=bands or None))

        schedule = boq_schedule_read.merge(reports, set_id=set_id)
    except Exception as exc:
        # The job carries the failure too, or a watcher polling it would see a run that simply
        # stopped reporting — which reads as hung rather than failed.
        jobs.JOBS.update(job_id, status="error", error=str(exc))
        raise
    jobs.JOBS.update(job_id, status="done", stage="merged",
                     done=len(plan.sheets), total=len(plan.sheets))
    return {
        "set_id": set_id,
        # WHERE THE SHEETS CAME FROM: "set" is the tender's own ingested drawings, "upload" is
        # files attached to this request. Stated because the two can genuinely differ — an
        # operator comparing a re-issued sheet against the ingested one needs to know which run
        # was which.
        "source": source,
        "schedule": schedule.model_dump(),
        "headline": _read_headline(plan, reports, schedule),
        "triage": {
            "tier": plan.tier, "reason": plan.reason, "headline": plan.headline(),
            "register": register_name,
            "sheets": [{"number": e.number, "title": e.title, "kind": e.kind(),
                        "filename": e.filename} for e in plan.sheets],
            "excluded": plan.excluded,
            "total_drawings": plan.total_drawings,
        },
        "sheets_read": [{"sheet": r.sheet, "read": r.read, "problem": r.problem,
                         "cells_unread": r.cells_unread, "headline": r.headline(),
                         # How the sheet was read, and what is missing from it. `bands > 1` means
                         # one call could not hold the answer; `bands_failed` non-empty means the
                         # sheet is only PARTLY read and no total on it is the sheet's total.
                         "bands": r.bands, "bands_failed": r.bands_failed,
                         # THE READER RETURNED ROWS AND PUT NO NUMBERS IN THEM. Distinct from
                         # `problem` (nothing came back) and from `cells_unread` (a count nobody
                         # reads as a verdict): this arrives with `read: true` and a plausible row
                         # count, which is the most reassuring thing on the response.
                         "gave_up": r.gave_up,
                         # WHAT THIS SHEET COST AND HOW LONG IT TOOK. Provider comparison has been
                         # done twice by hand from row counts; the reader carries its own evidence
                         # now, so the next comparison is one run rather than an afternoon. Empty
                         # in DEMO, which is the honest answer there.
                         "calls": r.calls,
                         "seconds": round(sum(c.get("ms") or 0 for c in r.calls) / 1000.0, 1),
                         "tokens_in": sum(c.get("in") or 0 for c in r.calls),
                         "tokens_out": sum(c.get("out") or 0 for c in r.calls),
                         "model": next((c.get("model") for c in r.calls if c.get("model")), ""),
                         "partial": r.partial()}
                        for r in reports],
        "partial_sheets": [r.sheet for r in reports if r.partial()],
        "surrendered_sheets": [r.sheet for r in reports if r.gave_up],
        # How the sheet was sliced, echoed back — a provider comparison is worthless if you cannot
        # tell which run was whole-sheet and which was quartered.
        "bands_requested": bands,
        "cells_unread": sum(r.cells_unread for r in reports),
        "bad_rows": schedule.bad_rows(),
        "unread_rows": schedule.unread_rows(),
        "empty_rows": schedule.empty_rows(),
        "duplicate_names": schedule.duplicate_names(),
        "problems": schedule.problems(),
        "usable": schedule.usable(),
        "totals": {
            "holes": schedule.hole_count(), "soil_m": schedule.soil_m(),
            "rock_m": schedule.rock_m(), "hard_m": schedule.hard_m(),
            "standpipes": schedule.standpipes(), "piezometers": schedule.piezometers(),
            "instruments": schedule.instruments(), "deepest": schedule.deepest(),
            "trial_pits": len(schedule.trial_pits),
        },
    }


def _read_headline(plan, reports: list, schedule) -> str:
    """One sentence for the top of the panel. Never reassuring about a sheet nobody read."""
    if not plan.found():
        return plan.headline()
    partial = [r for r in reports if r.partial()]
    unread_sheets = [r.sheet for r in reports if not r.read]
    if unread_sheets and len(unread_sheets) == len(reports):
        return (f"None of the {len(reports)} schedule sheet(s) could be read. "
                + " ".join(f"{r.sheet}: {r.problem}." for r in reports))
    head = (f"Read {len(schedule.stations)} borehole(s)"
            + (f" and {len(schedule.trial_pits)} trial pit(s)" if schedule.trial_pits else "")
            + f" from {len([r for r in reports if r.read])} of {len(reports)} sheet(s).")
    if unread_sheets:
        head += (f" {', '.join(unread_sheets)} could NOT be read, so every hole on "
                 f"{'them' if len(unread_sheets) > 1 else 'it'} is missing from this take-off.")
    for report in partial:
        head += (f" {report.sheet} is only PARTLY read: {'; '.join(report.bands_failed)} — rows "
                 f"from there are missing, so no total below is that sheet's total.")
    problems = schedule.problems()
    if problems:
        head += f" {len(problems)} row(s) are not settled — every one is named below."
    return head + " Nothing is saved until you say so, and nothing here is confirmed."


@router.get("/site/{set_id}/derived")
def get_derived_quantities(set_id: str, rev: Optional[int] = None) -> dict:
    """What the drawing says the quantities should be, checked against what the client billed.

    A divergence is worth more than a match. On the reference contract GI/100's Table 1 says 52
    permeability tests and the bill says 54 — nobody reading either document alone would notice,
    and the tenderer who prices 52 has under-priced two.
    """
    conn = store.get_conn()
    try:
        schedule = _schedule_or_404(conn, set_id)
        criteria, _class_refs = store.load_site_criteria(conn, set_id)
        bill = store.load_bill(conn, set_id, rev)
    finally:
        conn.close()
    report = boq_derive.derive(schedule, criteria, bill=bill)
    return {
        "set_id": set_id, "rev": bill.rev if bill else None,
        "checked_against_a_bill": bill is not None,
        "derived": [d.model_dump() for d in report.derived],
        "divergences": [d.model_dump() for d in report.divergences()],
        "confirmations": [d.full_ref for d in report.confirmations()],
        "unchecked": [d.label for d in report.unchecked()],
    }


@router.post("/site/class")
def post_station_class(req: StationClassRequest, actor: str = Depends(_actor)) -> dict:
    """Class one hole. The judgement no document in the set contains.

    Class C is the interesting one: PS 7.01B calls it access "only by helicopter" and the bill has
    no item for it, so a hole classed C has nowhere to be priced. That is not a reason to price it
    at nothing — the response says so, and the sweep is where it goes.
    """
    from client_boq.boq.groups import CLASS_C, CLASS_MEANING, CLASSES
    if req.access_class and req.access_class not in CLASSES:
        raise HTTPException(
            status_code=422,
            detail=f"{req.access_class!r} is not a class of site. PS 7.01B has "
                   f"{', '.join(CLASSES)}.")
    conn = store.get_conn()
    try:
        store.save_station_class(conn, req.set_id, req.station, access_class=req.access_class,
                                 group_id=req.group_id, actor=actor)
        classes = store.load_station_classes(conn, req.set_id)
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    counts: dict[str, int] = {}
    for row in classes.values():
        if row["access_class"]:
            counts[row["access_class"]] = counts.get(row["access_class"], 0) + 1
    return {
        "set_id": req.set_id, "station": req.station,
        "access_class": req.access_class, "decided_by": actor,
        "counts": counts,
        "note": (f"{CLASS_MEANING[CLASS_C]} — this hole has no bill item to be priced against, so "
                 f"it goes to the sweep rather than being priced at nothing."
                 if req.access_class == CLASS_C else ""),
    }


@router.get("/site/{set_id}/groups")
def get_hole_groups(set_id: str, rev: Optional[int] = None) -> dict:
    """The groups, what each still needs, and whether the classification agrees with the bill.

    ``reconcile`` is the whole point of the screen. The client bills 80 Class A and 11 Class B rig
    moves and never says which holes; the estimator's counts coming back to 80 and 11 is the only
    external check there is on a decision he otherwise makes alone.
    """
    conn = store.get_conn()
    try:
        schedule, _meta = store.load_station_schedule(conn, set_id)
        bill = store.load_bill(conn, set_id, rev)
        resolved_rev = bill.rev if bill else 0
        groups = store.load_hole_groups(conn, set_id, resolved_rev)
        classes = store.load_station_classes(conn, set_id)
        _criteria, class_refs = store.load_site_criteria(conn, set_id)
        book = store.load_output_book(conn)
    finally:
        conn.close()

    # A group's class follows its stations': the estimator classes holes on the Holes screen, and a
    # group is just a set of holes that drill alike. Inferring it here keeps that one act, not two.
    filled = []
    sources = {}
    for group in groups:
        if schedule is not None:
            group = boq_groups.summarise(group, schedule)
        assigned = {classes.get(name, {}).get("access_class", "") for name in group.stations}
        assigned.discard("")
        if len(assigned) == 1 and not group.access_class:
            group = group.model_copy(update={"access_class": assigned.pop()})
        group, source = boq_outputs.apply_to_group(group, book)
        filled.append(group)
        sources[group.label] = {k: v.model_dump() for k, v in source.items()}

    plan = boq_groups.GroupPlan(
        groups=filled,
        billed_class_counts=_billed_class_counts(bill, class_refs) if bill else {},
        # THE POPULATION, not just the part of it somebody has already grouped. Without this
        # `unassigned()` counts holes inside groups only, so 91 stations and no groups reported
        # 0 unassigned — every hole classed, on a tender where none of them was.
        total_holes=len(schedule.stations) if schedule is not None else None)
    return {
        "set_id": set_id, "rev": resolved_rev,
        "groups": [g.model_dump() for g in filled],
        "sources": sources,
        "counts": plan.counts(),
        "unassigned": plan.unassigned(),
        "billed_class_counts": plan.billed_class_counts,
        "reconcile": plan.reconcile(),
        "not_ready": plan.not_ready(),
        "class_refs": class_refs,
        # How many holes there are TO group, and whether that is even known. A screen showing
        # "0 unassigned" beside "no take-off has been read" is telling the truth; one showing it
        # alone is not.
        "total_holes": plan.total_holes,
        "take_off_read": schedule is not None,
        "not_checked_because": ("" if schedule is not None else
                                "no station schedule has been read for this tender, so how many "
                                "holes need a class of site is not known — every count on this "
                                "screen is over an empty take-off"),
    }


@router.post("/site/group")
def post_hole_group(req: HoleGroupRequest, actor: str = Depends(_actor)) -> dict:
    """Create or update a group — the estimator's judgement about which holes drill alike.

    Nothing in the client's documents draws these lines, which is why the group carries a ``basis``
    and stays "not ready" until it is written. A number nobody can explain is a number nobody can
    defend.
    """
    conn = store.get_conn()
    try:
        bill = store.load_bill(conn, req.set_id, req.rev)
        resolved_rev = bill.rev if bill else 0
        schedule, _meta = store.load_station_schedule(conn, req.set_id)
        group = boq_groups.summarise(req.group, schedule) if schedule else req.group
        store.save_hole_group(conn, req.set_id, resolved_rev, req.group_id, group, actor)
        existing = store.load_station_classes(conn, req.set_id)
        for station in group.stations:
            store.save_station_class(
                conn, req.set_id, station,
                access_class=existing.get(station, {}).get("access_class", ""),
                group_id=req.group_id, actor=actor)
        # A station REMOVED from the group (a move, or an ungroup) must not keep pointing at it.
        # Membership authority is the group's own station list; this secondary link exists for
        # per-station reads, and a stale one would double-count the hole the moment anything
        # trusted it. The class is untouched, as everywhere: classifying a hole and deciding
        # which spread works it are two different acts.
        members = set(group.stations)
        for station, row in existing.items():
            if row.get("group_id") == req.group_id and station not in members:
                store.save_station_class(
                    conn, req.set_id, station,
                    access_class=row.get("access_class", ""), group_id="", actor=actor)
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "rev": resolved_rev, "group_id": req.group_id,
            "group": group.model_dump(), "ready": group.ready()}


@router.delete("/site/{set_id}/group/{group_id}")
def remove_hole_group(set_id: str, group_id: str, rev: Optional[int] = None,
                      actor: str = Depends(_actor)) -> dict:
    """Remove a group. Its holes keep their access classes — classifying a hole and deciding which
    spread works it are two different acts, and undoing one must not undo the other."""
    conn = store.get_conn()
    try:
        bill = store.load_bill(conn, set_id, rev)
        store.delete_hole_group(conn, set_id, bill.rev if bill else 0, group_id)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {"set_id": set_id, "group_id": group_id, "deleted": True,
            "note": "The holes keep the class you gave them; only the grouping is gone."}


@router.post("/site/preview")
def post_group_preview(req: GroupPreviewRequest) -> dict:
    """The arithmetic under the Groups screen, recomputed as the estimator types.

    Deliberately a round trip rather than the same sum written again in TypeScript. The day-by-day
    simulation — 5% slower every 20 m down, and the afternoon going to rock when soil finishes at
    lunchtime — is the load-bearing calculation in this product, and two implementations of it
    would eventually disagree with no way to tell which was right.

    It prices nothing. Days and the blended rate of work are exact and cheap; the RATE needs the
    whole bill, and comes from ``/boq/{set_id}/priced`` when the estimator leaves the screen.
    """
    conn = store.get_conn()
    try:
        schedule, _meta = store.load_station_schedule(conn, req.set_id)
        book = store.load_output_book(conn)
    finally:
        conn.close()

    group = boq_groups.summarise(req.group, schedule) if schedule else req.group
    group, sources = boq_outputs.apply_to_group(group, book)
    source_dump = {k: v.model_dump() for k, v in sources.items()}
    missing = group.ready()
    if missing:
        return {"ready": False, "waiting_on": missing, "sources": source_dump}

    duration = group.duration()
    metres = group.soil_m + group.rock_m
    # What the as-built corpus says a group of this ROCK FRACTION takes, beside what these outputs
    # give. The band table is the production driver; before this it never reached the group path at
    # all, and a group's speed came from two flat norms and a depth curve the data does not support.
    calibration = boq_groups.band_calibration(
        group, setup_days_per_hole=boq_empirical.FITTED.setup_days_per_hole)
    return {
        "ready": True,
        "sources": source_dump,
        "band": calibration.model_dump(),
        "soil_m": group.soil_m, "rock_m": group.rock_m,
        "soil_days": duration.soil_days,
        "rock_days_charged": duration.rock_days_charged,
        "drilling_days": duration.total_days,
        "on_site_days": float(duration.total_days) + book.mob_days,
        "rigs": group.rigs,
        # What the group actually achieves once decay and the part-day carry-over are in. This
        # number exists so somebody can say "we have never beaten 9 on that hill" and fix it before
        # any money is involved.
        "blended_m_per_day": (metres / duration.total_days) if duration.total_days else 0.0,
        "unfinished": duration.unfinished,
    }


@router.get("/site/{set_id}/georef")
def get_georef(set_id: str, sheet: str = "", window_m: float = boq_georef.DEFAULT_WINDOW_M) -> dict:
    """Where each station sits on a drawing sheet, as fractions of the page.

    Coordinates, never images. One render per sheet is cropped ninety-one ways in the browser, so
    there is no image pipeline here and none is needed — the placement is arithmetic over two
    printed grid marks, which is a ruler rather than a guess.

    ``crops`` is ONE map, station → {sheet, part_id, page, box}, across every registered sheet:
    each located station is assigned to the sheet that CONTAINS its coordinates
    (``georef.sheet_for``), never nearest-match, so a hole off every registered sheet stays in
    ``unplaced`` by name rather than getting a tile of the wrong place. A stored-but-broken
    registration is listed with its problems and contributes zero crops — georef refuses to
    approximate and this endpoint does not help it.
    """
    conn = store.get_conn()
    try:
        schedule = _schedule_or_404(conn, set_id)
        registrations = store.load_sheet_registrations(conn, set_id)
    finally:
        conn.close()
    located = [s for s in schedule.stations if s.easting is not None and s.northing is not None]

    crops: dict[str, dict] = {}
    unplaced: list[str] = []
    for stn in located:
        home = boq_georef.sheet_for(stn.easting, stn.northing, registrations)
        if home is None:
            unplaced.append(stn.station)
            continue
        box = home.crop(stn.easting, stn.northing, window_m=window_m)
        crops[stn.station] = {
            "sheet": home.sheet, "part_id": home.part_id, "page": home.page,
            "box": {**box.model_dump(), "clipped": box.clipped},
        }

    sheets = []
    for registration in registrations:
        plot = boq_georef.plot(schedule, registration) if registration.usable() else None
        sheets.append({
            "sheet": registration.sheet, "part_id": registration.part_id,
            "page": registration.page, "usable": registration.usable(),
            "confirmed_by": registration.confirmed_by,
            "problems": registration.problems(),
            "marks": [m.model_dump() for m in registration.marks],
            "stations_on": len(plot.on_sheet()) if plot else 0,
        })

    # The per-`sheet` block keeps the original contract: what THIS sheet's registration holds,
    # or an empty one saying exactly what it needs.
    asked = next((r for r in registrations if r.sheet == sheet), None) if sheet else None
    probe = asked or boq_georef.SheetRegistration(sheet=sheet)
    return {
        "set_id": set_id, "sheet": sheet, "window_m": window_m,
        "registration": probe.model_dump(),
        "problems": probe.problems(),
        "waiting_on": ("" if any(r.usable() for r in registrations) else
                       "two printed grid marks from this sheet — read the coordinates beside any "
                       "two grid crosses and the other eighty-nine holes follow by arithmetic"),
        "stations": [s.station for s in located],
        "sheets": sheets,
        "crops": crops,
        "unplaced": unplaced,
    }


class SheetRegistrationRequest(BaseModel):
    """Two typed grid marks and where the sheet lives. `confirm` mirrors the schedule's flag:
    it is an act with a name on it, and it is refused (not silently absorbed) on a registration
    georef cannot use — confirming a ruler that refuses to measure means nothing."""
    set_id: str
    registration: boq_georef.SheetRegistration
    confirm: bool = False


@router.post("/site/registration")
def post_sheet_registration(req: SheetRegistrationRequest, actor: str = Depends(_actor)) -> dict:
    """Save one sheet's registration. The response carries the registration's own problems, so a
    mistyped coordinate is named the moment it is typed — the 2% isotropy check catches a bad
    mark instead of averaging it away. A broken registration IS stored (problems-visible, zero
    crops), the same save-then-refuse honesty as the station schedule."""
    registration = req.registration
    if not registration.sheet.strip():
        raise HTTPException(status_code=422, detail="Name the sheet the marks were read from.")
    if not registration.part_id.strip():
        raise HTTPException(
            status_code=422,
            detail="Name the part that holds this sheet — the render every crop points at needs "
                   "it (pick the part, then the page the sheet is on).")
    conn = store.get_conn()
    try:
        parts = store.load_parts(conn, req.set_id)
        spec = next((p for p, _path, _ctx in parts if p.part_id == registration.part_id), None)
        if spec is None:
            raise HTTPException(status_code=404,
                                detail=f"No part {registration.part_id!r} on this set.")
        if not (spec.start <= registration.page <= spec.end):
            raise HTTPException(
                status_code=422,
                detail=f"Page {registration.page} is outside part {registration.part_id} "
                       f"({spec.start}–{spec.end}, source-document numbering).")
        problems = registration.problems()
        store.save_sheet_registration(conn, req.set_id, registration,
                                      confirmed=req.confirm and not problems, actor=actor)
    finally:
        conn.close()
    return {
        "set_id": req.set_id, "sheet": registration.sheet,
        "usable": registration.usable(), "problems": problems,
        "confirmed_by": actor if (req.confirm and not problems) else "",
    }


@router.delete("/site/{set_id}/registration")
def delete_sheet_registration(set_id: str, sheet: str) -> dict:
    """Remove one sheet's registration. `sheet` is a query parameter because drawing numbers
    carry slashes ("60740338/GI/201") and a path segment cannot."""
    conn = store.get_conn()
    try:
        existing = {r.sheet for r in store.load_sheet_registrations(conn, set_id)}
        if sheet not in existing:
            raise HTTPException(status_code=404, detail=f"No registration for sheet {sheet!r}.")
        store.delete_sheet_registration(conn, set_id, sheet)
    finally:
        conn.close()
    return {"set_id": set_id, "sheet": sheet, "deleted": True}


@router.get("/site/{set_id}/roads")
def get_nearest_roads(set_id: str) -> dict:
    """The nearest MAPPED road to every located hole, measured from OpenStreetMap.

    A MEASUREMENT, not a verdict. Given road geometry and a coordinate the distance is arithmetic
    and two people get the same number — but a hole forty metres from a road it cannot be reached
    from is an ordinary thing on a hillside, so this is evidence beside the class decision and
    never the decision. Nothing here writes an access class; `proposed_class` stays empty.

    One bounding-box query for the whole site, not one per hole: ninety-nine round trips on a
    free volunteer-run endpoint is not a reasonable way to ask. The per-hole nearest is then
    computed locally and exactly, to the road SEGMENT rather than to its nearest node.

    DEMO does not run it. Overpass is a real outbound call and DEMO is offline by rule, so this
    says it did not run rather than replaying a fixture that would read as a measurement of the
    tender in front of you.
    """
    from pipeline.llm_client import demo_mode

    conn = store.get_conn()
    try:
        schedule, _meta = store.load_station_schedule(conn, set_id)
    finally:
        conn.close()
    if schedule is None:
        return {"set_id": set_id, **boq_roads.RoadReading(
            waiting_on="the borehole details schedule has not been read yet").model_dump()}

    located = {s.station: boq_hk1980.to_wgs84(s.easting, s.northing)
               for s in schedule.stations
               if s.easting is not None and s.northing is not None}
    if not located:
        return {"set_id": set_id, **boq_roads.RoadReading(
            waiting_on="no station on the schedule carries an easting and a northing, so there "
                       "is nothing to measure from").model_dump()}
    if demo_mode():
        return {"set_id": set_id, **boq_roads.RoadReading(
            waiting_on="road distances are read from OpenStreetMap, which is a live call — demo "
                       "mode is offline, so this has not run. Switch to live to measure them."
        ).model_dump()}

    bbox = boq_roads.bbox_for(list(located.values()))
    try:
        ways = boq_roads.fetch_ways(bbox)                              # type: ignore[arg-type]
    except Exception as exc:                                    # network, DNS, timeout, rate limit
        # A road measurement that did not happen must not read as "no roads near these holes".
        return {"set_id": set_id, **boq_roads.RoadReading(
            waiting_on=f"OpenStreetMap did not answer: {exc}. Nothing here is a measurement of "
                       f"this site — it is a request that failed, and the holes are unchanged."
        ).model_dump()}

    reading = boq_roads.nearest_roads(located, ways)
    reading.source = "OpenStreetMap contributors (ODbL), via Overpass"
    return {"set_id": set_id, **reading.model_dump()}


class RoadPointRequest(BaseModel):
    """A person's click on the map: where the site is entered from. The judgement is theirs (and
    named); every distance that follows is arithmetic."""
    set_id: str
    point_id: str = ""      # blank = the server assigns the next free "road-N"
    label: str = ""
    lat: float
    lon: float


@router.post("/site/road-point")
def post_road_point(req: RoadPointRequest, actor: str = Depends(_actor)) -> dict:
    """Pick (or move) a road-access point. Refuses a point outside Hong Kong by name — the same
    guard the still proxy applies, because a mistyped coordinate would put every distance on the
    tender quietly wrong."""
    if not boq_hk1980.in_hong_kong(req.lat, req.lon):
        raise HTTPException(
            status_code=422,
            detail=f"({req.lat:.5f}, {req.lon:.5f}) is not in Hong Kong. A road-access point off "
                   f"the map would make every measured distance wrong; nothing was saved.")
    conn = store.get_conn()
    try:
        existing = {p["point_id"] for p in store.load_road_points(conn, req.set_id)}
        point_id = req.point_id.strip()
        if not point_id:
            n = 1
            while f"road-{n}" in existing:
                n += 1
            point_id = f"road-{n}"
        store.save_road_point(conn, req.set_id, point_id, label=req.label.strip(),
                              lat=req.lat, lon=req.lon, actor=actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "point_id": point_id, "label": req.label.strip(),
            "lat": req.lat, "lon": req.lon, "picked_by": actor}


@router.delete("/site/{set_id}/road-point/{point_id}")
def delete_road_point(set_id: str, point_id: str) -> dict:
    conn = store.get_conn()
    try:
        existing = {p["point_id"] for p in store.load_road_points(conn, set_id)}
        if point_id not in existing:
            raise HTTPException(status_code=404, detail=f"No road-access point {point_id!r}.")
        store.delete_road_point(conn, set_id, point_id)
    finally:
        conn.close()
    return {"set_id": set_id, "point_id": point_id, "deleted": True}


@router.get("/site/{set_id}/road")
def get_road_distances(set_id: str) -> dict:
    """The picked road-access points and the straight-line metres from every located station to
    the nearest one — the number behind the Holes tiles' brass hint line.

    Deterministic end to end: the points are a person's clicks with names on them, the conversion
    is HK1980→WGS84 in-repo, and the metres are flat-earth arithmetic (fine across a site; Hong
    Kong is 50 km wide). No key, no network, works identically in DEMO. A station with no
    coordinates simply has no entry — absence, not zero.
    """
    conn = store.get_conn()
    try:
        schedule, _meta = store.load_station_schedule(conn, set_id)
        points = store.load_road_points(conn, set_id)
    finally:
        conn.close()
    if schedule is None:
        return {"set_id": set_id, "points": [], "station_m": {},
                "waiting_on": "the borehole details schedule has not been read yet"}
    station_m: dict[str, float] = {}
    if points:
        for stn in schedule.stations:
            if stn.easting is None or stn.northing is None:
                continue
            lat, lon = boq_hk1980.to_wgs84(stn.easting, stn.northing)
            nearest = boq_access.nearest_road_point(lat, lon, points)
            if nearest is not None:
                station_m[stn.station] = round(nearest[1], 0)
    return {
        "set_id": set_id, "points": points, "station_m": station_m,
        "waiting_on": ("" if points else
                       "no road-access point is picked yet — pick one on the MAP view and every "
                       "hole gets its distance by arithmetic"),
    }


# ---------------------------------------------------------------------------
# Price — the working, what a rate must cover, and the sweep
#
# The sweep is the app's ONLY hard stop. Everything else warns and lets you past, because everything
# else can be corrected later; a cost with no bill item and no routing cannot, and the reason is in
# the contract rather than in a preference:
#
#   General Preambles ¶6 — "Items against which no rate is entered shall be deemed to be covered by
#   the other rates in the bill of quantities."
# ---------------------------------------------------------------------------
class CoverageTickRequest(BaseModel):
    """A person saying their build-up does (or no longer does) carry one head."""
    set_id: str
    rev: Optional[int] = None
    full_ref: str = ""          # "" ticks a bill-level head
    head_key: str
    ticked: bool = True
    #: WHICH cost carries it — a build-up basis key. Optional, and a tick without one is still a
    #: tick: it is exactly what every tick was before this field existed, a person's word for it.
    #: Naming the cost is what makes the claim checkable, because the engine already knows which
    #: bases THIS item's rate draws on and can say when the two disagree.
    basis_key: str = ""


class SweepCostRequest(BaseModel):
    set_id: str
    rev: Optional[int] = None
    key: str
    label: str = ""
    source: str = ""
    amount: Optional[float] = None
    route: str = ""             # query | load | spread | accept ('' leaves it unrouted)
    target_ref: str = ""
    reason: str = ""


def _pool_shares_of(bill, stored: dict, rate_rows: list, sweep, full_ref: str
                    ) -> tuple[float, float]:
    """``(spread_share, loading)`` for one item, as the pricing engine itself computes them.

    Not a second opinion: it prices the bill through ``price_bill`` and reads back the one item's
    fields, so the numbers on the trace are the numbers in the rate by construction rather than by
    agreement. Pre-margin, because ``_allocate`` runs on build-up value before the factor is applied
    and the trace shows the margin as its own line further up the tree.

    Cheap in the case that matters: with nothing spread and nothing loaded there is nothing to
    allocate, and the pricing run is skipped entirely.
    """
    spread = sweep.spread_lines()
    loadings = sweep.loadings()
    if not spread and not loadings:
        return 0.0, 0.0
    build_ups, carried = _rate_inputs(stored)
    priced = boq_pricing.price_bill(bill, build_ups, rates=rate_rows, carried=carried,
                                    spread=spread, loadings=loadings)
    for entry in priced.items:
        if entry.full_ref == full_ref:
            return entry.spread, entry.loading
    return 0.0, 0.0


def _coverage_or_404(conn, set_id: str, rev: Optional[int], full_ref: str):
    bill = _bill_or_404(conn, set_id, rev)
    item = bill.index().get(full_ref)
    if item is None:
        raise HTTPException(status_code=404,
                            detail=f"No item {full_ref!r} in the bill at revision {bill.rev}.")
    return bill, item


@router.get("/price/{set_id}/coverage/{full_ref}")
def get_item_coverage(set_id: str, full_ref: str, rev: Optional[int] = None) -> dict:
    """What this rate must cover, and how much of it somebody has said it does.

    The list is a rule's — read off the Method of Measurement and the clauses its item coverage
    cites. The ticks are a person's, every one carrying a name and a date. A machine cannot know
    what you put in your number, so it never guesses: nothing here is ever pre-ticked, and three
    unticked heads is not an error but a decision waiting.
    """
    conn = store.get_conn()
    try:
        bill, item = _coverage_or_404(conn, set_id, rev, full_ref)
        ticks = store.load_coverage_ticks(conn, set_id, bill.rev)
        docmap_row = conn.execute(
            "SELECT map_json FROM client_boq_docmaps WHERE set_id = ? ORDER BY source LIMIT 1",
            (set_id,),
        ).fetchone()
        # THE COST THIS RATE IS ACTUALLY MADE OF. Running the whole costing here is not free, and
        # it is the only way to answer the question honestly: the alternative is asking the person
        # which basis carries a head and never checking the answer, which is where this started.
        # A costing that cannot be built is reported as unknown, NEVER as "nothing to check" —
        # absence reading as health is this codebase's recurring failure.
        bases, drawn_on, costing_note = _bases_for_item(conn, set_id, bill.rev, full_ref)
    finally:
        conn.close()

    docmap = None
    if docmap_row and docmap_row["map_json"] and docmap_row["map_json"] != "{}":
        docmap = boq_docmap.DocumentMap.model_validate_json(docmap_row["map_json"])

    merged = {**ticks.get(full_ref, {}), **ticks.get("", {})}
    coverage = boq_coverage.coverage_for(item, docmap=docmap, ticks=merged)
    if costing_note == "":
        boq_coverage.account_for_cost(coverage, bases=bases, drawn_on=drawn_on)
    return {
        "set_id": set_id, "rev": bill.rev,
        "full_ref": full_ref, "description": item.description,
        "summary": coverage.summary(),
        "entries": [e.model_dump() for e in coverage.entries],
        "bill_level": coverage.bill_level.model_dump() if coverage.bill_level else None,
        "uncovered": [e.key for e in coverage.uncovered()],
        "settled": coverage.settled(),
        "note": coverage.note,
        # WHY THIS LIST IS NOT THE WHOLE COVERAGE. The pack carries this contract's AMENDMENTS to
        # the SMM 1992, not the SMM itself, so every list here is partial by construction. A
        # partial list that reads as complete is the same failure as an empty one reading as
        # "fully covered" — it just takes longer to notice.
        "partial": coverage.partial,
        # A tick recorded against a head this item no longer has. Never applied; always named.
        "orphan_ticks": coverage.orphan_ticks,
        # An empty list must never read as "this rate covers nothing". `no_list_reason` says which
        # of the three cases it is — the clause is known and its words are not, nothing matched the
        # item by title, or nothing has been transcribed for this bill at all. They are three
        # different problems with three different fixes.
        "waiting_on": coverage.no_list_reason,
        # WHAT THE RATE ACTUALLY PAYS FOR, set beside what it is obliged to carry. A tick used to
        # be a belief and nothing could check it; naming the cost makes it a link, and a link
        # against a basis this item's rate does not draw on is an obligation claimed against money
        # that is not in the number. `bases` is offered so the choice is a pick, not a typed key.
        "accounting": {
            "summary": coverage.accounting_summary(),
            "checked": costing_note == "",
            "not_checked_because": costing_note,
            "accounted_by_cost": [e.key for e in coverage.accounted_by_cost()],
            "asserted_only": [e.key for e in coverage.asserted_only()],
            "cost_not_in_rate": [e.key for e in coverage.cost_not_in_rate()],
            "unaccounted": [e.key for e in coverage.unaccounted()],
            "problems": coverage.accounting_problems(),
            "drawn_on": sorted(drawn_on),
            "bases": [{"key": key, "label": label} for key, label in sorted(bases.items())],
        },
    }


def _bases_for_item(conn, set_id: str, rev: int, full_ref: str) -> tuple[dict, set, str]:
    """``(basis_key -> label, the keys THIS item's rate draws on, why it could not be worked out)``.

    The live engine maps one bill item to at most one cost basis (`ItemMapping.basis_key`), plus a
    laboratory buy rate or a preliminaries resource. All three are "where this rate's money comes
    from", so all three count as drawn on — a head carried by the laboratory line is carried.

    The third element is the honest-degradation half. A costing that cannot be built means the
    check DID NOT RUN, which is a different state from "ran and found nothing wrong", and the
    payload says which.
    """
    try:
        parts = _costing(conn, set_id, rev)
    except HTTPException as exc:
        return {}, set(), (f"the costing model could not be built for this tender "
                           f"({exc.detail}), so the rate's own cost could not be read")
    except Exception as exc:  # noqa: BLE001 — a check that cannot run must not sink the screen
        return {}, set(), (f"the costing model could not be built for this tender ({exc}), so the "
                           f"rate's own cost could not be read")
    bases = {row.key: row.label or row.key for row in parts["buildup"].rows}
    mapping = next((m for m in parts["item_mappings"] if m.full_ref == full_ref), None)
    drawn = {k for k in ((mapping.basis_key, mapping.lab_key, mapping.prelim_key) if mapping
                         else ()) if k}
    return bases, drawn, ""


@router.post("/price/coverage/tick")
def post_coverage_tick(req: CoverageTickRequest, actor: str = Depends(_actor)) -> dict:
    """Tick or untick one head. **Only this endpoint writes a tick, and only a person calls it.**

    The same structural refusal ``/review/approve`` makes for a clause verdict: there is no badge
    column on the row and no code path by which a model could set one.
    """
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        store.save_coverage_tick(conn, req.set_id, bill.rev, req.full_ref, req.head_key,
                                 req.ticked, actor, req.basis_key)
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "rev": bill.rev, "full_ref": req.full_ref,
            "head_key": req.head_key, "ticked": req.ticked, "ticked_by": actor if req.ticked else ""}


def _trace_terms(build, rate_rows) -> list[dict]:
    """The stored build-up's resource lines as the tree's term children.

    Pure display of the lines' own documented arithmetic (qty ÷ productivity = hours; hours ×
    rate = amount — models.ResourceLine): nothing here re-prices anything. A line naming a rate
    the book no longer carries keeps unit_cost 0.0 and shows as such rather than vanishing.
    """
    if build is None:
        return []
    by_id = {r.rate_id: r.rate for r in rate_rows}
    terms = []
    for line in build.lines:
        rate = (line.inline_rate if line.inline_rate is not None
                else by_id.get(line.resource_ref, 0.0))
        units = (line.qty / line.productivity) if line.productivity else line.qty
        terms.append({
            "label": line.description or line.resource_ref or "(unnamed line)",
            "key": line.resource_ref,
            "units": round(units, 2),
            "unit_cost": round(rate or 0.0, 2),
            "value": round(units * (rate or 0.0), 2),
        })
    return terms


@router.get("/price/{set_id}/trace/{full_ref}")
def get_rate_trace(set_id: str, full_ref: str, rev: Optional[int] = None,
                   margin_pct: float = 0.0) -> dict:
    """How this rate was reached, as a tree that opens all the way down to a page.

    Every leaf says whether it came from a document, a person or the library, and ``problems`` names
    any that cannot — because a tree with one unattributed number still looks complete, and looking
    complete is the failure this screen exists to prevent.
    """
    conn = store.get_conn()
    try:
        bill, item = _coverage_or_404(conn, set_id, rev, full_ref)
        rates = store.load_bill_rates(conn, set_id, bill.rev)
        schedule, _meta = store.load_station_schedule(conn, set_id)
        groups = store.load_hole_groups(conn, set_id, bill.rev)
        sweep = store.load_sweep(conn, set_id, bill.rev)
        rate_rows = rates_store.load(conn)
        own_model = store.load_set_model(conn, set_id)
    finally:
        conn.close()
    spread_share, loading = _pool_shares_of(bill, rates, rate_rows, sweep, full_ref)

    row = rates.get(full_ref)
    # A lump item's quantity is legitimately absent — SMM Corr. 1/2007 Part III ¶3 prints "-" in the
    # rate column — so `qty` is Optional on the model and must not be handed straight to arithmetic.
    qty = item.qty or 0.0
    breakdown = boq_allocate.RateBreakdown(
        full_ref=full_ref, label=item.description,
        rate=row["rate"] if row else None,
        cost=(row["amount"] or 0.0) if row else 0.0,
        divisor=qty, divisor_label=item.unit, lump=item.lump, markup_pct=margin_pct,
        # THE TERMS WERE ALWAYS THERE. `load_bill_rates` parses the stored build-up
        # (`buildup_json` → a ScheduleItem) and this endpoint dropped it on the floor — so the
        # build-up node had no children, and the tree's own honesty check flagged it "a bare
        # number with nothing behind it" on every response. The resource lines ARE what is
        # behind it.
        terms=_trace_terms(row.get("build_up") if row else None, rate_rows),
    )
    trace = boq_trace.trace_rate(
        breakdown, description=item.description, unit=item.unit, qty=qty,
        amount=row["amount"] if row else None, margin_pct=margin_pct,
        # Who the margin belongs to: the model in force, named by PROVENANCE — the app does not
        # record which person set a model input, and the rate row's author (what used to sit
        # here) is a different person's name on somebody else's decision.
        margin_owner=("this tender's model" if own_model is not None else "the library model"),
        # In THIS engine the divisor is the bill's own quantity, and the bill names its page.
        # A synthetic part locator ("bq:rev") because the workbook is not a PDF part — the
        # label carries the human-readable half.
        divisor_cite=boq_trace.Citation(
            part_id=f"bq:{bill.rev}", page=0,
            label=(f"{item.page_ref} · the bill's own quantity: {qty:g} {item.unit}"
                   if item.page_ref else
                   f"the bill's own quantity: {qty:g} {item.unit}")),
        groups=groups, schedule=schedule,
        # `PricedItem.spread` IS this item's share — `_allocate` computes it pro rata on build-up
        # value, which `pricing.py` states is the only proxy the bill itself supplies. This was a
        # literal 0.0 beside a `spread_total` loaded from the real sweep, and because `trace.py`
        # guards the node on `if spread_share:`, the total was read from the database and thrown
        # away on every request: the endpoint could not show a penny of the pool.
        spread_share=spread_share,
        spread_total=sweep.spread_total(),
        loading=loading,
    )
    return {
        "set_id": set_id, "rev": bill.rev, "full_ref": full_ref,
        "trace": trace.model_dump(),
        "priced": row is not None,
        "waiting_on": ("" if row else
                       "this item has no rate yet — price it and the working appears here"),
    }


@router.get("/price/{set_id}/sweep")
def get_sweep(set_id: str, rev: Optional[int] = None) -> dict:
    """Costs the contract makes yours that no bill item asks for, and where each one is going."""
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, set_id, rev)
        sweep = store.load_sweep(conn, set_id, bill.rev)
    finally:
        conn.close()
    return {
        "set_id": set_id, "rev": bill.rev,
        "costs": [c.model_dump() for c in sweep.costs],
        # `outstanding()` returns the reasons, one sentence per unrouted cost — the same sentences
        # the gate refuses with, so the screen can show them before the button is pressed rather
        # than after.
        "outstanding": sweep.outstanding(),
        "settled": sweep.settled(),
        "spread_total": sweep.spread_total(),
        "loadings": sweep.loadings(),
        "queries": [c.label for c in sweep.queries()],
        "accepted_risk": sweep.accepted_risk(),
        "routes": list(boq_unbilled.ROUTES),
        "route_meaning": boq_unbilled.ROUTE_MEANING,
        "warning": boq_unbilled.SILENCE_WARNING,
    }


@router.post("/price/sweep")
def post_sweep_cost(req: SweepCostRequest, actor: str = Depends(_actor)) -> dict:
    """Add a cost to the sweep, or route one already on it.

    Routing is a decision and it is stamped. Accepting a risk needs a written reason, because a risk
    somebody took deliberately and one nobody noticed look identical six months later.
    """
    if req.route and req.route not in boq_unbilled.ROUTES:
        raise HTTPException(
            status_code=422,
            detail=f"{req.route!r} is not a route. There are four: "
                   f"{', '.join(boq_unbilled.ROUTES)}.")
    cost = boq_unbilled.UnbilledCost(
        key=req.key, label=req.label, source=req.source, amount=req.amount,
        route=req.route, target_ref=req.target_ref, reason=req.reason, decided_by=actor)
    problem = cost.problem() if req.route else None
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        if req.route == boq_unbilled.ROUTE_LOAD and req.target_ref not in bill.index():
            raise HTTPException(
                status_code=422,
                detail=f"There is no item {req.target_ref!r} to load {req.label or req.key!r} onto.")
        store.save_sweep_cost(conn, req.set_id, bill.rev, cost, actor)
        sweep = store.load_sweep(conn, req.set_id, bill.rev)
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "rev": bill.rev, "key": req.key, "route": req.route,
            "decided_by": actor if req.route else "",
            "outstanding": len(sweep.outstanding()), "settled": sweep.settled()}


#: The bill items that price a rig move by class of site. If the client billed either, the holes
#: exist whether or not anybody has read the take-off — which is what lets the settle refuse an
#: unread schedule instead of waving it through.
RIG_MOVE_REFS = ("2.2a", "2.2b")


def _billed_rig_moves(bill) -> bool:
    """Does this bill price rig moves by class of site? Read off the client's own quantities."""
    index = bill.index()
    return any((index.get(ref) is not None and (index[ref].qty or index[ref].lump))
               for ref in RIG_MOVE_REFS)


@router.post("/price/{set_id}/sweep/settle")
def settle_sweep(set_id: str, rev: Optional[int] = None, actor: str = Depends(_actor)) -> dict:
    """Declare the sweep settled. **The app's only hard stop.**

    Refuses on the module's own sentence, unrewritten — it names each outstanding cost and says what
    leaving it costs. Also refuses while a hole has no access class, which is where the Site step's
    missing gate actually lands: an unclassed hole is a rig move nobody has priced.
    """
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, set_id, rev)
        sweep = store.load_sweep(conn, set_id, bill.rev)
        schedule, _meta = store.load_station_schedule(conn, set_id)
        classes = store.load_station_classes(conn, set_id)
    finally:
        conn.close()

    # ABSENCE IS NOT CLEARANCE.
    #
    # This read `if schedule is not None:`, and the net could therefore not fire in exactly the
    # case it was written for: with no take-off there are no holes, so no hole is unclassed, so
    # nothing refused — and the only screen in the application that assigns an access class sits
    # behind the take-off gate, so there was no path by which those classes could have been
    # supplied. A tender could be settled and priced with the net silently absent rather than
    # tripped. `chrome.tsx` had the mirror of it, computing "N HOLES UNASSIGNED" over an empty list
    # and reading 0.
    #
    # The bill's own quantities are what make the refusal possible without a take-off: 2.2a and
    # 2.2b are the rig moves the CLIENT billed, and if he billed any, holes exist and somebody has
    # to say which class each is. No schedule then means the classes are UNKNOWN, which is a
    # refusal, not a pass.
    if schedule is not None:
        unassigned = [s.station for s in schedule.stations
                      if not classes.get(s.station, {}).get("access_class")]
        if unassigned:
            raise HTTPException(
                status_code=409,
                detail=(f"{len(unassigned)} hole(s) still have no class of site — "
                        f"{', '.join(unassigned[:5])}{'…' if len(unassigned) > 5 else ''}. "
                        f"Each one is a rig move that has not been priced against 2.2a or 2.2b."))
    elif _billed_rig_moves(bill):
        raise HTTPException(
            status_code=409,
            detail=("No station schedule has been read for this tender, so no hole has a class of "
                    "site — and the bill prices rig moves against 2.2a and 2.2b, which means the "
                    "holes exist and somebody has to say which class each one is. Read the "
                    "take-off in on the Site step (paste it, or read it off the borehole details "
                    "drawing) and classify the holes. An unknown class is not a cleared one."))
    try:
        boq_unbilled.gate(sweep)
    except boq_unbilled.UnroutedCost as refused:
        raise HTTPException(status_code=409, detail=str(refused)) from refused

    conn = store.get_conn()
    try:
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {"set_id": set_id, "rev": bill.rev, "settled": True, "by": actor,
            "spread_total": sweep.spread_total(), "loadings": sweep.loadings(),
            "accepted_risk": sweep.accepted_risk()}


# ---------------------------------------------------------------------------
# Costing — the bill in, the priced workbook out
#
# The whole point of the module: a client's bill of quantities becomes a bottom-up cost build-up and
# an eight-sheet Excel model that still calculates. Everything the engine does is described by an
# editable CostingModel, and a change made on one tender stays on that tender (copy-on-write).
# ---------------------------------------------------------------------------
class CostingModelRequest(BaseModel):
    model: boq_model.CostingModel


class SubmittedRateRequest(BaseModel):
    set_id: str
    rev: Optional[int] = None
    full_ref: str
    rate: Optional[float] = None    # None puts the rounded proposal back


class ItemBasisRequest(BaseModel):
    set_id: str
    rev: Optional[int] = None
    full_ref: str
    #: Exactly one of these. Empty strings in all three clear the override and put the app's own
    #: proposal back — the same "None restores the proposal" rule the submitted rate follows.
    basis_key: str = ""
    lab_key: str = ""
    prelim_key: str = ""


@router.post("/costing/item-basis")
def post_item_basis(req: ItemBasisRequest, actor: str = Depends(_actor)) -> dict:
    """Point one bill item at the thing that should price it.

    ``_costing`` has always READ these overrides out of the costing state and applied them; nothing
    ever wrote one. So a proposal the app got wrong could only be typed over with a flat rate, which
    loses the build-up behind it — you got a number instead of a model. This is the missing half.
    """
    chosen = [k for k in (req.basis_key, req.lab_key, req.prelim_key) if k]
    if len(chosen) > 1:
        raise HTTPException(status_code=422,
                            detail="An item is priced by one thing. Send basis_key, lab_key or "
                                   "prelim_key — not more than one.")
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        if req.full_ref not in bill.index():
            raise HTTPException(status_code=404,
                                detail=f"No item {req.full_ref!r} in revision {bill.rev}.")
        model = boq_model.effective(store.load_library_model(conn), store.load_set_model(conn, req.set_id))
        for key, index, what in ((req.basis_key, model.basis_index(), "build-up basis"),
                                 (req.lab_key, model.lab_index(), "laboratory rate"),
                                 (req.prelim_key, model.prelim_index(), "preliminaries resource")):
            if key and key not in index:
                raise HTTPException(
                    status_code=422,
                    detail=f"{key!r} is not a {what} in this model. Available: "
                           f"{', '.join(sorted(index)[:12])}")

        state = store.load_costing_state(conn, req.set_id, bill.rev)
        items = dict(state["mapping"].get("items") or {})
        if chosen:
            items[req.full_ref] = {"basis_key": req.basis_key, "lab_key": req.lab_key,
                                   "prelim_key": req.prelim_key}
        else:
            items.pop(req.full_ref, None)
        store.save_costing_state(conn, req.set_id, bill.rev,
                                 mapping={**state["mapping"], "items": items}, actor=actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "rev": bill.rev, "full_ref": req.full_ref,
            "basis_key": req.basis_key, "lab_key": req.lab_key, "prelim_key": req.prelim_key,
            "cleared": not chosen, "by": actor}


class AssumptionVerdictRequest(BaseModel):
    set_id: str
    rev: Optional[int] = None
    key: str
    status: str = ""                # Accepted | Revised | Rejected ('' = back to unreviewed)
    comment: str = ""


class AssumptionValueRequest(BaseModel):
    """Change the NUMBER a register row is about, not the verdict on it."""

    set_id: str
    rev: Optional[int] = None
    key: str                        # the register row's key
    value: float


class ConditionRequest(BaseModel):
    """A condition somebody wrote down. Free prose — the notepad and the form are one thing."""

    set_id: str
    text: str
    #: The site-log discussion this condition was born of, 0 for none — provenance, never a value.
    born_of_seq: int = 0
    note: str = ""
    condition_id: str = ""          # blank mints one


class ConditionDecisionRequest(BaseModel):
    set_id: str
    condition_id: str
    status: str                     # confirmed | rejected | '' (back to undecided)
    #: What to write when confirming. Defaults to the proposal's own number; a person may type a
    #: different one, which is the point of confirming rather than accepting.
    value: Optional[float] = None


def _apply_model_path(model: boq_model.CostingModel, path: str, value: float) -> str:
    """Write one dotted path into a model IN PLACE. Returns what it used to be, for the record.

    Two shapes, both the workbook's own naming: ``inputs.<key>`` and ``spread.<key>.<field>``. A
    path naming something the model does not have raises — a write that silently lands nowhere is
    the exact failure `problems()` already guards the read side against.
    """
    parts = path.split(".")
    if len(parts) == 2 and parts[0] == "inputs":
        key = parts[1]
        if key not in model.inputs:
            raise HTTPException(
                status_code=422,
                detail=f"This model has no input {key!r}, so there is nothing to change. It may "
                       f"have been retired — a retired input is inert and setting it changes "
                       f"nothing, which is why writing to one is refused rather than accepted.")
        was = f"{model.inputs[key]:g}"
        model.inputs[key] = value
        return was
    if len(parts) == 3 and parts[0] == "spread" and parts[2] in {"rate", "multiplier"}:
        line = model.spread_index().get(parts[1])
        if line is None:
            raise HTTPException(status_code=422,
                                detail=f"This model has no spread line {parts[1]!r}.")
        was = f"{getattr(line, parts[2]):g}"
        setattr(line, parts[2], value)
        return was
    raise HTTPException(status_code=422, detail=f"{path!r} is not a path this model can be changed at.")


def _class_b_platform_total(groups, classes: dict) -> float:
    """The platform money that belongs in the Class B rig-move basis: builds typed on groups whose
    EFFECTIVE class is B — stored, or inferred from a single shared station class, the same rule
    ``GET /site/{set_id}/groups`` applies. A platform typed on a Class A group is NOT consumed
    (a Class A move must not carry a platform it does not need) and stays flagged on the checks
    surface rather than being absorbed."""
    total = 0.0
    for group in groups:
        cls = group.access_class
        if not cls:
            assigned = {classes.get(name, {}).get("access_class", "") for name in group.stations}
            assigned.discard("")
            if len(assigned) == 1:
                cls = next(iter(assigned))
        if cls == "B":
            total += group.access_build_cost
    return total


def _costing(conn, set_id: str, rev: Optional[int]) -> dict:
    """Run the whole engine for one tender. The single path everything else here goes through."""
    bill = _bill_or_404(conn, set_id, rev)
    library = store.load_library_model(conn)
    own = store.load_set_model(conn, set_id)
    model = boq_model.effective(library, own)
    state = store.load_costing_state(conn, set_id, bill.rev)

    mapping = boq_costing.propose_quantities(bill)
    for role, confirmed in (state["mapping"].get("quantities") or {}).items():
        if role in mapping.matches and confirmed.get("full_ref"):
            item = bill.index().get(confirmed["full_ref"])
            if item is not None:
                mapping.matches[role] = mapping.matches[role].model_copy(update={
                    "full_ref": item.full_ref, "description": item.description,
                    "value": item.qty or 0.0, "unit": item.unit, "confirmed": True,
                    "why": "confirmed by hand"})

    item_mappings = boq_costing.propose_pricing(bill, model)
    chosen = state["mapping"].get("items") or {}
    for entry in item_mappings:
        override = chosen.get(entry.full_ref)
        if override:
            entry.basis_key = override.get("basis_key", "")
            entry.lab_key = override.get("lab_key", "")
            entry.prelim_key = override.get("prelim_key", "")
            entry.confirmed = True
            entry.why = "confirmed by hand"

    quantities = mapping.quantities()
    programme = boq_programme.derive(quantities, model)
    spread = boq_buildup.build_spread(programme, model)
    # THE PER-CLASS RIG-MOVE WIRING (plan Phase 3). `active_keys` is what the items actually
    # claim after overrides; pointing 2.2a/2.2b at the derived class variants (the one-click act
    # on the Costing screen) is what switches the split on. The counts are the BILL's own 80/11
    # — the only external check on the estimator's classification — and the Class B platform
    # total rides in so ¶2.08(h) money lands inside the Class B move rate, never Class A's.
    active_keys = {entry.basis_key for entry in item_mappings if entry.basis_key}
    _criteria, class_refs = store.load_site_criteria(conn, set_id)
    class_counts = {k: float(v) for k, v in _billed_class_counts(bill, class_refs).items()}
    platform_b = _class_b_platform_total(store.load_hole_groups(conn, set_id, bill.rev),
                                         store.load_station_classes(conn, set_id))
    buildup = boq_buildup.build(programme, model, spread, active_keys=active_keys,
                                class_counts=class_counts, platform_cost_b=platform_b)
    priced = boq_costing.price(bill, model, programme, buildup, item_mappings,
                               submitted=state["submitted"])

    billed_standing = None
    for item in bill.items:
        if item.unit == "h" and "standing" in item.description.lower():
            billed_standing = item.qty
            break
    register = boq_assumptions.build(programme, model, buildup, spread,
                                     verdicts=state["verdicts"],
                                     billed_standing_hours=billed_standing)

    # Is every cost recovered exactly once? A deterministic join between the build-up and the
    # priced bill — see `boq/conservation.py`. Computed on the one path everything goes through,
    # so no screen and no workbook can show a total without it having been asked.
    balance = boq_conservation.check(bill, buildup, item_mappings)

    return {
        "bill": bill, "library": library, "own": own, "model": model, "state": state,
        "mapping": mapping, "item_mappings": item_mappings, "programme": programme,
        "spread": spread, "buildup": buildup, "priced": priced, "register": register,
        "billed_standing_hours": billed_standing, "conservation": balance,
        "class_refs": class_refs, "class_counts": class_counts,
        "platform_cost_b": platform_b,
    }


@router.get("/costing/model")
def get_library_model() -> dict:
    """The company's costing model — bands, resources, drivers, mark-up, rounding, every input.

    Seeded from the reference template on first read, so a company that has never opened this screen
    can still price something. Everything on it is editable.
    """
    conn = store.get_conn()
    try:
        model = store.load_library_model(conn)
    finally:
        conn.close()
    return {"model": model.model_dump(), "problems": model.problems(), "usable": model.usable(),
            **_model_declarations(model)}


def _model_declarations(model: boq_model.CostingModel) -> dict:
    """What the inputs MEAN, so a screen can render them without a second copy of the knowledge.

    The workbook reads the same declarations (``model.INPUT_SPECS``). A key with no spec would be
    invisible on both, which is what the drift test in the costing-model tests exists to prevent.
    """
    return {
        "input_blocks": list(boq_model.INPUT_BLOCKS),
        "input_specs": [spec.model_dump() for spec in boq_model.INPUT_SPECS],
        "charge_labels": {
            boq_model.CHARGE_RIG_DAY: "per rig-day — scales with the rig count",
            boq_model.CHARGE_CONTRACT_DAY: "per contract-day — the SITE team, per site",
            boq_model.CHARGE_GFT: "per GFT-day — the GFT, one per gft_ratio rigs",
            boq_model.CHARGE_PRELIM: "billed as its own item — in neither day-cost",
            boq_model.CHARGE_NONE: "not charged",
        },
        # Inputs this model still carries that nothing reads. Inert by construction; said out loud
        # so a knob that stopped being connected is not discovered from a number that never moves.
        "retired": [{"key": key, "value": value, "why": why} for key, value, why in model.retired()],
    }


@router.put("/costing/model")
def put_library_model(req: CostingModelRequest, actor: str = Depends(_actor)) -> dict:
    """Save the company's model. Changes every future tender; never rewrites one already priced."""
    conn = store.get_conn()
    try:
        store.save_library_model(conn, req.model, actor)
    finally:
        conn.close()
    return {"model": req.model.model_dump(), "problems": req.model.problems()}


def conservation_state(set_id: str, rev: Optional[int] = None) -> dict:
    """Does this tender's cost come out the other side exactly once? A pure read, for any caller.

    THE LAW. ``price()`` computes ``row.direct_cost = qty × basis.cost_per_unit`` and ``build()``
    computes ``basis.cost_per_unit = basis.total_cost / basis.divisor``, so a basis is recovered
    exactly once when the quantities of the items claiming it sum to its divisor. Anything else is
    money moving without anybody deciding it should.

    THE ONE PUBLIC ENTRY POINT for that verdict, because it has to be read in three places that do
    not share a module: the costing screen, the offer letter's approval, and the deliverable
    workbook. Three implementations of one law is how two of them would come to disagree.

    Degrades honestly and never raises. A costing that cannot be built returns ``checked: False``
    with the reason — which is a DIFFERENT state from "checked and clean", and the payload says
    which, because absence reading as health is this codebase's recurring failure.
    """
    conn = store.get_conn()
    try:
        parts = _costing(conn, set_id, rev)
    except HTTPException as exc:
        return {"checked": False, "clean": None, "difference": 0.0, "headline": "",
                "problems": [], "not_checked_because": str(exc.detail)}
    except Exception as exc:  # noqa: BLE001 — a check that cannot run must not sink its caller
        return {"checked": False, "clean": None, "difference": 0.0, "headline": "",
                "problems": [], "not_checked_because": str(exc)}
    finally:
        conn.close()
    balance = parts["conservation"]
    return {"checked": True, "clean": balance.clean(), "difference": balance.difference(),
            "headline": balance.headline(), "problems": balance.problems(),
            "not_checked_because": ""}


@router.get("/costing/{set_id}")
def get_costing(set_id: str, rev: Optional[int] = None) -> dict:
    """Everything the costing screens need: the model in force, the programme, and the priced bill."""
    conn = store.get_conn()
    try:
        parts = _costing(conn, set_id, rev)
    finally:
        conn.close()

    programme, register = parts["programme"], parts["register"]
    standing = boq_programme.against_the_bill(programme, parts["billed_standing_hours"])
    return {
        "set_id": set_id, "rev": parts["bill"].rev,
        "model": parts["model"].model_dump(),
        # Empty when this tender is still on the library's model — which is itself the answer to
        # "has anybody changed anything here".
        "marks": boq_model.compare(parts["library"], parts["own"]),
        "using_own_model": parts["own"] is not None,
        "quantities": {role: match.model_dump() for role, match in parts["mapping"].matches.items()},
        "unmatched_roles": parts["mapping"].unmatched_roles,
        "mapping_problems": parts["mapping"].problems(),
        "item_mappings": [m.model_dump() for m in parts["item_mappings"]],
        "programme": programme.model_dump(),
        "checks": [c.model_dump() for c in programme.checks] + (
            [standing.model_dump()] if standing else []),
        "spread": parts["spread"].model_dump(),
        # The rig count as a COMPARISON — every n priced, the cheapest feasible proposed. A
        # consequence of the same programme and model the rest of this payload shows; the
        # confirmed count stays the estimator's (the register's rig row is theirs to verdict).
        "optimiser": boq_optimiser.optimise(programme, parts["model"]).model_dump(),
        "buildup": parts["buildup"].model_dump(),
        "priced": parts["priced"].model_dump(),
        # The per-class rig-move wiring, for the screen's one-click switch: which bill items carry
        # the Class A / Class B moves (the set's class_refs), the billed counts, and the platform
        # money that lands in the Class B basis the moment the split is on.
        "class_refs": parts["class_refs"],
        "class_counts": parts["class_counts"],
        "platform_cost_b": parts["platform_cost_b"],
        # THE CONSERVATION CHECK. `priced.total` is a number; this says whether it is the cost of
        # the work. A basis nothing claims is cost given away (GP ¶6); a basis whose claimants do
        # not sum to its divisor is cost recovered twice. Reported beside the total, never applied
        # to it — which of those is the right repair is the estimator's decision, not arithmetic.
        "conservation": {
            **parts["conservation"].model_dump(),
            "clean": parts["conservation"].clean(),
            "difference": parts["conservation"].difference(),
            "headline": parts["conservation"].headline(),
            "problems": parts["conservation"].problems(),
        },
        # A reference priced more than once. The bill reader keeps both copies of a repeated
        # reference deliberately — "neither is assumed correct" — but every index downstream keys
        # on the reference and collapses them, so a screen shows 63 where the workbook prints 64
        # and the workbook's SUM counts one line's amount twice. Named here so the two surfaces
        # stop disagreeing silently.
        "duplicates": {
            "refs": parts["priced"].duplicate_refs(),
            "amount": parts["priced"].duplicate_total(),
            "note": parts["priced"].duplicate_note(),
        },
        "register": {
            "rows": [r.model_dump() for r in register.rows],
            "gate": register.gate(), "summary": register.summary(),
            "outstanding": len(register.outstanding()),
        },
        **_model_declarations(parts["model"]),
    }


@router.put("/costing/{set_id}/model")
def put_set_model(set_id: str, req: CostingModelRequest, actor: str = Depends(_actor)) -> dict:
    """Change the model **for this tender only**.

    Copy-on-write: this is the write that makes the tender's model its own. The library is untouched
    and no other tender moves — which is the whole of "a change made on one job stays on that job".
    """
    conn = store.get_conn()
    try:
        store.save_set_model(conn, set_id, req.model, actor=actor)
        library = store.load_library_model(conn)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {"set_id": set_id, "model": req.model.model_dump(),
            "marks": boq_model.compare(library, req.model),
            "problems": req.model.problems(), "using_own_model": True}


@router.delete("/costing/{set_id}/model")
def delete_set_model(set_id: str, actor: str = Depends(_actor)) -> dict:
    """Put this tender back on the library's model, discarding its own copy."""
    conn = store.get_conn()
    try:
        store.clear_set_model(conn, set_id)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {"set_id": set_id, "using_own_model": False,
            "note": "This tender is back on the library's model. Its own copy is gone."}


@router.post("/costing/rate")
def post_submitted_rate(req: SubmittedRateRequest, actor: str = Depends(_actor)) -> dict:
    """Type a rate over the rounded proposal. The last decision before a tender goes in is a
    commercial one, and it is not the app's."""
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        if req.full_ref not in bill.index():
            raise HTTPException(status_code=404,
                                detail=f"No item {req.full_ref!r} in the bill at revision "
                                       f"{bill.rev}.")
        if req.rate is None:
            store.clear_submitted_rate(conn, req.set_id, bill.rev, req.full_ref)
        else:
            store.save_costing_state(conn, req.set_id, bill.rev,
                                     submitted={req.full_ref: req.rate}, actor=actor)
        store.touch_set(conn, req.set_id, actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "rev": bill.rev, "full_ref": req.full_ref, "rate": req.rate,
            "by": actor}


@router.post("/costing/assumption")
def post_assumption_verdict(req: AssumptionVerdictRequest, actor: str = Depends(_actor)) -> dict:
    """Rule on one assumption. **Only a person calls this**, and the register is the human gate.

    It warns and does not block — the sweep is the app's only hard stop — but the workbook prints
    NOT CLEARED until every row has a verdict, so a model nobody reviewed cannot pass as one that
    somebody did.
    """
    from datetime import datetime, timezone
    if req.status and req.status not in boq_assumptions.STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"{req.status!r} is not a verdict. There are three: "
                   f"{', '.join(boq_assumptions.STATUSES)} — or blank for not yet reviewed.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        store.save_costing_state(conn, req.set_id, bill.rev, actor=actor, verdicts={
            req.key: {"status": req.status, "reviewed_by": actor if req.status else "",
                      "reviewed_at": now if req.status else None, "comment": req.comment}})
        parts = _costing(conn, req.set_id, bill.rev)
    finally:
        conn.close()
    register = parts["register"]
    return {"set_id": req.set_id, "rev": bill.rev, "key": req.key, "status": req.status,
            "reviewed_by": actor if req.status else "",
            "gate": register.gate(), "outstanding": len(register.outstanding())}


@router.post("/costing/assumption-value")
def post_assumption_value(req: AssumptionValueRequest, actor: str = Depends(_actor)) -> dict:
    """Change the NUMBER a register row is about. The register becomes editable, not just signable.

    A register that can only be confirmed is a page of agreements about numbers you have to go
    somewhere else to change — so people change them somewhere else and the register goes stale,
    which is the failure this whole surface was built against. Every judgement row names the model
    path it is about (``Assumption.edit_path``), so typing here writes THAT and nothing else, and
    the programme, the rig curve, the group durations and every rate recompute from it. There is no
    second write path.

    Copy-on-write, like every other model edit: the first one makes this tender's model its own and
    the library is untouched. A DERIVED row has no path and is refused — its number is read from
    the bill or worked out from it, and typing over it would be inventing a fact.
    """
    conn = store.get_conn()
    try:
        bill = _bill_or_404(conn, req.set_id, req.rev)
        parts = _costing(conn, req.set_id, bill.rev)
        row = next((r for r in parts["register"].rows if r.key == req.key), None)
        if row is None:
            raise HTTPException(status_code=404,
                                detail=f"No assumption {req.key!r} on this register.")
        if not row.edit_path:
            raise HTTPException(
                status_code=422,
                detail=(f"{row.label!r} is not a number anybody types. "
                        + ("It is derived — read from the bill or worked out from it, so changing "
                           "it here would be inventing a fact. Change what it is derived FROM."
                           if row.derived else
                           "It has no single input behind it, so there is nothing here to write.")))

        model = parts["model"].model_copy(deep=True)
        was = _apply_model_path(model, row.edit_path, req.value)
        store.save_set_model(conn, req.set_id, model, actor=actor)
        store.touch_set(conn, req.set_id, actor)
        after = _costing(conn, req.set_id, bill.rev)
    finally:
        conn.close()
    fresh = next((r for r in after["register"].rows if r.key == req.key), None)
    return {
        "set_id": req.set_id, "rev": bill.rev, "key": req.key, "path": row.edit_path,
        "was": was, "value": req.value, "now": fresh.value if fresh else "",
        "by": actor, "using_own_model": True,
        # What moved, so the screen can say it rather than the reader hunting for it.
        "recomputed": {
            "work_days": after["programme"].work_days,
            "rigs_required": after["programme"].rigs_required,
            "proposal_n": boq_optimiser.optimise(after["programme"], after["model"]).proposal_n,
            "total": after["priced"].total,
        },
        "problems": model.problems(),
    }


# ---------------------------------------------------------------------------
# Conditions — a sentence somebody wrote down, mapped onto a knob by proposal
# ---------------------------------------------------------------------------
@router.get("/costing/{set_id}/log")
def get_site_log(set_id: str) -> dict:
    """Every grounded discussion on this tender, oldest first. A pure read.

    Memory, not authority: nothing prices from this, and each entry still carries its `stripped`
    list — a discussion that lost a citation on the way through reads that way here too.
    """
    conn = store.get_conn()
    try:
        entries = store.load_site_log(conn, set_id)
        conditions = store.load_conditions(conn, set_id)
    finally:
        conn.close()
    born: dict[int, dict] = {}
    for row in conditions:
        # First condition per discussion wins the link — rowid order, so it is the one recorded
        # closest to the exchange. The STATUS travels with it: a discussion whose condition was
        # later rejected must not keep wearing a green badge.
        if row.get("born_of_seq") and row["born_of_seq"] not in born:
            born[row["born_of_seq"]] = row
    for entry in entries:
        # The forward link: which discussion went on to become a recorded condition. Derived at
        # read time from the conditions' own provenance, never stored twice.
        link = born.get(entry["seq"])
        entry["became_condition"] = link["condition_id"] if link else ""
        entry["became_status"] = (link.get("status") or "") if link else ""
    return {"set_id": set_id, "count": len(entries), "entries": entries}


@router.get("/costing/{set_id}/conditions")
def get_conditions(set_id: str) -> dict:
    """Every condition on this tender. Nothing is filtered — an unmapped one has to stay visible."""
    conn = store.get_conn()
    try:
        rows = store.load_conditions(conn, set_id)
    finally:
        conn.close()
    return {"set_id": set_id, "conditions": rows,
            "unmapped": sum(1 for r in rows if not r["proposed_path"] and not r["status"]),
            "undecided": sum(1 for r in rows if not r["status"])}


@router.post("/costing/conditions")
def post_condition(req: ConditionRequest, actor: str = Depends(_actor)) -> dict:
    """Write a condition down, and ask the model which knob it moves.

    ONE entry point for the form and the free notepad, because they are the same act: somebody has
    a sentence about this job that the engine has no field for. Recording it is unconditional — the
    row exists whether or not anything can be mapped. The mapping is a PROPOSAL and a person
    confirms it; nothing here writes the model or a verdict.
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="A condition needs some words in it.")
    condition_id = (req.condition_id or "").strip() or f"c-{abs(hash((req.set_id, text))) % 10**10}"

    conn = store.get_conn()
    try:
        stored = store.save_condition(conn, req.set_id, condition_id, text=text,
                                      note=req.note, actor=actor,
                                      born_of_seq=max(0, req.born_of_seq))
        parts = _costing_or_library(conn, req.set_id)
    finally:
        conn.close()

    proposal = _propose_condition_mapping(text, parts["model"], parts["context"])
    conn = store.get_conn()
    try:
        store.save_condition_proposal(
            conn, req.set_id, condition_id, path=proposal.path, value=proposal.value,
            basis=proposal.basis or proposal.cannot_map,
            source="; ".join(proposal.checked))
        stored = store.load_condition(conn, req.set_id, condition_id) or stored
    finally:
        conn.close()
    return {"set_id": req.set_id, "condition": stored,
            "proposal": proposal.model_dump(),
            "awaiting": ("your confirmation — nothing has been written to the model"
                         if proposal.maps else
                         "nothing to confirm: no single input carries this condition, so it stays "
                         "on the register unmapped and visible")}


@router.post("/costing/conditions/decide")
def post_condition_decision(req: ConditionDecisionRequest, actor: str = Depends(_actor)) -> dict:
    """Confirm or reject a proposed mapping. **The ONLY thing that writes the model from here.**

    Confirming writes the proposed input (or a number the person typed instead, which is the point
    of confirming rather than accepting) through the same copy-on-write path every model edit uses.
    Rejecting records the refusal and leaves the condition on the register, unpriced and visible.
    """
    if req.status not in {"confirmed", "rejected", ""}:
        raise HTTPException(status_code=422,
                            detail=f"{req.status!r} is not a verdict — confirmed, rejected, or "
                                   f"blank for back to undecided.")
    conn = store.get_conn()
    try:
        condition = store.load_condition(conn, req.set_id, req.condition_id)
        if condition is None:
            raise HTTPException(status_code=404,
                                detail=f"No condition {req.condition_id!r} on this tender.")
        applied: Optional[float] = None
        if req.status == "confirmed":
            path = condition["proposed_path"]
            value = req.value if req.value is not None else condition["proposed_value"]
            if not path or value is None:
                raise HTTPException(
                    status_code=422,
                    detail="There is no mapping to confirm on this condition. It stays recorded "
                           "and unpriced, which is the honest state — a condition with no knob "
                           "behind it is a real thing.")
            bill = _bill_or_404(conn, req.set_id, None)
            parts = _costing(conn, req.set_id, bill.rev)
            model = parts["model"].model_copy(deep=True)
            _apply_model_path(model, path, float(value))
            store.save_set_model(conn, req.set_id, model, actor=actor)
            applied = float(value)
        store.decide_condition(conn, req.set_id, req.condition_id, status=req.status,
                               actor=actor, applied_value=applied)
        store.touch_set(conn, req.set_id, actor)
        fresh = store.load_condition(conn, req.set_id, req.condition_id)
    finally:
        conn.close()
    return {"set_id": req.set_id, "condition": fresh, "applied": applied, "by": actor}


@router.delete("/costing/{set_id}/conditions/{condition_id}")
def delete_condition_row(set_id: str, condition_id: str, actor: str = Depends(_actor)) -> dict:
    """Remove a condition. It does NOT unwind a confirmed mapping — that number is now the model's,
    and silently reverting it would be an edit nobody made. Change it on the register instead."""
    conn = store.get_conn()
    try:
        existing = store.load_condition(conn, set_id, condition_id)
        store.delete_condition(conn, set_id, condition_id)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    applied = bool(existing and existing.get("applied_value") is not None)
    return {"set_id": set_id, "condition_id": condition_id, "deleted": True,
            "note": ("The condition is gone. The model value it set is NOT reverted — it is the "
                     "model's number now, and undoing it silently would be an edit nobody made."
                     if applied else "The condition is gone. It had written nothing.")}


def _costing_or_library(conn, set_id: str) -> dict:
    """The model in force for a tender, plus what is known about the tender, for a mapping call.

    A condition can be written down before a bill is imported, so this falls back to the library's
    model rather than 404ing — the knobs are the same either way, and refusing to record a
    condition because a spreadsheet has not arrived would put it back in a notebook.
    """
    context_lines: list[str] = []
    try:
        bill = _bill_or_404(conn, set_id, None)
        parts = _costing(conn, set_id, bill.rev)
        model = parts["model"]
        programme = parts["programme"]
        context_lines.append(
            f"Rock fraction {programme.rock_fraction:.1%}; {programme.work_days:,.0f} work-days "
            f"at P50; {programme.rigs_required} rig(s) required.")
    except HTTPException:
        model = store.load_library_model(conn)
        context_lines.append("No bill of quantities is imported yet, so nothing is derived from "
                             "one. The inputs below are the company's defaults.")
    meta = store.load_set_meta(conn, set_id)
    if meta and meta.get("package"):
        context_lines.append(f"Package: {meta['package']}")
    return {"model": model, "context": "\n".join(context_lines)}


def _propose_condition_mapping(text: str, model: boq_model.CostingModel, context: str):
    """Ask the model which knob a condition moves. Always returns a proposal — never raises.

    A mapping call that fails must not lose the condition. The row is already stored by the time
    this runs, so an unreachable provider degrades to "unmapped, and here is why", which is a state
    the register already knows how to show.
    """
    from client_boq import llm as llm_mod

    client = llm_mod.make_client()
    try:
        raw = client.complete_json(
            system=boq_conditions.SYSTEM,
            user=boq_conditions.prompt_for(text, model, context=context),
            target_model=boq_conditions.RawConditionMapping,
            demo_fixture=boq_conditions.DEMO_FIXTURE, purpose="client_boq-condition-map",
        )
    except Exception as exc:                                    # provider, parse, budget
        return boq_conditions.ConditionProposal(
            cannot_map=f"the mapping call did not come back: {exc}",
            checked=["the condition is recorded either way — it is on the register, unmapped"])
    return boq_conditions.validate(
        raw.model_dump() if isinstance(raw, boq_conditions.RawConditionMapping) else
        (raw if isinstance(raw, dict) else {}), model)


# ---------------------------------------------------------------------------
# Site photographs, and asking a question about one tender
# ---------------------------------------------------------------------------
@router.get("/site/{set_id}/photos")
def get_site_photos(set_id: str) -> dict:
    """Every photograph on this tender. The index; the bytes come from the file route below."""
    conn = store.get_conn()
    try:
        rows = store.load_site_photos(conn, set_id)
    finally:
        conn.close()
    return {"set_id": set_id, "photos": rows, "count": len(rows)}


@router.post("/site/photos")
async def post_site_photo(set_id: str = Form(...), caption: str = Form(""),
                          station: str = Form(""), file: UploadFile = File(...),
                          actor: str = Depends(_actor)) -> dict:
    """Upload one site photograph.

    The caption and the station are the PHOTOGRAPHER's — neither is read off the image. A model
    guessing which hole a picture is of would attach real evidence to the wrong location, which is
    worse than a picture with no location at all.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="That file is empty.")
    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=422,
            detail=f"{file.filename!r} is {content_type or 'of unknown type'}, not an image. Site "
                   f"photographs are read with vision; a document belongs on the Documents step.")

    workspace = Workspace()
    photo_id = f"p-{abs(hash((set_id, file.filename, len(data)))) % 10**10}"
    # `safe_relative_path` is the guard the workspace already keeps against a filename that walks
    # out of the tender's directory; the photo id in front of it also stops two files with the same
    # name from overwriting each other.
    relative = safe_relative_path(f"site_photos/{photo_id}-{file.filename or 'photo'}").as_posix()
    workspace.save_upload_at(set_id, relative, data)
    conn = store.get_conn()
    try:
        row = store.save_site_photo(conn, set_id, photo_id, filename=file.filename or photo_id,
                                    rel_path=relative, content_type=content_type,
                                    caption=caption, station=station, actor=actor)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {"set_id": set_id, "photo": row}


@router.get("/site/{set_id}/photos/{photo_id}/file")
def get_site_photo_file(set_id: str, photo_id: str) -> Response:
    conn = store.get_conn()
    try:
        row = store.load_site_photo(conn, set_id, photo_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No photograph {photo_id!r} on this tender.")
    path = Workspace().docs_dir(set_id) / row["rel_path"]
    if not path.is_file():
        raise HTTPException(
            status_code=410,
            detail="The row is here but the file is not. Uploads live on local disk; losing the "
                   "disk loses the picture, and nothing else in this app knows that happened.")
    return Response(content=path.read_bytes(),
                    media_type=row["content_type"] or "image/jpeg")


@router.delete("/site/{set_id}/photos/{photo_id}")
def delete_site_photo_row(set_id: str, photo_id: str, actor: str = Depends(_actor)) -> dict:
    conn = store.get_conn()
    try:
        store.delete_site_photo(conn, set_id, photo_id)
        store.touch_set(conn, set_id, actor)
    finally:
        conn.close()
    return {"set_id": set_id, "photo_id": photo_id, "deleted": True,
            "note": "Any condition already recorded from this photograph stays — it is a decision "
                    "somebody made, not a property of the file."}


@router.post("/site/{set_id}/photos/read")
def post_read_site_photos(set_id: str) -> dict:
    """Read the photographs with vision, alongside the schedule and the reports.

    Produces OBSERVATIONS, each naming the photograph it came from. Never an access class, never a
    cost — see `boq/photos.py`. A kept observation becomes a condition through the ordinary
    propose-and-confirm path, so a human is in the loop twice before any number moves.

    The images are counted and loaded FIRST, in every mode. `s02_interpret` was once burned by
    returning its DEMO fixture before checking whether the input was readable, so a scanned page
    came back with a confident summary of pages nobody had seen. No photographs means no
    observations and a stated reason, fixture or not.
    """
    from client_boq import llm as llm_mod

    conn = store.get_conn()
    try:
        rows = store.load_site_photos(conn, set_id)
        schedule, _meta = store.load_station_schedule(conn, set_id)
    finally:
        conn.close()

    workspace = Workspace()
    images: list[str] = []
    names: list[str] = []
    missing: list[str] = []
    for row in rows:
        path = workspace.docs_dir(set_id) / row["rel_path"]
        if not path.is_file():
            missing.append(row["filename"])
            continue
        images.append(base64.b64encode(path.read_bytes()).decode("ascii"))
        names.append(row["filename"])

    if not images:
        return {"set_id": set_id, "observations": [], "photos_read": [],
                "could_not_see": "", "problems": (
                    [f"{len(missing)} photograph(s) are indexed but their files are gone: "
                     f"{', '.join(missing)}"] if missing else []),
                "waiting_on": "no photographs have been uploaded, so there is nothing to look at"}

    stations = ""
    if schedule is not None:
        stations = "\n".join(
            f"{s.station}: soil {s.soil_m:g} m + rock {s.rock_m:g} m"
            + (f", sheet {s.sheet}" if s.sheet else "")
            for s in schedule.stations[:120])
    captions = "\n".join(f"{row['filename']}: {row['caption']}"
                         + (f" (station {row['station']})" if row["station"] else "")
                         for row in rows if row["caption"] or row["station"])

    client = llm_mod.make_client()
    try:
        raw = client.complete_json(
            system=boq_photos.SYSTEM,
            user=boq_photos.prompt_for(stations=stations, reports=captions, photos=names),
            images=images, target_model=_RawPhotoRead,
            demo_fixture=boq_photos.DEMO_FIXTURE, purpose="client_boq-site-photos",
        )
    except Exception as exc:
        return {"set_id": set_id, "observations": [], "photos_read": names, "could_not_see": "",
                "problems": [f"the reading call did not come back: {exc}"]}

    read = boq_photos.validate(raw.model_dump() if hasattr(raw, "model_dump") else (raw or {}),
                              available=names)
    if missing:
        read.problems.append(
            f"{len(missing)} photograph(s) are indexed but their files are gone and were NOT read: "
            f"{', '.join(missing)}")
    payload = read.model_dump()
    # What each observation would say if somebody keeps it — computed here so the screen does not
    # have to reconstruct the sentence, and so the same words reach the register every time.
    payload["observations"] = [
        {**o, "as_condition": boq_photos.as_condition_text(boq_photos.Observation(**o))}
        for o in payload["observations"]]
    return {"set_id": set_id, **payload}


class _RawPhotoRead(models.NullTolerant):
    """Exactly what the vision call is asked for. It does not get to write `problems`."""

    observations: list[dict] = Field(default_factory=list)
    could_not_see: str = ""


class AskRequest(BaseModel):
    set_id: str
    question: str


@router.post("/costing/ask")
def post_ask(req: AskRequest, actor: str = Depends(_actor)) -> dict:
    """Ask a question about one tender, grounded in its own documents and its own numbers.

    The answer is constrained BY ITS SHAPE (see `boq/ask.py`): it may quote a figure the engine
    computed, it may not invent one, every claim carries a citation validated against the ground
    actually supplied, and a citation to something that was not supplied is stripped and reported.
    The only thing it may suggest doing is recording a condition — which then goes through the
    ordinary propose-and-confirm path like any other.
    """
    from client_boq import llm as llm_mod

    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="Ask something.")

    conn = store.get_conn()
    try:
        ground = _ground_for(conn, req.set_id)
    finally:
        conn.close()
    if not ground.sources:
        # The SAME keys as the grounded path, so the response type is one shape, not two. The
        # exchange is deliberately not logged (an exchange grounded on nothing is not a
        # discussion worth remembering), and `log_seq: 0` says so — seq is 1-based on purpose.
        return {"set_id": req.set_id, "question": question, "answer": "",
                "cannot_answer": "nothing has been read for this tender yet — no documents, no "
                                 "bill, no schedule — so there is nothing to ground an answer in",
                "citations": [], "figures_used": [], "figures": {}, "proposes": "",
                "stripped": [], "log_seq": 0, "asked_by": actor, "grounded_in": []}

    client = llm_mod.make_client()
    try:
        raw = client.complete_json(
            system=boq_ask.SYSTEM,
            user=f"{ground.as_prompt()}\n\nTHE QUESTION:\n{question}",
            target_model=boq_ask.RawAnswer,
            demo_fixture=boq_ask.DEMO_FIXTURE, purpose="client_boq-ask",
        )
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"the answer did not come back: {exc}") from exc

    answer = boq_ask.validate(raw.model_dump() if hasattr(raw, "model_dump") else (raw or {}),
                              ground)
    payload = {**answer.model_dump(),
               "figures": {k: ground.figures[k] for k in answer.figures_used}}
    # PERSISTED, with who asked and when. The exchange used to live only in this response, so a
    # discussion that decided something real was gone on refresh, a later question could not see
    # it, and a condition born of it could not say so. The log stores the VALIDATED answer — the
    # type with no field for a rate or a verdict — so memory can never hold more authority than
    # the reply did.
    conn = store.get_conn()
    try:
        log_seq = store.save_ask_exchange(conn, req.set_id, question=question,
                                          payload=payload, actor=actor)
    finally:
        conn.close()
    return {"set_id": req.set_id, "question": question, **payload,
            "log_seq": log_seq, "asked_by": actor,
            "grounded_in": sorted(ground.sources)}


def _ground_for(conn, set_id: str) -> "boq_ask.Ground":
    """Assemble what an answer is allowed to rest on. Deterministic — no model call anywhere here.

    Now a delegation: the assembly lives in `client_boq/ground.py` (the whole-tender ground,
    plan Phase 4 layer 1) so the chat and the brain read the SAME ground — a fact one can see is
    never invisible to the other. The engine-derived block is injected because `_costing` is the
    router's single whole-engine path and the ground module must not import the router.
    """
    from client_boq import ground as ground_mod

    try:
        bill = _bill_or_404(conn, set_id, None)
        costing = _costing(conn, set_id, bill.rev)
    except HTTPException:
        costing = None
    return ground_mod.assemble(conn, set_id, costing=costing)


# ---------------------------------------------------------------------------
# The brain — reads everything, proposes, never disposes (plan Phase 4)
# ---------------------------------------------------------------------------
class BrainRunRequest(BaseModel):
    set_id: str


def _brain_grounds(set_id: str) -> tuple["boq_ask.Ground", dict]:
    """The full ground and the per-read slices, on one connection, closed before any model call
    (the post_ask pattern — a 17-minute run must not hold SQLite's single writer)."""
    from client_boq import brain as brain_mod
    from client_boq import ground as ground_mod

    conn = store.get_conn()
    try:
        try:
            bill = _bill_or_404(conn, set_id, None)
            costing = _costing(conn, set_id, bill.rev)
        except HTTPException:
            costing = None
        full = ground_mod.assemble(conn, set_id, costing=costing)
        slices = {name: ground_mod.assemble(conn, set_id, costing=costing, families=fams)
                  for name, fams in brain_mod.READ_SLICES.items()}
    finally:
        conn.close()
    return full, slices


def _run_brain(set_id: str, *, actor: str = "", progress=None) -> dict:
    """The orchestration: focused reads over narrow slices, then one synthesis over everything.
    Every model call carries a fixture (DEMO stays offline); the output is VALIDATED before it is
    stored — an invented action or an ungrounded citation is stripped and named, never kept."""
    from client_boq import brain as brain_mod
    from client_boq import llm as llm_mod

    tell = progress or (lambda stage: None)
    full, slices = _brain_grounds(set_id)
    if not full.sources:
        raise ValueError("nothing has been read for this tender yet — no documents, no bill, "
                         "no schedule — so there is nothing for the brain to understand")

    client = llm_mod.make_client(stage=llm_mod.STAGE_BRAIN)
    tell("reading")
    findings: dict = {}
    for name, slice_ground in slices.items():
        if not slice_ground.sources:
            continue  # an empty slice is not a read — nothing to find in nothing
        findings[name] = client.complete_json(
            system=brain_mod.READ_SYSTEM,
            user=f"{slice_ground.as_prompt()}\n\nReport your findings.",
            target_model=brain_mod.RawFindings,
            demo_fixture=brain_mod.READ_FIXTURES[name],
            purpose=f"client_boq-brain-read-{name}",
        )

    tell("proposing")
    raw = client.complete_json(
        system=brain_mod.SYNTH_SYSTEM,
        user=brain_mod.synthesis_user(full, findings),
        target_model=brain_mod.RawBriefing,
        demo_fixture=brain_mod.SYNTH_FIXTURE,
        purpose="client_boq-brain-briefing",
    )
    briefing = brain_mod.validate(
        raw.model_dump() if hasattr(raw, "model_dump") else (raw or {}), full)
    briefing.reads = [f"{name}: {len(f.findings)} finding(s)" for name, f in findings.items()]

    conn = store.get_conn()
    try:
        seq = store.save_briefing(conn, set_id, briefing.model_dump(), actor=actor)
    finally:
        conn.close()
    return {"set_id": set_id, "seq": seq, **briefing.model_dump()}


def _run_brain_job(job_id: str, set_id: str, actor: str = "") -> None:
    try:
        _begin(job_id, "grounding")
        result = _run_brain(set_id, actor=actor, progress=_stage_cb(job_id, "brain"))
        jobs.JOBS.update(job_id, status="done", stage="proposing", result=result)
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except Exception as exc:
        jobs.JOBS.update(job_id, status="error", error=str(exc))


@router.post("/brain/run")
def post_brain_run(req: BrainRunRequest, actor: str = Depends(_actor)) -> JobState:
    """Run the brain over this tender. Propose-only by construction: the output's raw model has
    no field for a verdict, a number or a gate flag, and every proposed action is a reference to
    a screen — the gated endpoint behind it still takes a human click."""
    full, _slices = _brain_grounds(req.set_id)
    if not full.sources:
        raise HTTPException(
            status_code=409,
            detail="nothing has been read for this tender yet — no documents, no bill, no "
                   "schedule — so there is nothing for the brain to understand. Read something "
                   "in first.")
    live = jobs.JOBS.live_for("brain", req.set_id)
    if live:
        raise HTTPException(status_code=409,
                            detail=f"a brain run is already in flight for this tender "
                                   f"(job {live}). Adopt it rather than starting another.")
    from pipeline.llm_client import demo_mode

    if demo_mode():
        result = _run_brain(req.set_id, actor=actor)
        return JobState(kind="brain", status="done", stage="proposing", result=result)
    job_id = jobs.JOBS.create("brain", set_id=req.set_id)
    jobs.POOL.submit(_run_brain_job, job_id, req.set_id, actor)
    return JobState(job_id=job_id, kind="brain", status="queued", stage="grounding")


@router.get("/brain/status/{job_id}")
def get_brain_status(job_id: str) -> JobState:
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired client_boq job.")
    return _job_state(job_id, job)


@router.get("/brain/{set_id}")
def get_briefing(set_id: str) -> dict:
    """The latest briefing, or what running one would need. A pure read — rendering a briefing
    changes nothing, and the actions on it are navigation, not execution."""
    conn = store.get_conn()
    try:
        briefing = store.load_briefing(conn, set_id)
        count = store.briefing_count(conn, set_id)
    finally:
        conn.close()
    if briefing is None:
        return {"set_id": set_id, "briefing": None, "count": 0,
                "waiting_on": "the brain has not run on this tender yet"}
    return {"set_id": set_id, "briefing": briefing, "count": count, "waiting_on": ""}


@router.get("/costing/{set_id}/workbook.xlsx")
def get_costing_workbook(set_id: str, rev: Optional[int] = None) -> Response:
    """The deliverable: eight sheets **with their formulas intact**.

    Not a report. Change a blue cell on 01 Inputs and every rate on 05 recalculates in Excel, with
    the app switched off — which is also the honest answer to "what if I want to do something the
    engine cannot".
    """
    conn = store.get_conn()
    try:
        parts = _costing(conn, set_id, rev)
        meta = store.load_set_meta(conn, set_id)
    finally:
        conn.close()

    # Empty when the tender conserves, a sentence when it does not. Read from the single owner of
    # that verdict rather than recomputed — the screen, the approval and this file must not be able
    # to disagree about whether the money comes out the other side.
    balance = parts["conservation"]
    conservation_note = "" if balance.clean() else balance.headline()
    xlsx = boq_costing_workbook.build_workbook(
        parts["model"], parts["programme"], parts["spread"], parts["buildup"],
        parts["priced"], parts["register"],
        contract_reference=meta.get("client", "") or set_id,
        conservation=conservation_note)
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="costing_{set_id}_rev{parts["bill"].rev}.xlsx"'},
    )
