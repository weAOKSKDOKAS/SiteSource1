"""The shortlist itself, persisted — because persisting the ticks is useless without the list.

``bridge/approvals.py`` records which firms the operator selected per package, and the tab restores
that on mount. It shipped, and the shortlist was still lost on every refresh, because the thing
being restored had nothing to land on: ``shortlist`` was React state written only by
``runShortlist``, read by nothing at load, and stored by no endpoint. After a refresh the candidate
list was empty, so the operator re-ran a 148-firm screen to get back to where they already were.

Worse than the re-run: ``runShortlist`` filters a restored selection to the firms the RECOMPUTED
list contains (``stored.filter(f => ids.has(f))``). A firm that was selected and no longer makes the
new top-k is dropped from the selection without a word. Restoring the list rather than rebuilding it
removes that failure entirely — the ticks land back on the same candidates they were made against.

Modelled on ``approvals.py`` rather than inventing a second pattern: the same lazy idempotent DDL,
the same ``bridge_conn`` / ``run_ref_for`` identity, the same ``*_on(conn, …)`` + connection-owning
wrapper pair.

ONE ROW PER SET, holding the ``ShortlistSet`` as JSON. Not a row per candidate: the shortlist is a
single computed answer with its evidence and flags, read and written whole, and normalising it here
would mean re-deriving a Layer-1 result on every read. Re-running the screen simply replaces it.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Optional


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the bridge's shortlist table if absent (lazy DDL, idempotent)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_shortlists (
            set_id TEXT PRIMARY KEY,
            shortlist_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def save_shortlist_on(conn: sqlite3.Connection, set_id: str, shortlist: dict) -> None:
    """Replace this set's stored shortlist. A re-run is a new answer, not a second one."""
    ensure_tables(conn)
    conn.execute(
        "INSERT INTO bridge_shortlists (set_id, shortlist_json, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(set_id) DO UPDATE SET shortlist_json = excluded.shortlist_json, "
        "created_at = excluded.created_at",
        (set_id, json.dumps(shortlist), _now()),
    )
    conn.commit()


def load_shortlist_on(conn: sqlite3.Connection, set_id: str) -> Optional[dict]:
    """The stored shortlist, or ``None`` when the screen has never been run for this set.

    Unreadable JSON also answers ``None``: a corrupt row means "run it again", which is exactly
    what an absent row means, and raising here would break a tab that has other work to do.
    """
    ensure_tables(conn)
    row = conn.execute(
        "SELECT shortlist_json FROM bridge_shortlists WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["shortlist_json"]:
        return None
    try:
        body = json.loads(row["shortlist_json"])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def shortlist_created_at_on(conn: sqlite3.Connection, set_id: str) -> str:
    """When the stored shortlist was computed, or ``""``. Shown so an operator reading a restored
    list knows whether it predates a change to the split."""
    ensure_tables(conn)
    row = conn.execute(
        "SELECT created_at FROM bridge_shortlists WHERE set_id = ?", (set_id,)
    ).fetchone()
    return (row["created_at"] if row else "") or ""


# ---------------------------------------------------------------------------
# The connection-owning wrappers, exactly as approvals.py pairs them
# ---------------------------------------------------------------------------
def save_shortlist(set_id: str, shortlist: dict) -> None:
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        save_shortlist_on(conn, run_ref_for(set_id), shortlist)
    finally:
        conn.close()


def load_shortlist(set_id: str) -> tuple[Optional[dict], str]:
    """``(shortlist, created_at)`` — both in one read, so the caller makes one round trip."""
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        ref = run_ref_for(set_id)
        return load_shortlist_on(conn, ref), shortlist_created_at_on(conn, ref)
    finally:
        conn.close()
