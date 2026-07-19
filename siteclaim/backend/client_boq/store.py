"""Persistence for the client_boq module — the ``client_boq_*`` tables and the Workspace artifacts.

Two homes, by design (a locked decision):

* **Workspace artifacts** (``artifacts/client_boq/parsed.json`` and ``register.json``) — a readable,
  per-tender file copy, reusing ``pipeline/workspace.py`` and its deterministic ``tender_slug``.
* **The ``client_boq_*`` tables** — the SOURCE OF TRUTH for the review→estimate gate. The register
  and its ``approved`` flag live here; the estimate gate check reads this, not the artifact file.

Everything is deterministic infra (no AI, no network beyond the local SQLite file). The DB connection
comes from the shared ``db.store.get_connection`` (honouring ``SITESOURCE_DB``); tables are created
lazily on first use via ``models.init_tables``.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from client_boq import models
from client_boq.models import (
    ContextSummary,
    DepartureRegister,
    Estimate,
    EstimateScope,
    ParsedDocumentSet,
    ScopeReviewResult,
)
from db import store as db_store
from pipeline.llm_client import demo_mode
from pipeline.workspace import Workspace


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def _demo_db_path() -> Path:
    """A gitignored scratch DB for DEMO runs — under the workspace out dir (``backend/fixtures/out/``,
    already gitignored), so a DEMO review never writes the committed ``sitesource.db`` (decision 4A)."""
    return Workspace().root.parent / "client_boq_demo.db"


def get_conn() -> sqlite3.Connection:
    """Open the DB the module's tables live in and ensure those tables exist (idempotent).

    Path: an explicit ``SITESOURCE_DB`` always wins (live, tests). Otherwise, in DEMO mode the module
    defaults to a gitignored scratch DB (decision 4A) so an offline demo leaves the committed
    ``sitesource.db`` byte-identical; live with no override uses the shared default DB as before.
    """
    if not os.getenv("SITESOURCE_DB", "").strip() and demo_mode():
        path = _demo_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            sqlite3.connect(str(path)).close()  # create the file so get_connection accepts it
        conn = db_store.get_connection(path)
    else:
        conn = db_store.get_connection()
    models.init_tables(conn)
    return conn


# ---------------------------------------------------------------------------
# Document set + parsed store + summary
# ---------------------------------------------------------------------------
def upsert_document_set(
    conn: sqlite3.Connection, *, set_id: str, name: str, slug: str, status: str,
    parsed_json: Optional[str] = None, summary_json: Optional[str] = None,
) -> None:
    """Create/update the document-set row. ``parsed_json``/``summary_json`` are only overwritten when
    provided (None leaves the stored value), so recording the summary never clobbers the parsed set."""
    conn.execute(
        """
        INSERT INTO client_boq_document_sets (set_id, name, slug, status, parsed_json, summary_json)
        VALUES (:set_id, :name, :slug, :status, COALESCE(:parsed, '{}'), COALESCE(:summary, '{}'))
        ON CONFLICT(set_id) DO UPDATE SET
            name = excluded.name,
            slug = excluded.slug,
            status = excluded.status,
            parsed_json = COALESCE(:parsed, client_boq_document_sets.parsed_json),
            summary_json = COALESCE(:summary, client_boq_document_sets.summary_json)
        """,
        {"set_id": set_id, "name": name, "slug": slug, "status": status,
         "parsed": parsed_json, "summary": summary_json},
    )
    conn.commit()


def load_parsed(conn: sqlite3.Connection, set_id: str) -> Optional[ParsedDocumentSet]:
    """The persisted parsed document set for ``set_id`` (tables copy), or None."""
    row = conn.execute(
        "SELECT parsed_json FROM client_boq_document_sets WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["parsed_json"] or row["parsed_json"] == "{}":
        return None
    return ParsedDocumentSet.model_validate_json(row["parsed_json"])


def load_summary(conn: sqlite3.Connection, set_id: str) -> Optional[ContextSummary]:
    """The persisted s02 commercial-risk summary for ``set_id``, or None."""
    row = conn.execute(
        "SELECT summary_json FROM client_boq_document_sets WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["summary_json"] or row["summary_json"] == "{}":
        return None
    return ContextSummary.model_validate_json(row["summary_json"])


# ---------------------------------------------------------------------------
# Register + the review→estimate gate
# ---------------------------------------------------------------------------
def save_register(conn: sqlite3.Connection, register: DepartureRegister) -> None:
    """Persist the register to the tables (source of truth). Preserves the existing ``approved`` flag
    — assembling/re-running the review never silently re-opens or closes the gate; only the approve
    endpoint moves it."""
    conn.execute(
        """
        INSERT INTO client_boq_review_registers (set_id, register_json)
        VALUES (:set_id, :json)
        ON CONFLICT(set_id) DO UPDATE SET register_json = excluded.register_json
        """,
        {"set_id": register.set_id, "json": register.model_dump_json()},
    )
    conn.commit()


def load_register(conn: sqlite3.Connection, set_id: str) -> Optional[DepartureRegister]:
    """The persisted register for ``set_id`` (tables — the source of truth), or None. The stored
    ``approved`` column wins over whatever the JSON blob happens to carry, so the gate is always read
    from the authoritative flag."""
    row = conn.execute(
        "SELECT register_json, approved FROM client_boq_review_registers WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["register_json"] or row["register_json"] == "{}":
        return None
    reg = DepartureRegister.model_validate_json(row["register_json"])
    reg.approved = bool(row["approved"])
    return reg


def review_is_approved(conn: sqlite3.Connection, set_id: str) -> bool:
    """True when the review register for ``set_id`` is human-approved — the estimate gate."""
    row = conn.execute(
        "SELECT approved FROM client_boq_review_registers WHERE set_id = ?", (set_id,)
    ).fetchone()
    return bool(row and row["approved"])


def set_review_approved(conn: sqlite3.Connection, set_id: str, approved: bool) -> None:
    """Record the human approval decision on the register (the gate action). Upserts the row so it is
    safe even if called before a register was assembled (approved with no register is still a no-op
    for the estimate, which also requires a register)."""
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
# Workspace artifacts (the readable file copies)
# ---------------------------------------------------------------------------
def _client_boq_dir(ws: Workspace, tender_id: str):
    path = ws.artifacts_dir(tender_id, create=True) / "client_boq"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_parsed_artifact(ws: Workspace, tender_id: str, parsed: ParsedDocumentSet) -> None:
    (_client_boq_dir(ws, tender_id) / "parsed.json").write_text(
        parsed.model_dump_json(indent=2), encoding="utf-8"
    )


def save_register_artifact(ws: Workspace, tender_id: str, register: DepartureRegister) -> None:
    (_client_boq_dir(ws, tender_id) / "register.json").write_text(
        register.model_dump_json(indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Estimate persistence (client_boq_estimates table + artifact)
# ---------------------------------------------------------------------------
def save_estimate(conn: sqlite3.Connection, estimate: Estimate) -> None:
    """Persist the priced estimate to the tables (upsert per document set)."""
    conn.execute(
        """
        INSERT INTO client_boq_estimates (set_id, estimate_json)
        VALUES (:set_id, :json)
        ON CONFLICT(set_id) DO UPDATE SET estimate_json = excluded.estimate_json
        """,
        {"set_id": estimate.set_id, "json": estimate.model_dump_json()},
    )
    conn.commit()


def load_estimate(conn: sqlite3.Connection, set_id: str) -> Optional[Estimate]:
    """The persisted estimate for ``set_id``, or None."""
    row = conn.execute(
        "SELECT estimate_json FROM client_boq_estimates WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["estimate_json"] or row["estimate_json"] == "{}":
        return None
    return Estimate.model_validate_json(row["estimate_json"])


def save_estimate_artifact(ws: Workspace, tender_id: str, estimate: Estimate) -> None:
    (_client_boq_dir(ws, tender_id) / "estimate.json").write_text(
        estimate.model_dump_json(indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Estimate scope (the s01 draft + the scope gate — the second estimate gate)
# ---------------------------------------------------------------------------
def save_scope_draft(conn: sqlite3.Connection, set_id: str, draft: ScopeReviewResult) -> None:
    """Persist the s01 scope draft, preserving any existing approval/amendment (re-drafting never
    silently re-opens the gate)."""
    conn.execute(
        """
        INSERT INTO client_boq_estimate_scope (set_id, scope_json)
        VALUES (:set_id, :json)
        ON CONFLICT(set_id) DO UPDATE SET scope_json = excluded.scope_json
        """,
        {"set_id": set_id, "json": draft.model_dump_json()},
    )
    conn.commit()


def load_scope(conn: sqlite3.Connection, set_id: str) -> Optional[EstimateScope]:
    """The scope record (draft + amended summary + approved flag), or None. The stored ``approved``
    column is authoritative (mirrors the review gate)."""
    row = conn.execute(
        "SELECT scope_json, amended_summary, approved FROM client_boq_estimate_scope WHERE set_id = ?",
        (set_id,),
    ).fetchone()
    if not row or not row["scope_json"] or row["scope_json"] == "{}":
        return None
    return EstimateScope(
        set_id=set_id, draft=ScopeReviewResult.model_validate_json(row["scope_json"]),
        amended_summary=row["amended_summary"] or "", approved=bool(row["approved"]),
    )


def scope_is_approved(conn: sqlite3.Connection, set_id: str) -> bool:
    """True when the estimate scope for ``set_id`` is human-approved — the estimate's second gate."""
    row = conn.execute(
        "SELECT approved FROM client_boq_estimate_scope WHERE set_id = ?", (set_id,)
    ).fetchone()
    return bool(row and row["approved"])


def approve_scope(conn: sqlite3.Connection, set_id: str, approved: bool, amended_summary: str = "") -> None:
    """The scope gate writer (the ONLY place scope-approved state is set). An ``amended_summary`` (when
    non-empty) becomes the approved scope of record; the original draft is retained in ``scope_json``."""
    conn.execute(
        """
        INSERT INTO client_boq_estimate_scope (set_id, amended_summary, approved, approved_at)
        VALUES (:set_id, :amended, :approved, CASE WHEN :approved THEN datetime('now') ELSE NULL END)
        ON CONFLICT(set_id) DO UPDATE SET
            amended_summary = excluded.amended_summary,
            approved = excluded.approved,
            approved_at = excluded.approved_at
        """,
        {"set_id": set_id, "amended": amended_summary.strip(), "approved": 1 if approved else 0},
    )
    conn.commit()


def save_scope_artifact(ws: Workspace, tender_id: str, scope: EstimateScope) -> None:
    (_client_boq_dir(ws, tender_id) / "estimate_scope.json").write_text(
        scope.model_dump_json(indent=2), encoding="utf-8"
    )
