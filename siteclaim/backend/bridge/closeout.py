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


# ---------------------------------------------------------------------------
# Lessons learned — human-authored, never model-drafted (node 51)
# ---------------------------------------------------------------------------
# The categories a lesson can be filed under. Free enough to be useful, closed enough that a future
# read can group them; an unrecognised one falls to `other` rather than being refused, because a
# lesson worth writing must never be lost to a taxonomy quibble.
LESSON_CATEGORIES = ("pricing", "scope", "programme", "commercial", "other")


def ensure_lessons_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_tender_lessons (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id     TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT 'other',       -- pricing|scope|programme|commercial|other
            lesson     TEXT NOT NULL,                       -- the human's note; the machine never writes it
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_tender_lessons_set ON bridge_tender_lessons(set_id);
        """
    )
    conn.commit()


def add_lesson(set_id: str, category: str, lesson: str) -> dict:
    """Append one lesson. Human-authored — there is no model path into this table. An empty lesson
    is refused (nothing to record); an unrecognised category is filed as ``other`` rather than
    rejected, because the note is what matters and losing it to a category typo would be the worse
    outcome."""
    ref = run_ref_for(set_id)
    text = (lesson or "").strip()
    if not text:
        raise ValueError("a lesson needs text — an empty note records nothing.")
    cat = (category or "").strip().lower()
    if cat not in LESSON_CATEGORIES:
        cat = "other"

    conn = bridge_conn()
    try:
        ensure_lessons_table(conn)
        cur = conn.execute(
            "INSERT INTO bridge_tender_lessons (set_id, category, lesson, created_at) "
            "VALUES (?, ?, ?, ?)",
            (ref, cat, text, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bridge_tender_lessons WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _lesson_row(row)
    finally:
        conn.close()


def _lesson_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "set_id": row["set_id"], "category": row["category"] or "other",
        "lesson": row["lesson"] or "", "created_at": row["created_at"] or "",
    }


def list_lessons(set_id: str) -> list[dict]:
    """Every lesson for a tender, oldest first — a pure read."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_tender_lessons"):
            return []
        rows = conn.execute(
            "SELECT * FROM bridge_tender_lessons WHERE set_id = ? ORDER BY id", (ref,)).fetchall()
        return [_lesson_row(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Post-submission change-control log — LIGHT (nodes 49–50)
# ---------------------------------------------------------------------------
# A minimal append-only trail of what happened after submission: a clarification asked, a
# negotiation point, a change, a note. DELIBERATELY NOT a re-pricing engine — if a price or a bill
# moved, a human states that in `detail`; the log records the fact, it does not recompute anything.
# Actual client questions still go through the RFI machinery where that already fits; this is the
# tender-level trail beside it.
EVENT_KINDS = ("clarification", "negotiation", "change", "note")


def ensure_events_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_post_submission_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id     TEXT NOT NULL,
            kind       TEXT NOT NULL DEFAULT 'note',        -- clarification|negotiation|change|note
            detail     TEXT NOT NULL,                       -- what changed / was asked — human-stated
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_post_submission_events_set
            ON bridge_post_submission_events(set_id);
        """
    )
    conn.commit()


def log_event(set_id: str, kind: str, detail: str) -> dict:
    """Append one change-control entry. Append-only — nothing here edits or deletes a prior entry,
    because a negotiation trail you can rewrite is not a trail. An unrecognised kind falls to
    ``note``; an empty detail is refused."""
    ref = run_ref_for(set_id)
    text = (detail or "").strip()
    if not text:
        raise ValueError("an event needs a detail — an empty entry records nothing.")
    k = (kind or "").strip().lower()
    if k not in EVENT_KINDS:
        k = "note"

    conn = bridge_conn()
    try:
        ensure_events_table(conn)
        cur = conn.execute(
            "INSERT INTO bridge_post_submission_events (set_id, kind, detail, created_at) "
            "VALUES (?, ?, ?, ?)",
            (ref, k, text, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bridge_post_submission_events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _event_row(row)
    finally:
        conn.close()


def _event_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "set_id": row["set_id"], "kind": row["kind"] or "note",
        "detail": row["detail"] or "", "created_at": row["created_at"] or "",
    }


def list_events(set_id: str) -> list[dict]:
    """Every post-submission event for a tender, oldest first — a pure read."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_post_submission_events"):
            return []
        rows = conn.execute(
            "SELECT * FROM bridge_post_submission_events WHERE set_id = ? ORDER BY id", (ref,)
        ).fetchall()
        return [_event_row(r) for r in rows]
    finally:
        conn.close()
