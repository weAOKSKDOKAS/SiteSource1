"""The bridge's FastAPI surface, mounted at ``/bridge``.

One tender, carried from an approved client_boq review through a human bill-part confirmation and
a scope split, into the procurement routing fork. Every handler is sync ``def`` — the heavy ones
(pdf reads, the scope split) must not block the event loop.

The set is addressed by ``set_id``, which IS the procurement ``run_ref`` (see ``identity.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
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
