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

import sqlite3
from typing import Optional

from client_boq import models
from client_boq.models import DepartureRegister, ParsedDocumentSet
from db import store as db_store
from pipeline.workspace import Workspace


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def get_conn() -> sqlite3.Connection:
    """Open the shared DB and ensure the module's own tables exist (idempotent)."""
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
