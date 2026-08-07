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


# ---------------------------------------------------------------------------
# Every name a tender is known by — so one tender is one workspace
# ---------------------------------------------------------------------------
# A TENDER IS ADDRESSED BY ITS ``run_ref`` AND BY NOTHING ELSE, but the callers that reach a
# workspace hold whatever string they happen to have: the bridge holds the ``set_id``, client_boq's
# ingest holds the set's display NAME, `/ingest-upload` holds the project title read off the
# documents, and `Workspace.tender_dir` slugged each of them into a DIFFERENT directory. One tender
# on the operator's disk had five:
#
#   nd-2025-04-san-tin-technopole                       the set_id — 156 KB index, current
#   nd-2025-04                                          tender_slug("Contract No. ND/2025/04")
#   ground-investigation-works-for-developme-ccd1cccd   tender_slug(<long title>) — the hash branch
#   san-tin-technopole-phase-2-ground-invest-68caed6d   another title, another hash
#   i-nd-2025-04-bq-0                                   a FILENAME used as the project name
#
# Six rounds of fixing one caller at a time did not converge, because each fix only revealed the
# next string somebody happened to hold. This table ends that: every name a tender is known by maps
# to its one ``run_ref``, and resolution is an EXACT lookup. Never fuzzy — a near-match across two
# tender names would put one tender's documents into another's enquiry, which is worse than the
# defect it would be fixing.
def ensure_alias_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS unified_project_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alias TEXT NOT NULL UNIQUE,
            run_ref TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_unified_aliases_run ON unified_project_aliases(run_ref);
        """
    )


def has_alias_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='unified_project_aliases'"
    ).fetchone()
    return row is not None


def register_aliases(conn: sqlite3.Connection, run_ref: str, *names: str) -> list[str]:
    """Record every ``name`` as another way of addressing ``run_ref``. Returns what was stored.

    The ``run_ref`` registers as an alias of itself, so one lookup answers every case. An alias
    already pointing at a DIFFERENT tender is left alone and reported by omission: re-pointing it
    would move one tender's artifacts under another, and a collision between two tenders' names is
    a fact for a person to resolve, not for this to overwrite.
    """
    ref = (run_ref or "").strip()
    if not ref:
        return []
    ensure_alias_table(conn)
    stored: list[str] = []
    for raw in (ref, *names):
        alias = (raw or "").strip()
        if not alias:
            continue
        row = conn.execute(
            "SELECT run_ref FROM unified_project_aliases WHERE alias = ?", (alias,)).fetchone()
        if row is not None:
            if row["run_ref"] == ref:
                stored.append(alias)
            continue                      # claimed by another tender — never re-pointed
        conn.execute(
            "INSERT INTO unified_project_aliases (alias, run_ref, created_at) VALUES (?, ?, ?)",
            (alias, ref, _now()))
        stored.append(alias)
    conn.commit()
    return stored


def resolve_ref(conn: sqlite3.Connection, name_or_ref: str) -> Optional[str]:
    """The ``run_ref`` this string addresses, or ``None`` when it addresses no known tender.

    STRICTLY READ-ONLY — it creates no table and writes no row, because it is called from
    ``Workspace.tender_dir``, which runs against whatever database is open, including the committed
    demo one. A missing table is simply "nothing is registered".
    """
    ref = (name_or_ref or "").strip()
    if not ref:
        return None
    if has_alias_table(conn):
        row = conn.execute(
            "SELECT run_ref FROM unified_project_aliases WHERE alias = ?", (ref,)).fetchone()
        if row is not None and row["run_ref"]:
            return row["run_ref"]
    if not has_unified_table(conn):
        return None
    if conn.execute("SELECT 1 FROM unified_projects WHERE run_ref = ?", (ref,)).fetchone():
        return ref                        # already canonical
    row = conn.execute(
        "SELECT run_ref FROM unified_projects WHERE name = ? ORDER BY id LIMIT 1", (ref,)).fetchone()
    return row["run_ref"] if row and row["run_ref"] else None


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
