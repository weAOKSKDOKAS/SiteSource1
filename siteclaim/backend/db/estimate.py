"""Estimator storage (Phase 3, Layer 3) — the left-track priced-tender build.

``estimate_projects`` / ``estimate_items`` are a DRAFT surface, deliberately separate from
the confirmed benchmark corpus (``tender_items`` / ``variance_records``): a work-in-progress
estimate must never pollute rate precedent, and on award it is promoted into a tender_items
snapshot (Phase 4). Rate-primary and rate-optional — the human prices every line; a quantity
is never invented and an amount is only ever the computable ``qty·rate`` extension (Layer-1
``computable_amount``), never fabricated. Mirrors the benchmark store conventions
(self-migrating guard, Row access, atomic writes). Nothing here touches the network.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Optional

from rules_engine.variance import computable_amount

_STATUSES = ("draft", "submitted", "awarded", "closed")
_UPDATABLE = ("name", "trade", "client", "contract_ref", "notes", "status", "scope_of_works")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def has_estimate_tables(conn: sqlite3.Connection) -> bool:
    """True when the DB carries the estimator tables (older DBs predate Phase 3)."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name IN "
        "('estimate_projects','estimate_items')"
    ).fetchone()
    return row is not None and int(row["n"]) == 2


def ensure_estimate_tables(conn: sqlite3.Connection) -> None:
    """Create the estimator tables + indexes if missing (IF NOT EXISTS — never drops), so a
    pre-Phase-3 database is upgraded in place. Called at the top of every estimator write."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS estimate_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, trade TEXT, client TEXT,
            contract_ref TEXT, status TEXT NOT NULL DEFAULT 'draft', provenance TEXT NOT NULL DEFAULT 'live',
            source TEXT, run_ref TEXT, package_key TEXT, scope_of_works TEXT, notes TEXT,
            created_at TEXT NOT NULL, closed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS estimate_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, estimate_id INTEGER NOT NULL REFERENCES estimate_projects(id),
            item_ref TEXT NOT NULL, description TEXT, unit TEXT, qty REAL, rate REAL, amount REAL,
            section TEXT, source TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_estimate_items_est     ON estimate_items(estimate_id);
        CREATE INDEX IF NOT EXISTS idx_estimate_items_ref     ON estimate_items(item_ref);
        CREATE INDEX IF NOT EXISTS idx_estimate_projects_prov ON estimate_projects(provenance);
        CREATE INDEX IF NOT EXISTS idx_estimate_projects_run  ON estimate_projects(run_ref);
        """
    )


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def _rollup(conn: sqlite3.Connection, estimate_id: int) -> tuple[int, int, Optional[float]]:
    """(item_count, priced_item_count, total). ``total`` sums the computable amounts only —
    a rate-only or unpriced line contributes nothing, never a fabricated figure."""
    rows = conn.execute(
        "SELECT qty, rate, amount FROM estimate_items WHERE estimate_id = ?", (estimate_id,)
    ).fetchall()
    priced = 0
    total: Optional[float] = None
    for r in rows:
        if r["rate"] is not None:
            priced += 1
        amt = r["amount"] if r["amount"] is not None else computable_amount(r["qty"], r["rate"], None)
        if amt is not None:
            total = round((total or 0.0) + amt, 2)
    return len(rows), priced, total


def _project_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    n, priced, total = _rollup(conn, row["id"])
    return {
        "id": row["id"], "name": row["name"], "trade": row["trade"] or "", "client": row["client"] or "",
        "contract_ref": row["contract_ref"] or "", "status": row["status"], "provenance": row["provenance"],
        "source": row["source"] or "", "run_ref": row["run_ref"] or "", "package_key": row["package_key"] or "",
        "scope_of_works": row["scope_of_works"] or "", "notes": row["notes"] or "",
        "created_at": row["created_at"] or "", "closed_at": row["closed_at"] or "",
        "item_count": n, "priced_item_count": priced, "total": total,
    }


