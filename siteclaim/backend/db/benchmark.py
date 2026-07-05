"""Benchmark estimator — data access over the SQLite benchmark tables (Layer 3).

Phase B1 (the variance spine): projects, tender_items, actual_items, variance_records,
reason_codes, rubric_items. This module is the single home for benchmark storage — reads
and the gated writes — mirroring ``db.store`` conventions (a plain connection with Row
access, JSON-tolerant, migration-guarded). Cost data is local SQLite only; nothing here
touches the network.

B1a lands the schema, the ten-code reason vocabulary, and the table/existence guard;
project/item CRUD, the matcher, and variance queries grow onto this module in B1b–B1d.
See ``docs/PRODUCT_ARCHITECTURE_benchmark_estimator.md``.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Optional

# The controlled ten-code reason vocabulary (§4). Seeded into EVERY profile — a vocabulary
# is not fabricated data. Order is the display order.
REASON_CODES: list[dict] = [
    {"code": "ground_conditions", "label": "Unforeseen ground conditions",
     "description": "Harder strata, rock or obstructions beyond what was tendered.", "category": "ground"},
    {"code": "standing_time", "label": "Standing time",
     "description": "Plant / rig standing idle (waiting, breakdown, or instruction).", "category": "time"},
    {"code": "weather", "label": "Inclement weather",
     "description": "Rain, typhoon or other weather standing.", "category": "time"},
    {"code": "access_restriction", "label": "Access restriction",
     "description": "Restricted or delayed access to the working area.", "category": "time"},
    {"code": "quantity_remeasure", "label": "Quantity remeasure",
     "description": "Remeasured quantity differs from the tendered quantity.", "category": "quantity"},
    {"code": "rate_reprice", "label": "Rate reprice",
     "description": "Rate corrected or renegotiated against the tendered rate.", "category": "rate"},
    {"code": "scope_variation", "label": "Scope variation",
     "description": "Client-instructed variation or additional scope.", "category": "scope"},
    {"code": "omission_at_tender", "label": "Omission at tender",
     "description": "Required on site but missing from (or not required by) the priced tender.", "category": "scope"},
    {"code": "additional_testing", "label": "Additional testing",
     "description": "Extra in-situ or laboratory testing instructed.", "category": "scope"},
    {"code": "provisional_sum_adjustment", "label": "Provisional sum adjustment",
     "description": "Provisional / prime-cost sum reconciled at final account.", "category": "commercial"},
]

REASON_CODE_SET: set[str] = {c["code"] for c in REASON_CODES}

_BENCHMARK_TABLES = ("projects", "tender_items", "actual_items", "variance_records", "reason_codes", "rubric_items")


def has_benchmark_tables(conn: sqlite3.Connection) -> bool:
    """True when the DB carries the benchmark tables (older DBs predate Phase B1).

    Mirrors ``store._has_contacts_table`` so a benchmark route degrades gracefully rather
    than crashing against a pre-B1 database."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name IN "
        "('projects','tender_items','actual_items','variance_records','reason_codes','rubric_items')"
    ).fetchone()
    return row is not None and int(row["n"]) == len(_BENCHMARK_TABLES)


def seed_reason_codes(conn: sqlite3.Connection) -> int:
    """Insert the ten reason codes (idempotent). Called at seed-build time for every
    profile. Returns the number of codes written."""
    for c in REASON_CODES:
        conn.execute(
            "INSERT OR REPLACE INTO reason_codes (code, label, description, category) VALUES (?, ?, ?, ?)",
            (c["code"], c["label"], c["description"], c["category"]),
        )
    return len(REASON_CODES)


