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


class FinalApprovalRequest(BaseModel):
    verdict: str                              # 'approve' | 'revise'
    rationale: str = ""                       # required for 'revise' — what to correct
    approved_by: str = "operator"


class SubmitRequest(BaseModel):
    proof: str = ""                           # portal ref / filename — stored verbatim, never invented
    submitted_by: str = "operator"


class OutcomeRequest(BaseModel):
    status: str                               # submitted | won | lost | withdrawn
    notes: str = ""                           # human — award value, competitor, why
    decided_by: str = "operator"


class LessonRequest(BaseModel):
    category: str = "other"                   # pricing | scope | programme | commercial | other
    lesson: str                               # human-authored


class PostSubmissionRequest(BaseModel):
    kind: str = "note"                        # clarification | negotiation | change | note
    detail: str                               # human-stated


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

    **A JOB on the live path, inline in DEMO** — the shape ``/ingest/split`` already uses. This
    reads every part's pdf, runs the extraction and indexes every document; on the real pack that
    is ~170 documents and minutes of work. Sync ``def`` kept the event loop free, so the server
    stayed up and the only symptom was one request that never came back — no progress, no stage,
    no way to stop it.

    DEMO has nothing to wait for (no model call, fixtures on disk), so it answers directly and the
    caller gets the finished payload in one round trip.

    Live returns the job envelope; poll ``/client-boq/ingest/status/{job_id}`` and stop it with
    ``/client-boq/jobs/{job_id}/cancel`` — one job store, so the existing endpoints already serve
    this without a second poll route to keep in step. **The finished ``result`` is byte-for-byte
    the dict this used to return**: set_id, scope, unrecognised_items, notes.
    """
    from pipeline.llm_client import demo_mode

    from bridge import scope as scope_mod

    if demo_mode():
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

    from client_boq import jobs

    from bridge.scope_job import run_scope_split_job

    # One split per set at a time. A second would index the same ~170 documents concurrently on a
    # two-wide pool and overwrite the first's scope — refused rather than queued, the same ruling
    # the review runs under.
    live = jobs.JOBS.live_for("scope_split", set_id)
    if live:
        raise HTTPException(
            status_code=409,
            detail=(f"A scope split is already running for set {set_id!r} (job {live}). A second "
                    "would overwrite the first's split, so it was refused rather than queued. "
                    "Wait for it, or cancel it and start again."),
        )
    # `scope_split`, NOT `scope`: `/client-boq/estimate/scope` already owns the kind `scope`, and
    # `live_for` is keyed on it — sharing the name would have each workflow refuse the other with a
    # 409 naming a job the operator never started.
    job_id = jobs.JOBS.create("scope_split", set_id=set_id)
    jobs.POOL.submit(run_scope_split_job, job_id, set_id)
    return {"job_id": job_id, "kind": "scope_split", "status": "queued", "stage": "reading"}


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


class ShortlistRequest(BaseModel):
    """The computed shortlist for this set, as the screen received it."""

    shortlist: dict = Field(default_factory=dict)


@router.get("/{set_id}/shortlist")
def get_shortlist(set_id: str) -> dict:
    """The stored shortlist for this set — ``shortlist: null`` when it has never been run.

    A pure read, and never a 404: "not run yet" is a state the screen renders normally, the same
    reasoning as ``/route/proposal`` returning an empty list rather than 404ing.
    """
    from bridge import shortlist_store

    body, created_at = shortlist_store.load_shortlist(set_id)
    return {"set_id": set_id, "shortlist": body, "created_at": created_at}


@router.post("/{set_id}/shortlist")
def post_shortlist(set_id: str, req: ShortlistRequest) -> dict:
    """Store the computed shortlist so a refresh does not throw away a 148-firm screen.

    **This is not the dispatch gate and not an approval.** It records the CANDIDATES, which are a
    deterministic Layer-1 answer, so the ticks made against them have something to be restored
    onto. Nothing is composed, drafted or sent, and no selection is implied by storing a list.
    """
    from bridge import shortlist_store

    shortlist_store.save_shortlist(set_id, req.shortlist)
    return {"set_id": set_id, "stored": bool(req.shortlist)}


@router.get("/{set_id}/doc-index")
def get_doc_index_state(set_id: str) -> dict:
    """Does a document index exist for this tender, when was it built, and over how many documents.

    A pure read, and the gate's precondition made visible. The last live failure was a split run
    under one slug and drafts assembled under another: `load_doc_index` returned `[]`, the enquiry
    carried a generated workbook instead of the sliced bill, and nothing said so until it had been
    sent. Never 404s — "no index" is the answer this exists to give, and the loudest one it has.
    """
    from bridge.doc_index_state import doc_index_state

    return doc_index_state(set_id)


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
# The back of the funnel — final approval, then submission (nodes 46–48)
# ---------------------------------------------------------------------------
@router.post("/{set_id}/final-approval")
def post_final_approval(set_id: str, req: FinalApprovalRequest) -> dict:
    """The tender's last human gate: ``approve`` or ``revise``. Mirrors ``/route/confirm`` — the
    verdict is the human's, recorded and nothing else. A ``revise`` must say what to correct."""
    from bridge import submission

    try:
        return submission.confirm_final_approval(
            set_id, req.verdict, req.rationale, approved_by=req.approved_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{set_id}/submit")
def post_submit(set_id: str, req: SubmitRequest) -> dict:
    """Freeze the offer and record the submission. Refused (409) unless a final ``approve`` exists —
    a hard precondition, named in the message."""
    from bridge import submission

    try:
        return submission.record_submission(set_id, proof=req.proof, submitted_by=req.submitted_by)
    except submission.NotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{set_id}/submission")
def get_submission(set_id: str) -> dict:
    """Approval + submission + deadline + whether a letter exists to submit — a pure read. Every
    field is a state; nothing here 404s."""
    from bridge import submission

    try:
        return submission.submission_state(set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Closeout — outcome, lessons, change-control, corpus feedback, handover (nodes 49–53)
# ---------------------------------------------------------------------------
@router.post("/{set_id}/outcome")
def post_outcome(set_id: str, req: OutcomeRequest) -> dict:
    """Record the tender outcome (did WE win — NOT the sublet award). A ``won``/``lost`` outcome
    also feeds the benchmark corpus; the feed result rides back under ``corpus``."""
    from bridge import closeout

    try:
        outcome = closeout.set_outcome(set_id, req.status, req.notes, decided_by=req.decided_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    corpus = closeout.feed_outcome_to_corpus(set_id)  # no-op for submitted/withdrawn
    return {"outcome": outcome, "corpus": corpus}


@router.post("/{set_id}/lessons")
def post_lesson(set_id: str, req: LessonRequest) -> dict:
    """Add one human-authored lesson. 400 on an empty note."""
    from bridge import closeout

    try:
        return closeout.add_lesson(set_id, req.category, req.lesson)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{set_id}/lessons")
def get_lessons(set_id: str) -> dict:
    from bridge import closeout

    return {"set_id": set_id, "lessons": closeout.list_lessons(set_id)}


@router.post("/{set_id}/post-submission")
def post_post_submission(set_id: str, req: PostSubmissionRequest) -> dict:
    """Append one change-control entry. 400 on an empty detail."""
    from bridge import closeout

    try:
        return closeout.log_event(set_id, req.kind, req.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{set_id}/post-submission")
def get_post_submission(set_id: str) -> dict:
    from bridge import closeout

    return {"set_id": set_id, "events": closeout.list_events(set_id)}


@router.get("/{set_id}/closeout")
def get_closeout(set_id: str) -> dict:
    """Outcome + lessons + events + whether a handover is meaningful — the Closeout tab's one read."""
    from bridge import closeout

    try:
        return closeout.closeout_state(set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{set_id}/handover")
def get_handover(set_id: str) -> dict:
    """The assembled handover package — a read-only projection, meaningful once the tender is won."""
    from bridge import closeout

    try:
        return closeout.assemble_handover(set_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Which specification governs which bill section — proposed, then confirmed
# ---------------------------------------------------------------------------
class SpecMapConfirmation(BaseModel):
    """One bill section's decision. ``ps_section = ""`` is a decision, not a blank."""

    bill_section: str
    ps_section: str = ""
    bill_heading: str = ""
    ps_title: str = ""
    proposed_ps_section: str = ""
    proposed_confidence: str = ""


class SpecMapRequest(BaseModel):
    confirmations: list[SpecMapConfirmation] = Field(default_factory=list)


@router.get("/{set_id}/spec-map")
def get_spec_map(set_id: str) -> dict:
    """The proposed bill-section -> PS-section map, and whatever a person has confirmed.

    A pure read that computes the proposals fresh from the persisted scope and doc index — they are
    deterministic, so recomputing costs nothing and cannot drift from a stale copy. Nothing is
    written, and nothing is auto-confirmed: ``confirmed`` is exactly the rows a human decided, and a
    bill section absent from it is unmapped no matter how good its proposal looks.
    """
    from bridge import scope as scope_mod, spec_map as spec_map_mod
    from pipeline.stage_01_ingest.doc_index import load_doc_index
    from pipeline.stage_03_dispatch.spec_match import bill_headings_from_scope, propose_spec_map
    from pipeline.workspace import Workspace

    scope = scope_mod.load_scope(set_id)
    doc_index = load_doc_index(Workspace(), set_id)
    headings: dict[str, str] = {}
    for pkg in (scope.packages if scope else []):
        headings.update(bill_headings_from_scope(pkg))
    confirmed = spec_map_mod.load_spec_map(set_id)
    return {
        "set_id": set_id,
        "proposals": [p.model_dump() for p in propose_spec_map(headings, doc_index)],
        "confirmed": {k: v.model_dump() for k, v in confirmed.items()},
    }


@router.post("/{set_id}/spec-map")
def post_spec_map(set_id: str, req: SpecMapRequest,
                  x_cboq_actor: str = Header("")) -> dict:
    """The Layer-4 gate: record which specification section governs which bill section.

    THE ONLY WRITER of the map, and it writes only what it was given. A proposal is never persisted
    on the operator's behalf — an auto-confirmed match is the silent-wrong-specification failure the
    whole design exists to prevent, and it would be indistinguishable, later, from a decision.
    """
    from bridge import spec_map as spec_map_mod

    try:
        confirmed = spec_map_mod.save_spec_map(
            set_id, [c.model_dump() for c in req.confirmations],
            confirmed_by=x_cboq_actor.strip() or "operator")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"set_id": set_id, "confirmed": {k: v.model_dump() for k, v in confirmed.items()}}


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
