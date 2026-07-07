"""Persist a tender's canonical scope split so a later stage can read it back.

The ingest split (:class:`ScopePackages`) is returned to the client at ``/ingest-upload`` but,
until now, was never persisted server-side — so the inbound-reply loop had no canonical SoR items
to match a returned line against, and fell back to stamping every line with the enquiry's trade.

This module gives the scope a deterministic per-tender home (``artifacts/scope.json`` via
:meth:`Workspace.scope_path`) and a loader that returns it (or ``None`` when a tender predates
this persistence, so the reply loop degrades to the old ref-trade behaviour). Pure JSON — no
network, no model; the demo path returns its scope inline and never writes here.
"""

from __future__ import annotations

from typing import Optional

from pipeline.workspace import Workspace
from schemas.models import ScopePackages


def save_scope(ws: Workspace, tender_id: str, scope: ScopePackages) -> None:
    """Persist the tender's canonical scope split (its ``ScopePackages``) under ``tender_id``."""
    path = ws.scope_path(tender_id, create=True)
    path.write_text(scope.model_dump_json(indent=2), encoding="utf-8")


def load_scope(ws: Workspace, tender_id: str) -> Optional[ScopePackages]:
    """The tender's persisted canonical scope, or ``None`` when absent / unreadable (an older
    tender, or a demo run that never persisted one) — the caller then keeps the ref-trade path."""
    path = ws.scope_path(tender_id)
    if not path.is_file():
        return None
    try:
        return ScopePackages.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