def all_reason_codes(conn: sqlite3.Connection) -> list[dict]:
    """The reason vocabulary, in display order, for the UI dropdown."""
    if not has_benchmark_tables(conn):
        return []
    rows = conn.execute("SELECT code, label, description, category FROM reason_codes").fetchall()
    by_code = {r["code"]: dict(r) for r in rows}
    # Preserve the canonical display order; tolerate an unknown code from a future seed.
    ordered = [by_code[c["code"]] for c in REASON_CODES if c["code"] in by_code]
    ordered += [v for k, v in by_code.items() if k not in REASON_CODE_SET]
    return ordered


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Self-migrating guard — a benchmark WRITE creates the tables if this DB predates
# them (mirrors refresh._ensure_staging_tables), then seeds the reason vocabulary.
# ---------------------------------------------------------------------------
def ensure_benchmark_tables(conn: sqlite3.Connection) -> None:
    """Create the benchmark tables + indexes if missing (IF NOT EXISTS — never drops),
    then seed the reason codes. Called at the top of every benchmark write so a pre-B1
    database is upgraded in place without a full reseed."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, trade TEXT, client TEXT,
            contract_ref TEXT, status TEXT NOT NULL DEFAULT 'open',
            provenance TEXT NOT NULL DEFAULT 'live', source TEXT, notes TEXT,
            created_at TEXT NOT NULL, closed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tender_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
            item_ref TEXT NOT NULL, description TEXT, unit TEXT, qty REAL, rate REAL, amount REAL,
            section TEXT, source TEXT, source_doc TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS actual_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
            item_ref TEXT, description TEXT, unit TEXT, qty REAL, rate REAL, amount REAL, section TEXT,
            granularity TEXT NOT NULL DEFAULT 'item', source TEXT, source_doc TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reason_codes (
            code TEXT PRIMARY KEY, label TEXT NOT NULL, description TEXT, category TEXT
        );
        CREATE TABLE IF NOT EXISTS variance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
            tender_item_id INTEGER REFERENCES tender_items(id), actual_item_id INTEGER REFERENCES actual_items(id),
            item_ref TEXT, granularity TEXT NOT NULL DEFAULT 'item', match_tier INTEGER,
            tender_rate REAL, actual_rate REAL, tender_qty REAL, actual_qty REAL,
            tender_amount REAL, actual_amount REAL, rate_delta REAL, rate_delta_pct REAL,
            amount_delta REAL, amount_delta_qty REAL, amount_delta_rate REAL,
            reason_code TEXT REFERENCES reason_codes(code), reason_note TEXT,
            tagged_by TEXT, confirmed_at TEXT, source TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rubric_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, trade TEXT, item_ref TEXT, guidance TEXT,
            evidence_variance_id INTEGER REFERENCES variance_records(id), source TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tender_items_project ON tender_items(project_id);
        CREATE INDEX IF NOT EXISTS idx_tender_items_ref     ON tender_items(item_ref);
        CREATE INDEX IF NOT EXISTS idx_actual_items_project ON actual_items(project_id);
        CREATE INDEX IF NOT EXISTS idx_actual_items_ref     ON actual_items(item_ref);
        CREATE INDEX IF NOT EXISTS idx_variance_project     ON variance_records(project_id);
        CREATE INDEX IF NOT EXISTS idx_variance_reason      ON variance_records(reason_code);
        CREATE INDEX IF NOT EXISTS idx_projects_provenance  ON projects(provenance);
        """
    )
    seed_reason_codes(conn)