def create_project(conn: sqlite3.Connection, *, name: str, trade: str = "", client: str = "",
                   contract_ref: str = "", notes: str = "", source: str = "manual",
                   provenance: str = "live", run_ref: str = "", package_key: str = "",
                   scope_of_works: str = "") -> dict:
    ensure_estimate_tables(conn)
    cur = conn.execute(
        "INSERT INTO estimate_projects (name, trade, client, contract_ref, status, provenance, source, "
        "run_ref, package_key, scope_of_works, notes, created_at) "
        "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)",
        (name, trade, client, contract_ref, provenance, source, run_ref, package_key, scope_of_works, notes, _now()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM estimate_projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _project_dict(conn, row)


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    if not has_estimate_tables(conn):
        return []
    rows = conn.execute("SELECT * FROM estimate_projects ORDER BY id DESC").fetchall()
    return [_project_dict(conn, r) for r in rows]


def get_project(conn: sqlite3.Connection, estimate_id: int) -> Optional[dict]:
    if not has_estimate_tables(conn):
        return None
    row = conn.execute("SELECT * FROM estimate_projects WHERE id = ?", (estimate_id,)).fetchone()
    return _project_dict(conn, row) if row is not None else None


def list_by_run(conn: sqlite3.Connection, run_ref: str) -> list[dict]:
    """Every estimate seeded for an analysis run (the left-track packages of a unified
    project, Phase 4)."""
    if not has_estimate_tables(conn) or not run_ref:
        return []
    rows = conn.execute("SELECT * FROM estimate_projects WHERE run_ref = ? ORDER BY id", (run_ref,)).fetchall()
    return [_project_dict(conn, r) for r in rows]


def find_by_route(conn: sqlite3.Connection, run_ref: str, package_key: str) -> Optional[dict]:
    """The estimate seeded for a routed package, if one exists (so route→estimate is
    idempotent — a package opens one estimate, not a new one per click)."""
    if not has_estimate_tables(conn) or not run_ref:
        return None
    row = conn.execute(
        "SELECT * FROM estimate_projects WHERE run_ref = ? AND package_key = ? ORDER BY id LIMIT 1",
        (run_ref, package_key),
    ).fetchone()
    return _project_dict(conn, row) if row is not None else None


def update_project(conn: sqlite3.Connection, estimate_id: int, patch: dict) -> Optional[dict]:
    """Patch known fields. status='closed' stamps closed_at; reopening ('draft') clears it.
    Raises ``ValueError`` on an out-of-vocabulary status. Returns the updated project or None."""
    ensure_estimate_tables(conn)
    if patch.get("status") is not None and patch["status"] not in _STATUSES:
        raise ValueError(f"unknown status {patch['status']!r} (use one of {_STATUSES})")
    if conn.execute("SELECT 1 FROM estimate_projects WHERE id = ?", (estimate_id,)).fetchone() is None:
        return None
    sets, params = [], []
    for field in _UPDATABLE:
        if field in patch and patch[field] is not None:
            sets.append(f"{field} = ?")
            params.append(patch[field])
    if "status" in patch and patch["status"] is not None:
        sets.append("closed_at = ?")
        params.append(_now() if patch["status"] == "closed" else None)
    if sets:
        params.append(estimate_id)
        conn.execute(f"UPDATE estimate_projects SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
    return get_project(conn, estimate_id)


# ---------------------------------------------------------------------------
# Items — rate-primary; the amount is only ever the computable qty·rate extension.
# ---------------------------------------------------------------------------
def _item_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "estimate_id": row["estimate_id"], "item_ref": row["item_ref"],
        "description": row["description"] or "", "unit": row["unit"] or "",
        "qty": row["qty"], "rate": row["rate"], "amount": row["amount"],
        "section": row["section"] or "", "source": row["source"] or "",
    }


def _insert_item(conn: sqlite3.Connection, estimate_id: int, it: dict, source: str) -> None:
    ref = (it.get("item_ref") or "").strip()
    if not ref:
        return
    amount = computable_amount(it.get("qty"), it.get("rate"), it.get("amount"))
    conn.execute(
        "INSERT INTO estimate_items (estimate_id, item_ref, description, unit, qty, rate, amount, section, "
        "source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (estimate_id, ref, it.get("description"), it.get("unit"), it.get("qty"), it.get("rate"),
         amount, it.get("section"), it.get("source") or source, _now()),
    )


def replace_items(conn: sqlite3.Connection, estimate_id: int, items: list[dict], *, source: str) -> list[dict]:
    """Replace the estimate's item list with ``items`` (rows with no item_ref skipped). Atomic."""
    ensure_estimate_tables(conn)
    try:
        conn.execute("DELETE FROM estimate_items WHERE estimate_id = ?", (estimate_id,))
        for it in items:
            _insert_item(conn, estimate_id, it, source)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return items_for(conn, estimate_id)


def add_items(conn: sqlite3.Connection, estimate_id: int, items: list[dict], *, source: str) -> list[dict]:
    """Append ``items`` to the estimate (rows with no item_ref skipped). Atomic."""
    ensure_estimate_tables(conn)
    try:
        for it in items:
            _insert_item(conn, estimate_id, it, source)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return items_for(conn, estimate_id)


def items_for(conn: sqlite3.Connection, estimate_id: int) -> list[dict]:
    if not has_estimate_tables(conn):
        return []
    rows = conn.execute("SELECT * FROM estimate_items WHERE estimate_id = ? ORDER BY id", (estimate_id,)).fetchall()
    return [_item_dict(r) for r in rows]


_ITEM_FIELDS = ("description", "unit", "qty", "rate", "section")


def update_item(conn: sqlite3.Connection, estimate_id: int, item_id: int, patch: dict) -> Optional[dict]:
    """Edit one line (the human prices: qty/rate/description/unit/section). Recomputes the
    computable amount. Returns the updated line, or None if it is not in the estimate."""
    ensure_estimate_tables(conn)
    row = conn.execute(
        "SELECT * FROM estimate_items WHERE id = ? AND estimate_id = ?", (item_id, estimate_id)
    ).fetchone()
    if row is None:
        return None
    merged = _item_dict(row)
    for f in _ITEM_FIELDS:
        if f in patch and patch[f] is not None:
            merged[f] = patch[f]
    amount = computable_amount(merged["qty"], merged["rate"], None)
    conn.execute(
        "UPDATE estimate_items SET description = ?, unit = ?, qty = ?, rate = ?, amount = ?, section = ? WHERE id = ?",
        (merged["description"], merged["unit"], merged["qty"], merged["rate"], amount, merged["section"], item_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM estimate_items WHERE id = ?", (item_id,)).fetchone()
    return _item_dict(updated)


def delete_item(conn: sqlite3.Connection, estimate_id: int, item_id: int) -> bool:
    ensure_estimate_tables(conn)
    cur = conn.execute("DELETE FROM estimate_items WHERE id = ? AND estimate_id = ?", (item_id, estimate_id))
    conn.commit()
    return cur.rowcount > 0
