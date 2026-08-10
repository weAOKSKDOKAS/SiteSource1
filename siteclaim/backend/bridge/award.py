"""The sublet award, persisted — which firm won a package, at what levelled total.

The same decision+record family as ``bridge_route_decisions`` and the final approval: a per-package
human decision keyed on ``run_ref``, lazy DDL, provenance columns, one sole writer. It exists
because the award lived only in React state — the sourcing screen's ``awards`` dict died with the
tab, so nothing downstream could ever know what a sublet package costs, and the tender total could
not be assembled at all (node 43's gap).

**The award is the human's.** The ranking recommends; the radio is a person; this records what they
pressed, with the levelled total of the return they chose. It never computes a number of its own.

**The double-count front door is here.** A package whose confirmed route is self-perform cannot
take a sub award — recording one would put the same work on both sides of the tender total. Refused
by name, not silently allowed and reconciled later.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Optional

from bridge.identity import bridge_conn, run_ref_for


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row["n"])


def ensure_award_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_package_awards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id      TEXT NOT NULL,
            package_key TEXT NOT NULL,
            firm_id     TEXT NOT NULL,
            firm_name   TEXT NOT NULL DEFAULT '',
            total       REAL,                        -- the levelled total of the chosen return
            decided_by  TEXT NOT NULL DEFAULT 'operator',
            decided_at  TEXT NOT NULL,
            UNIQUE(set_id, package_key)
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_package_awards_set ON bridge_package_awards(set_id);
        """
    )
    conn.commit()


def _row(row: sqlite3.Row) -> dict:
    return {
        "set_id": row["set_id"], "package_key": row["package_key"], "firm_id": row["firm_id"],
        "firm_name": row["firm_name"] or "", "total": row["total"],
        "decided_by": row["decided_by"] or "operator", "decided_at": row["decided_at"] or "",
    }


def record_award(set_id: str, package_key: str, firm_id: str, firm_name: str = "",
                 total: Optional[float] = None, *, decided_by: str = "operator") -> dict:
    """Record the human's award for one package — THE sole writer. Re-awarding replaces.

    Refuses a package whose confirmed route is self-perform: the estimate prices that side, and an
    award there would count the same work twice. A package with NO confirmed route also refuses —
    the award follows the routing decision, never precedes it.
    """
    from bridge import decisions

    ref = run_ref_for(set_id)
    key = (package_key or "").strip()
    if not key:
        raise ValueError("an award needs a package_key")
    if not (firm_id or "").strip():
        raise ValueError("an award needs the firm that won it")

    state = decisions.stored_decisions(ref)
    if key in state.get("self_perform_packages", []):
        raise ValueError(
            f"package {key!r} is routed SELF-PERFORM — the estimate prices it, and a sub award "
            f"there would count the same work on both sides of the tender total. Re-route it to "
            f"sublet first if that is what is meant.")
    if key not in state.get("sublet_packages", []):
        raise ValueError(
            f"package {key!r} has no confirmed sublet route — the award follows the routing "
            f"decision. Confirm the routing first (POST /bridge/{ref}/route/confirm).")

    conn = bridge_conn()
    try:
        ensure_award_table(conn)
        conn.execute(
            """
            INSERT INTO bridge_package_awards
                (set_id, package_key, firm_id, firm_name, total, decided_by, decided_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(set_id, package_key) DO UPDATE SET
                firm_id = excluded.firm_id, firm_name = excluded.firm_name,
                total = excluded.total, decided_by = excluded.decided_by,
                decided_at = excluded.decided_at
            """,
            (ref, key, firm_id.strip(), (firm_name or "").strip(), total, decided_by, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bridge_package_awards WHERE set_id = ? AND package_key = ?",
            (ref, key)).fetchone()
        return _row(row)
    finally:
        conn.close()


def clear_award(set_id: str, package_key: str) -> bool:
    """Withdraw an award (the operator pressed 'skip', or is re-levelling). True when one existed."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_package_awards"):
            return False
        cur = conn.execute(
            "DELETE FROM bridge_package_awards WHERE set_id = ? AND package_key = ?",
            (ref, (package_key or "").strip()))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def load_awards(set_id: str) -> list[dict]:
    """Every recorded award for the tender — a pure read, ordered by package."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_package_awards"):
            return []
        rows = conn.execute(
            "SELECT * FROM bridge_package_awards WHERE set_id = ? ORDER BY package_key",
            (ref,)).fetchall()
        return [_row(r) for r in rows]
    finally:
        conn.close()