# ---------------------------------------------------------------------------
# Projects — CRUD (writes are gated to the confirm gate only for variance_records;
# project/item writes are ordinary operator actions on the active DB).
# ---------------------------------------------------------------------------
def _counts(conn: sqlite3.Connection, project_id: int) -> tuple[int, int, int]:
    def n(table: str) -> int:
        return int(conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE project_id = ?", (project_id,)).fetchone()["n"])
    return n("tender_items"), n("actual_items"), n("variance_records")


def _project_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    t, a, v = _counts(conn, row["id"])
    return {
        "id": row["id"], "name": row["name"], "trade": row["trade"] or "", "client": row["client"] or "",
        "contract_ref": row["contract_ref"] or "", "status": row["status"], "provenance": row["provenance"],
        "source": row["source"] or "", "notes": row["notes"] or "", "created_at": row["created_at"] or "",
        "closed_at": row["closed_at"] or "", "tender_item_count": t, "actual_item_count": a, "variance_count": v,
    }


def create_project(conn: sqlite3.Connection, *, name: str, trade: str = "", client: str = "",
                   contract_ref: str = "", notes: str = "", source: str = "manual",
                   provenance: str = "live") -> dict:
    """Create a project (default provenance 'live' — a real operator project). Demo-fixture
    projects are seeded separately with provenance 'demo' so they never enter live counts."""
    ensure_benchmark_tables(conn)
    cur = conn.execute(
        "INSERT INTO projects (name, trade, client, contract_ref, status, provenance, source, notes, created_at) "
        "VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)",
        (name, trade, client, contract_ref, provenance, source, notes, _now()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _project_dict(conn, row)


def list_projects(conn: sqlite3.Connection) -> list[dict]:
    if not has_benchmark_tables(conn):
        return []
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return [_project_dict(conn, r) for r in rows]


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[dict]:
    if not has_benchmark_tables(conn):
        return None
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_dict(conn, row) if row is not None else None


_UPDATABLE = ("name", "trade", "client", "contract_ref", "notes", "status")


def update_project(conn: sqlite3.Connection, project_id: int, patch: dict) -> Optional[dict]:
    """Patch the given fields (only known columns). Setting status='closed' stamps
    closed_at; reopening clears it. Returns the updated project, or None if unknown."""
    ensure_benchmark_tables(conn)
    if conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
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
        params.append(project_id)
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
    return get_project(conn, project_id)


# ---------------------------------------------------------------------------
# Tender snapshot (the priced tender). replace_tender_items overwrites the project's
# tender snapshot (re-uploading a corrected tender replaces, never double-counts).
# ---------------------------------------------------------------------------
def _item_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "project_id": row["project_id"], "item_ref": row["item_ref"],
        "description": row["description"] or "", "unit": row["unit"] or "",
        "qty": row["qty"], "rate": row["rate"], "amount": row["amount"],
        "section": row["section"] or "", "source": row["source"] or "", "source_doc": row["source_doc"] or "",
    }


def replace_tender_items(conn: sqlite3.Connection, project_id: int, items: list[dict], *,
                         source: str, source_doc: str = "") -> list[dict]:
    """Replace the project's tender snapshot with ``items`` (each: item_ref, description?,
    unit?, qty?, rate?, amount?, section?). Rows with no item_ref are skipped. Atomic."""
    ensure_benchmark_tables(conn)
    try:
        conn.execute("DELETE FROM tender_items WHERE project_id = ?", (project_id,))
        for it in items:
            ref = (it.get("item_ref") or "").strip()
            if not ref:
                continue
            conn.execute(
                "INSERT INTO tender_items (project_id, item_ref, description, unit, qty, rate, amount, section, "
                "source, source_doc, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, ref, it.get("description"), it.get("unit"), it.get("qty"), it.get("rate"),
                 it.get("amount"), it.get("section"), source, source_doc, _now()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return tender_items(conn, project_id)


def tender_items(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    if not has_benchmark_tables(conn):
        return []
    rows = conn.execute("SELECT * FROM tender_items WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [_item_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Actuals (the outturn). replace_actual_items overwrites the project's actuals.
# ---------------------------------------------------------------------------
def _actual_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "project_id": row["project_id"], "item_ref": row["item_ref"] or "",
        "description": row["description"] or "", "unit": row["unit"] or "",
        "qty": row["qty"], "rate": row["rate"], "amount": row["amount"],
        "section": row["section"] or "", "granularity": row["granularity"],
        "source": row["source"] or "", "source_doc": row["source_doc"] or "",
    }


def replace_actual_items(conn: sqlite3.Connection, project_id: int, items: list[dict], *,
                         source: str, source_doc: str = "") -> list[dict]:
    """Replace the project's actuals with ``items`` (each carries an explicit granularity:
    item | section | project). Item-granularity rows with no item_ref are skipped; coarse
    (section/project) rows are kept even without an item_ref. Atomic."""
    ensure_benchmark_tables(conn)
    try:
        conn.execute("DELETE FROM actual_items WHERE project_id = ?", (project_id,))
        for it in items:
            gran = it.get("granularity") or "item"
            ref = (it.get("item_ref") or "").strip()
            if gran == "item" and not ref:
                continue  # an item row must have a ref; coarse rows may not
            conn.execute(
                "INSERT INTO actual_items (project_id, item_ref, description, unit, qty, rate, amount, section, "
                "granularity, source, source_doc, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, ref or None, it.get("description"), it.get("unit"), it.get("qty"), it.get("rate"),
                 it.get("amount"), it.get("section"), gran, source, source_doc, _now()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return actual_items(conn, project_id)


def actual_items(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    if not has_benchmark_tables(conn):
        return []
    rows = conn.execute("SELECT * FROM actual_items WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [_actual_dict(r) for r in rows]
