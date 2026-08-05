"""The bridge's FastAPI surface, mounted at ``/bridge``.

One tender, carried from an approved client_boq review through a human bill-part confirmation and
a scope split, into the procurement routing fork. Every handler is sync ``def`` — the heavy ones
(pdf reads, the scope split) must not block the event loop.

The set is addressed by ``set_id``, which IS the procurement ``run_ref`` (see ``identity.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/bridge", tags=["bridge"])


class ConfirmBillPartsRequest(BaseModel):
    """The human's chosen SET of bill parts — several are legitimate (a BQ plus a daywork
    schedule), so this is a list, not one id."""

    part_ids: list[str] = Field(default_factory=list)
    confirmed_by: str = "operator"


class BridgeRouteDecision(BaseModel):
    package_key: str
    chosen_route: str  # self_perform | sublet


class ConfirmBridgeRoutesRequest(BaseModel):
    decisions: list[BridgeRouteDecision] = Field(default_factory=list)
    decided_by: str = "operator"


@router.get("/{set_id}/bq-candidates")
def get_bq_candidates(set_id: str) -> dict:
    """Every part in the set, with which one(s) are proposed as the bill. Never auto-selects.

    Read-only: a GET registers nothing. A set with no parts returns 404 rather than an empty list
    that would read as "this tender has no documents".
    """
    from bridge import parts

    body = parts.bq_candidates(set_id)
    if not body["parts"]:
        raise HTTPException(status_code=404, detail=body["message"])
    return body


@router.post("/{set_id}/bq-part")
def post_bq_part(set_id: str, req: ConfirmBillPartsRequest) -> dict:
    """The human confirms which part(s) are the bill — the gate before any priced row exists."""
    from bridge import parts

    try:
        return parts.confirm_bill_parts(set_id, req.part_ids, confirmed_by=req.confirmed_by)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{set_id}/scope")
def post_scope(set_id: str) -> dict:
    """Run the scope split over the confirmed bill parts, persist it, and return it.

    Sync ``def`` on purpose: this reads pdfs and runs the extraction, and must not block the
    event loop. ``notes`` carries every honest-degradation message the split produced (an
    unreadable part, a quarantined item) — nothing is dropped quietly.
    """
    from bridge import scope as scope_mod

    notes: list[str] = []
    try:
        scope, unrecognised = scope_mod.scope_from_set(set_id, on_error=notes.append)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    scope_mod.save_scope(set_id, scope)
    return {
        "set_id": set_id,
        "scope": scope.model_dump(),
        "unrecognised_items": [u.model_dump() for u in unrecognised],
        "notes": notes,
    }


@router.get("/{set_id}/scope")
def get_scope(set_id: str) -> dict:
    """The persisted scope split for this set."""
    from bridge import scope as scope_mod

    scope = scope_mod.load_scope(set_id)
    if scope is None:
        raise HTTPException(
            status_code=404,
            detail=f"No scope split stored for set {set_id!r} — POST /bridge/{set_id}/scope first.",
        )
    return {"set_id": set_id, "scope": scope.model_dump()}


@router.post("/{set_id}/route/analyze")
def post_route_analyze(set_id: str) -> dict:
    """Propose a route per package — 409s until the client_boq review register is approved.

    Routing sits behind the review gate and both forks inherit it. An OPEN QUERY, by contrast,
    never blocks: the count rides on the response for a human to weigh.
    """
    from bridge import decisions

    notes: list[str] = []
    try:
        body = decisions.propose_routes(set_id, on_error=notes.append)
    except decisions.ReviewNotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**body, "notes": notes}


class ApprovalsRequest(BaseModel):
    """The operator's current shortlist selection for the packages this screen is showing.

    Replace semantics per package: a firm just DESELECTED must disappear, and an empty list means
    "none of them", which is a decision rather than an absence.
    """

    approvals: dict[str, list[str]] = Field(default_factory=dict)


@router.get("/{set_id}/approvals")
def get_approvals(set_id: str) -> dict:
    """The persisted shortlist selection — ``{package_key: [firm_id, …]}``.

    A pure read. An empty mapping is a state ("nothing selected yet"), never an error, so this
    does not 404 on a set nobody has shortlisted.
    """
    from bridge import approvals as approvals_mod

    return {"set_id": set_id, "approvals": approvals_mod.load_approvals(set_id)}


@router.post("/{set_id}/approvals")
def post_approvals(set_id: str, req: ApprovalsRequest,
                   x_cboq_actor: str = Header("")) -> dict:
    """Record the shortlist selection so a reload does not lose it.

    **This is not the dispatch gate.** Nothing is composed, drafted or sent here; the operator
    still presses Compose/Prepare on the Dispatch step and that decision is unchanged. Persisting a
    selection only stops it evaporating between the click and the decision — which is the same
    session-only loss that made Level & compare show nothing over six landed replies.
    """
    from bridge import approvals as approvals_mod

    return {
        "set_id": set_id,
        "approvals": approvals_mod.save_approvals(
            set_id, req.approvals, selected_by=x_cboq_actor.strip() or "operator"),
    }


@router.get("/{set_id}/route/proposal")
def get_route_proposal(set_id: str) -> dict:
    """The persisted route proposal — a pure read that never re-runs the analysis.

    The step chips have to know whether a proposal exists. POSTing analyze to find out would be a
    write and, live, a model call. A set with no proposal returns ``packages: []`` — "not yet run"
    is a state, not an error, so this never 404s.
    """
    from bridge import decisions

    return decisions.stored_proposal(set_id)


@router.get("/{set_id}/route/decisions")
def get_route_decisions(set_id: str) -> dict:
    """The persisted route decisions — a pure read. No decisions yet is ``decisions: []``."""
    from bridge import decisions

    return decisions.stored_decisions(set_id)


@router.post("/{set_id}/route/confirm")
def post_route_confirm(set_id: str, req: ConfirmBridgeRoutesRequest) -> dict:
    """The Layer-4 gate: record the human's routes. Seeds no estimate on either side.

    The procurement ``/route/confirm`` is not called and not changed: it seeds only when a
    ``scope`` is supplied, so it keeps working exactly as it does today and stays the sole writer
    of ``package_routes.chosen_route``.
    """
    from bridge import decisions

    try:
        return decisions.confirm_routes(
            set_id,
            {d.package_key: d.chosen_route for d in req.decisions},
            decided_by=req.decided_by,
        )
    except decisions.ReviewNotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# The archive: a whole tender pack, at constant memory
# ---------------------------------------------------------------------------
def _archive_path(ws, name: str):
    """Where the uploaded archive is kept between the proposal and the approval.

    In `artifacts/`, not `docs/`: `docs/` is what `run_split` reads as the set's documents, and a
    232 MB zip sitting among them would be read as one.
    """
    return ws.artifacts_dir(name, create=True) / "archive.zip"


@router.post("/archive/upload")
def post_archive_upload(
    file: UploadFile = File(...),
    project_name: str = Form(""),
) -> dict:
    """Receive a tender pack and PROPOSE a manifest from its folder tree. Extracts nothing.

    The upload streams to disk a chunk at a time — `.read()` here is what would materialise 232 MB,
    and Starlette has already spooled the body to a real file, so there is nothing to gain by it.
    The total UNCOMPRESSED size is then checked against the ceiling from the central directory,
    before any member is opened: that ordering is what makes it a zip-bomb guard rather than a
    limit discovered too late.

    The manifest is saved UNAPPROVED. The human approves it through the existing gate
    (`/client-boq/ingest/manifest/approve`), and `/bridge/archive/extract` does the rest — so a
    tender pack passes through exactly the gate a single PDF does.
    """
    from client_boq import store
    from pipeline.workspace import Workspace

    from bridge import archive

    name = (project_name or Path(file.filename or "tender pack").stem).strip() or "Tender pack"
    set_id = archive.set_id_for(name)
    ws = Workspace()
    target = _archive_path(ws, name)
    try:
        written = archive.stream_to(file.file, target)
        report = archive.read_tree(target)
        archive.check_size(report)
        manifest = archive.plan_manifest(report, set_id=set_id, source_name=file.filename or "archive.zip")
    except ValueError as exc:
        # A refused archive leaves nothing behind — an unusable 232 MB file in the workspace would
        # be the operator's problem to find and delete.
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=set_id, name=name, slug=set_id, status="inspected")
        store.save_manifest(conn, manifest)
        # Explicitly closed. `save_manifest` preserves the flag by design, and a new pack landing
        # on an existing tender must not inherit an approval given for a manifest nobody can see.
        store.approve_manifest(conn, set_id, False)
    finally:
        conn.close()

    return {
        "set_id": set_id,
        "name": name,
        "archive_bytes": written,
        "uncompressed_bytes": report.uncompressed_bytes,
        "entries": len(report.members),
        "content_files": len(report.content),
        "signature_files": len(report.signatures),
        "skipped_files": len(report.skipped),
        # Grouped, because a 203-row gate is a wall. The person is checking the SHAPE.
        "folders": archive.folder_summary(report),
        "tier_reason": manifest.tier_reason,
        "parts": len(manifest.parts),
        "manifest_approved": False,
    }


class ArchiveExtractRequest(BaseModel):
    set_id: str


@router.post("/archive/extract")
def post_archive_extract(req: ArchiveExtractRequest) -> dict:
    """Extract the approved pack. 409 until the manifest gate is passed.

    Runs as a job on the same pool, reporting through the same strip, stoppable with the same STOP
    — a 232 MB extraction is the longest-running operation in the product and must not be the one
    thing a person cannot see or interrupt.
    """
    from client_boq import jobs, store

    from bridge.archive_job import run_archive_extract_job

    conn = store.get_conn()
    try:
        approved = store.manifest_is_approved(conn, req.set_id)
        row = conn.execute(
            "SELECT name FROM client_boq_document_sets WHERE set_id = ?", (req.set_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No document set {req.set_id!r}.")
    if not approved:
        raise HTTPException(
            status_code=409,
            detail=("The split manifest for this pack is not approved yet. A tender pack passes "
                    "the same gate a single document does — approve it, then extract."),
        )
    job_id = jobs.JOBS.create("archive", set_id=req.set_id)
    jobs.POOL.submit(run_archive_extract_job, job_id, req.set_id, row["name"])
    return {"job_id": job_id, "kind": "archive", "status": "queued", "stage": "reading"}
