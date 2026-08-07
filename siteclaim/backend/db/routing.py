"""Routing gate — storage over ``package_routes`` (Layer 3).

Persists the per-package route recommendation at analyze time (``chosen_route`` null) and,
at the confirm gate, records the human's decision — ``confirm_decisions`` is the ONLY writer
of ``chosen_route`` (Layer 4). Mirrors the benchmark store conventions (Row access,
self-migrating guard). Nothing here touches the network.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Optional


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def has_routing_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='package_routes'"
    ).fetchone()
    return row is not None


def ensure_routing_table(conn: sqlite3.Connection) -> None:
    """Create ``package_routes`` if this DB predates it (IF NOT EXISTS — never drops)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS package_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_ref TEXT NOT NULL, package_key TEXT NOT NULL,
            trade TEXT, scope_summary TEXT, recommended_route TEXT, rationale TEXT, signals TEXT,
            chosen_route TEXT, decided_by TEXT, decided_at TEXT, source TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_package_routes_run ON package_routes(run_ref);
        """
    )


def _row_dict(row: sqlite3.Row) -> dict:
    try:
        signals = json.loads(row["signals"]) if row["signals"] else {}
    except (json.JSONDecodeError, TypeError):
        signals = {}
    return {
        "id": row["id"], "package_key": row["package_key"], "trade": row["trade"] or "",
        "scope_summary": row["scope_summary"] or "", "recommended_route": row["recommended_route"] or "sublet",
        "rationale": row["rationale"] or "", "signals": signals,
        "chosen_route": row["chosen_route"], "decided_by": row["decided_by"] or "",
        "decided_at": row["decided_at"] or "", "source": row["source"] or "",
    }


def write_proposal(conn: sqlite3.Connection, run_ref: str, packages: list[dict]) -> list[dict]:
    """Replace the run's routing proposal with ``packages`` (each: package_key, trade,
    scope_summary, recommended_route, rationale, signals, source). Atomic.

    **A HUMAN'S CHOSEN ROUTE SURVIVES A RE-PROPOSAL.** This deleted every row and re-inserted with
    `chosen_route = NULL`, so re-running `/route/analyze` silently destroyed every Layer-4 decision
    on the run — a recomputation wiping the human gate it exists to inform. The advisory columns
    (recommended_route, rationale, signals) are the proposal's to replace; `chosen_route` is not
    the proposal's to hold an opinion about at all.

    A key the new proposal does NOT carry loses its decision, and correctly: it named a package
    that no longer exists. The caller is told which — see `bridge.decisions.propose_routes`, which
    reports the same thing for its own decision table — so a re-confirm is a known step rather than
    a silent gap.
    """
    ensure_routing_table(conn)
    try:
        kept = {
            row["package_key"]: (row["chosen_route"], row["decided_by"], row["decided_at"])
            for row in conn.execute(
                "SELECT package_key, chosen_route, decided_by, decided_at FROM package_routes "
                "WHERE run_ref = ? AND chosen_route IS NOT NULL", (run_ref,)).fetchall()
        }
        conn.execute("DELETE FROM package_routes WHERE run_ref = ?", (run_ref,))
        for p in packages:
            chosen, by, at = kept.get(p["package_key"], (None, None, None))
            conn.execute(
                "INSERT INTO package_routes (run_ref, package_key, trade, scope_summary, recommended_route, "
                "rationale, signals, chosen_route, decided_by, decided_at, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_ref, p["package_key"], p.get("trade"), p.get("scope_summary"), p.get("recommended_route"),
                 p.get("rationale"), json.dumps(p.get("signals", {})), chosen, by, at,
                 p.get("source"), _now()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return read_proposal(conn, run_ref)


def orphaned_decisions(conn: sqlite3.Connection, run_ref: str, package_keys: set) -> list[str]:
    """Confirmed routes whose ``package_key`` a new proposal would not carry — the decisions a
    re-proposal is about to drop. Read BEFORE `write_proposal`, so a caller can say which."""
    if not has_routing_table(conn):
        return []
    rows = conn.execute(
        "SELECT package_key FROM package_routes WHERE run_ref = ? AND chosen_route IS NOT NULL",
        (run_ref,)).fetchall()
    return sorted(r["package_key"] for r in rows if r["package_key"] not in package_keys)


def read_proposal(conn: sqlite3.Connection, run_ref: str) -> list[dict]:
    if not has_routing_table(conn):
        return []
    rows = conn.execute("SELECT * FROM package_routes WHERE run_ref = ? ORDER BY id", (run_ref,)).fetchall()
    return [_row_dict(r) for r in rows]


def confirm_decisions(conn: sqlite3.Connection, run_ref: str, decisions: dict[str, str], *,
                      decided_by: str = "operator") -> list[dict]:
    """THE sole writer of ``chosen_route`` (Layer 4). ``decisions`` maps package_key ->
    chosen_route (validated by the caller against the route vocabulary). Stamps
    decided_by/decided_at. Atomic. Returns the run's full proposal."""
    ensure_routing_table(conn)
    when = _now()
    try:
        for package_key, route in decisions.items():
            conn.execute(
                "UPDATE package_routes SET chosen_route = ?, decided_by = ?, decided_at = ? "
                "WHERE run_ref = ? AND package_key = ?",
                (route, decided_by, when, run_ref, package_key),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return read_proposal(conn, run_ref)
