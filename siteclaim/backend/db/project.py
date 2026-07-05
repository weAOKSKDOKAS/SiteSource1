"""Unified project spine (Phase 4, Layer 3) — the thin umbrella keyed by ``run_ref``.

A tender's analysis run is one identity that carries it through the tracks: routing
(``package_routes.run_ref``) → the left estimates (``estimate_projects.run_ref``) and the
right sourcing, and — on award — a benchmark project. This table holds NO cost data (the
benchmark tables stay authoritative); ``benchmark_project_id`` is only the link recorded when
an estimate is captured into a benchmark snapshot (Phase 4c). Self-migrating guard, Row
access — mirrors the routing/estimate stores. Nothing here touches the network.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Optional


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def has_unified_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='unified_projects'"
    ).fetchone()
    return row is not None


def ensure_unified_table(conn: sqlite3.Connection) -> None:
    """Create ``unified_projects`` if this DB predates it (IF NOT EXISTS — never drops)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS unified_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_ref TEXT NOT NULL UNIQUE, name TEXT,
            provenance TEXT NOT NULL DEFAULT 'live', benchmark_project_id INTEGER REFERENCES projects(id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_unified_projects_run ON unified_projects(run_ref);
        """
    )


def _row_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "run_ref": row["run_ref"], "name": row["name"] or "",
        "provenance": row["provenance"] or "live", "benchmark_project_id": row["benchmark_project_id"],
        "created_at": row["created_at"] or "",
    }


def get(conn: sqlite3.Connection, run_ref: str) -> Optional[dict]:
    if not has_unified_table(conn) or not run_ref:
        return None
    row = conn.execute("SELECT * FROM unified_projects WHERE run_ref = ?", (run_ref,)).fetchone()
    return _row_dict(row) if row is not None else None


def get_or_create(conn: sqlite3.Connection, run_ref: str, *, name: str = "", provenance: str = "live") -> dict:
    """Return the run's umbrella row, creating it on first sight. The name backfills if the
    row was created without one (e.g. a lazy read before the analyze recorded it)."""
    ensure_unified_table(conn)
    existing = get(conn, run_ref)
    if existing is not None:
        if name and not existing["name"]:
            conn.execute("UPDATE unified_projects SET name = ? WHERE run_ref = ?", (name, run_ref))
            conn.commit()
            existing["name"] = name
        return existing
    conn.execute(
        "INSERT INTO unified_projects (run_ref, name, provenance, created_at) VALUES (?, ?, ?, ?)",
        (run_ref, name, provenance, _now()),
    )
    conn.commit()
    return get(conn, run_ref)


def link_benchmark(conn: sqlite3.Connection, run_ref: str, benchmark_project_id: int) -> Optional[dict]:
    """Record that this run's tender was captured into a benchmark project (Phase 4c)."""
    ensure_unified_table(conn)
    if get(conn, run_ref) is None:
        return None
    conn.execute(
        "UPDATE unified_projects SET benchmark_project_id = ? WHERE run_ref = ?",
        (benchmark_project_id, run_ref),
    )
    conn.commit()
    return get(conn, run_ref)


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    if not has_unified_table(conn):
        return []
    rows = conn.execute("SELECT * FROM unified_projects ORDER BY id DESC").fetchall()
    return [_row_dict(r) for r in rows]
