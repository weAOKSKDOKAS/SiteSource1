"""The bridge's FastAPI surface, mounted at ``/bridge``.

One tender, carried from an approved client_boq review through a human bill-part confirmation and
a scope split, into the procurement routing fork. Every handler is sync ``def`` — the heavy ones
(pdf reads, the scope split) must not block the event loop.

The set is addressed by ``set_id``, which IS the procurement ``run_ref`` (see ``identity.py``).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/bridge", tags=["bridge"])


class ConfirmBillPartsRequest(BaseModel):
    """The human's chosen SET of bill parts — several are legitimate (a BQ plus a daywork
    schedule), so this is a list, not one id."""

    part_ids: list[str] = Field(default_factory=list)


class BridgeRouteDecision(BaseModel):
    package_key: str
    chosen_route: str  # self_perform | sublet


class ConfirmBridgeRoutesRequest(BaseModel):
    decisions: list[BridgeRouteDecision] = Field(default_factory=list)
    decided_by: str = "operator"


@router.get("/{set_id}/bq-candidates")
def get_bq_candidates(set_id: str) -> dict:
    """Every part in the set, with which one(s) are proposed as the bill. Never auto-selects."""
    raise NotImplementedError("GET /bridge/{set_id}/bq-candidates: list parts, propose the pricing ones")


@router.post("/{set_id}/bq-part")
def post_bq_part(set_id: str, req: ConfirmBillPartsRequest) -> dict:
    """The human confirms which part(s) are the bill — the gate before any priced row exists."""
    raise NotImplementedError("POST /bridge/{set_id}/bq-part: persist the confirmed bill-part set")


@router.post("/{set_id}/scope")
def post_scope(set_id: str) -> dict:
    """Run the scope split over the confirmed bill parts, persist it, and return it."""
    raise NotImplementedError("POST /bridge/{set_id}/scope: run and persist the scope split")


@router.get("/{set_id}/scope")
def get_scope(set_id: str) -> dict:
    """The persisted scope split for this set."""
    raise NotImplementedError("GET /bridge/{set_id}/scope: return the persisted scope split")


@router.post("/{set_id}/route/analyze")
def post_route_analyze(set_id: str) -> dict:
    """Propose a route per package — 409s until the client_boq review register is approved."""
    raise NotImplementedError(
        "POST /bridge/{set_id}/route/analyze: 409 until review approved, then propose routes"
    )


@router.post("/{set_id}/route/confirm")
def post_route_confirm(set_id: str, req: ConfirmBridgeRoutesRequest) -> dict:
    """The Layer-4 gate: record the human's routes. Seeds no estimate on either side."""
    raise NotImplementedError(
        "POST /bridge/{set_id}/route/confirm: persist decisions, return the splits, seed nothing"
    )
