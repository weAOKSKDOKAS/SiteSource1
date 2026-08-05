"""Which firms the operator selected per package — persisted, so a browser reload does not lose it.

``approvals`` lived only in React state. Close the tab and the shortlist selection was gone, with
no server-side record that it had ever been made — the same session-only loss that made Level &
compare render "No dispatched packages yet" over six replies sitting on disk.

**Persisting a selection is not approving a dispatch.** Nothing here sends anything, drafts
anything, or moves a gate. The human gate is exactly where it was: the operator still presses
Compose/Prepare on the Dispatch step, and that step still reads the approvals it is given. This
only stops the selection evaporating between the click and the decision.

Modelled on ``bridge/decisions.py`` rather than inventing a second pattern: the same lazy
idempotent DDL, the same ``UNIQUE`` from the first version so a re-selection updates in place
instead of accumulating rows that would be read back in insertion order, and the same
``bridge_conn`` / ``run_ref_for`` identity handling.

The row is ``(set_id, package_key, firm_id)``. Per-firm rather than a JSON blob per package,
because "who is selected" is a set membership and a set is what the UI toggles — storing the blob
would mean read-modify-write on every click and a lost update the moment two tabs are open.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the bridge's shortlist-approval table if absent (lazy DDL, idempotent).

    ``UNIQUE(set_id, package_key, firm_id)`` from the first version: selecting the same firm twice
    must be a no-op, not a second row. Adding the constraint later would cost a migration.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_shortlist_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id TEXT NOT NULL,
            package_key TEXT NOT NULL,
            firm_id TEXT NOT NULL,
            selected_by TEXT NOT NULL DEFAULT 'operator',
            selected_at TEXT NOT NULL,
            UNIQUE(set_id, package_key, firm_id)
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_shortlist_approvals_set
            ON bridge_shortlist_approvals(set_id);
        """
    )
    conn.commit()


def load_approvals_on(conn: sqlite3.Connection, set_id: str) -> dict[str, list[str]]:
    """``{package_key: [firm_id, …]}`` for one set, against a caller-owned connection.

    Firm order is the order they were selected in — stable across reloads, so the list does not
    reshuffle under the operator between one visit and the next.
    """
    ensure_tables(conn)
    out: dict[str, list[str]] = {}
    for row in conn.execute(
        "SELECT package_key, firm_id FROM bridge_shortlist_approvals "
        "WHERE set_id = ? ORDER BY id",
        (set_id,),
    ).fetchall():
        out.setdefault(row["package_key"], []).append(row["firm_id"])
    return out


def save_approvals_on(
    conn: sqlite3.Connection, set_id: str, approvals: dict[str, list[str]],
    *, selected_by: str = "operator",
) -> dict[str, list[str]]:
    """Replace the stored selection for EVERY package named in ``approvals``. Returns the new state.

    Replace, not merge, and only for the packages named: the payload is the UI's current selection
    for those packages, so a firm the operator has just DESELECTED must disappear. A package absent
    from the payload is left alone — that is a package this screen was not talking about, not one
    whose selection was cleared.

    An empty list for a package is meaningful and is honoured: it means "none of them", which is a
    decision, and it must not read back as the previous selection.
    """
    ensure_tables(conn)
    stamp = _now()
    for package_key, firm_ids in approvals.items():
        conn.execute(
            "DELETE FROM bridge_shortlist_approvals WHERE set_id = ? AND package_key = ?",
            (set_id, package_key),
        )
        conn.executemany(
            "INSERT INTO bridge_shortlist_approvals "
            "(set_id, package_key, firm_id, selected_by, selected_at) VALUES (?, ?, ?, ?, ?)",
            [(set_id, package_key, fid, selected_by, stamp)
             for fid in dict.fromkeys(f for f in firm_ids if f)],   # distinct, order preserved
        )
    conn.commit()
    return load_approvals_on(conn, set_id)


# ---------------------------------------------------------------------------
# The connection-owning wrappers, exactly as decisions.py pairs them
# ---------------------------------------------------------------------------
def load_approvals(set_id: str) -> dict[str, list[str]]:
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        return load_approvals_on(conn, run_ref_for(set_id))
    finally:
        conn.close()


def save_approvals(set_id: str, approvals: dict[str, list[str]],
                   *, selected_by: str = "operator") -> dict[str, list[str]]:
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        return save_approvals_on(conn, run_ref_for(set_id), approvals, selected_by=selected_by)
    finally:
        conn.close()
