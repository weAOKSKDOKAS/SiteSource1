"""The back of the tender funnel: final approval, then submission — decision + record.

Two stores, both beside ``bridge/decisions.py`` and both the same shape as ``bridge_route_decisions``:
a per-tender human decision keyed on ``run_ref``, lazy DDL, ``decided_by``/``decided_at`` provenance.

* ``bridge_final_approvals`` — the last human gate before the tender goes out: ``approve`` or
  ``revise``. A ``revise`` MUST say what to correct (node 47). The machine never writes this row;
  the operator does, through the confirm endpoint, exactly as a route decision is recorded.
* ``bridge_tender_submissions`` — the act of submitting. It FREEZES the offer letter at the moment
  it goes out (an immutable snapshot, so a later letter edit never rewrites what was submitted),
  records the proof the operator supplies, and refuses outright unless an ``approve`` exists. You
  cannot submit a tender nobody approved — a hard precondition, not a soft warning.

What this does NOT do: it does not build the letter (``estimate/s06_offer.py`` owns that, and is
off-limits), does not send anything, and does not invent a deadline or a proof. An unknown deadline
makes ``on_time`` NULL, shown as "deadline unknown" — never a fabricated pass.

Table names carry the ``bridge_`` prefix to match ``bridge_route_decisions``; the brief wrote
``tender_submissions`` and this reconciles it with the module's real convention.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Optional

from bridge.identity import bridge_conn, run_ref_for

# The two verdicts a final approval can carry. `revise` is not a rejection of the tender — it is a
# note that something must be corrected before it goes out (node 47), so it REQUIRES a rationale.
APPROVE = "approve"
REVISE = "revise"
FINAL_VERDICTS = (APPROVE, REVISE)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row["n"])


# ---------------------------------------------------------------------------
# Final approval — the last human gate before submission (node 46/47)
# ---------------------------------------------------------------------------
def ensure_final_approval_table(conn: sqlite3.Connection) -> None:
    """Create ``bridge_final_approvals`` if absent (lazy DDL, idempotent).

    ``set_id`` is the PRIMARY KEY: one final verdict per tender, re-deciding updates in place — the
    same idempotence ``bridge_route_decisions`` gets from its UNIQUE constraint, here at tender
    granularity because there is exactly one tender to approve.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_final_approvals (
            set_id      TEXT PRIMARY KEY,
            verdict     TEXT NOT NULL,                       -- 'approve' | 'revise'
            rationale   TEXT NOT NULL DEFAULT '',            -- REQUIRED for 'revise' (what to correct)
            approved_by TEXT NOT NULL DEFAULT 'operator',
            approved_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _approval_row(row: sqlite3.Row) -> dict:
    return {
        "set_id": row["set_id"], "verdict": row["verdict"], "rationale": row["rationale"] or "",
        "approved_by": row["approved_by"] or "operator", "approved_at": row["approved_at"] or "",
    }


def confirm_final_approval(set_id: str, verdict: str, rationale: str = "", *,
                           approved_by: str = "operator") -> dict:
    """Record the human's final verdict on the whole tender. THE sole writer of this row.

    Mirrors ``decisions.confirm_routes``: validates before it writes, keys on ``run_ref_for`` at the
    boundary, upserts (re-deciding replaces), stamps who and when. ``revise`` without a rationale is
    refused — node 47 is "what to correct", and a revise verdict that says nothing to correct is not
    a decision anybody can act on.
    """
    ref = run_ref_for(set_id)
    if verdict not in FINAL_VERDICTS:
        raise ValueError(f"verdict must be one of {list(FINAL_VERDICTS)}; got {verdict!r}")
    text = (rationale or "").strip()
    if verdict == REVISE and not text:
        raise ValueError("a 'revise' verdict must say what to correct — rationale is required.")

    conn = bridge_conn()
    try:
        ensure_final_approval_table(conn)
        conn.execute(
            """
            INSERT INTO bridge_final_approvals (set_id, verdict, rationale, approved_by, approved_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(set_id) DO UPDATE SET
                verdict = excluded.verdict, rationale = excluded.rationale,
                approved_by = excluded.approved_by, approved_at = excluded.approved_at
            """,
            (ref, verdict, text, approved_by, _now()),
        )
        conn.commit()
        return load_final_approval(ref) or {}
    finally:
        conn.close()


def load_final_approval(set_id: str) -> Optional[dict]:
    """The persisted final verdict for a tender, or ``None`` — a pure read. "Not yet decided" is a
    STATE, not an error."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_final_approvals"):
            return None
        row = conn.execute(
            "SELECT * FROM bridge_final_approvals WHERE set_id = ?", (ref,)).fetchone()
        return _approval_row(row) if row else None
    finally:
        conn.close()


def is_approved(set_id: str) -> bool:
    """True when the tender carries an ``approve`` final verdict — the submission precondition."""
    approval = load_final_approval(set_id)
    return bool(approval and approval["verdict"] == APPROVE)
