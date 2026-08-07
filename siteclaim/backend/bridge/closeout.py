"""After the tender goes out: the outcome, the lessons, a light change-control log, and — when we
win — a handover package. The only feedback edge in the whole workflow (nodes 49–53).

Every store here is the same shape as the rest of the bridge: a per-tender record keyed on
``run_ref``, lazy ``CREATE TABLE IF NOT EXISTS``, human provenance, written through ``bridge_conn``.

**The distinction this module exists to keep:** the TENDER OUTCOME is whether *we* won the tender
from the client. It is NOT the sublet award (which subcontractor wins a package — that is
package-level, lives in the procurement recommend flow, and one never writes the other). They are
named apart on purpose; conflating them is the failure this file is written to prevent.

Table names carry the ``bridge_`` prefix to match ``bridge_route_decisions``; the brief wrote
``tender_outcomes`` / ``tender_lessons`` / ``post_submission_events`` and this reconciles them with
the module's real convention.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Optional

from bridge.identity import bridge_conn, run_ref_for

# The tender's lifecycle after it goes out. `submitted` is the resting state; `won`/`lost` are the
# outcomes that feed the corpus; `withdrawn` is a tender we pulled. A machine never writes these —
# a person records what the client decided.
SUBMITTED = "submitted"
WON = "won"
LOST = "lost"
WITHDRAWN = "withdrawn"
OUTCOME_STATUSES = (SUBMITTED, WON, LOST, WITHDRAWN)
# The two that trigger the corpus feedback loop — a resolved tender, won or lost, is what a future
# tender learns from. `submitted`/`withdrawn` record nothing to the corpus.
CORPUS_OUTCOMES = (WON, LOST)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row["n"])


# ---------------------------------------------------------------------------
# Tender outcome — did WE win the tender (node 49). NOT the sublet award.
# ---------------------------------------------------------------------------
def ensure_outcome_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_tender_outcomes (
            set_id        TEXT PRIMARY KEY,
            status        TEXT NOT NULL,                    -- submitted | won | lost | withdrawn
            outcome_notes TEXT NOT NULL DEFAULT '',         -- award value, competitor, why — human
            decided_by    TEXT NOT NULL DEFAULT 'operator',
            decided_at    TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _outcome_row(row: sqlite3.Row) -> dict:
    return {
        "set_id": row["set_id"], "status": row["status"], "outcome_notes": row["outcome_notes"] or "",
        "decided_by": row["decided_by"] or "operator", "decided_at": row["decided_at"] or "",
    }


def set_outcome(set_id: str, status: str, notes: str = "", *, decided_by: str = "operator") -> dict:
    """Record the tender outcome — THE sole writer of this row. Validates the status, keys on
    ``run_ref``, upserts. A ``won``/``lost`` outcome also feeds the corpus (see
    :func:`feed_outcome_to_corpus`), which the API layer calls after this returns.

    ``outcome_notes`` is the human's — award value, competitor, why we won or lost. The machine
    never drafts it.
    """
    ref = run_ref_for(set_id)
    if status not in OUTCOME_STATUSES:
        raise ValueError(f"status must be one of {list(OUTCOME_STATUSES)}; got {status!r}")

    conn = bridge_conn()
    try:
        ensure_outcome_table(conn)
        conn.execute(
            """
            INSERT INTO bridge_tender_outcomes (set_id, status, outcome_notes, decided_by, decided_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(set_id) DO UPDATE SET
                status = excluded.status, outcome_notes = excluded.outcome_notes,
                decided_by = excluded.decided_by, decided_at = excluded.decided_at
            """,
            (ref, status, (notes or "").strip(), decided_by, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return load_outcome(ref) or {}


def load_outcome(set_id: str) -> Optional[dict]:
    """The tender outcome, or ``None`` — a pure read. "Not yet decided" is a state, not an error."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_tender_outcomes"):
            return None
        row = conn.execute(
            "SELECT * FROM bridge_tender_outcomes WHERE set_id = ?", (ref,)).fetchone()
        return _outcome_row(row) if row else None
    finally:
        conn.close()
