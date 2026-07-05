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
        CREATE TABLE IF NOT EXISTS project_eos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id),
            narrative TEXT, summary TEXT, source_doc TEXT, has_images INTEGER NOT NULL DEFAULT 0,
            provenance TEXT NOT NULL DEFAULT 'live', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tender_items_project ON tender_items(project_id);
        CREATE INDEX IF NOT EXISTS idx_tender_items_ref     ON tender_items(item_ref);
        CREATE INDEX IF NOT EXISTS idx_actual_items_project ON actual_items(project_id);
        CREATE INDEX IF NOT EXISTS idx_actual_items_ref     ON actual_items(item_ref);
        CREATE INDEX IF NOT EXISTS idx_variance_project     ON variance_records(project_id);
        CREATE INDEX IF NOT EXISTS idx_variance_reason      ON variance_records(reason_code);
        CREATE INDEX IF NOT EXISTS idx_project_eos_project  ON project_eos(project_id);
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


_STATUSES = ("open", "closed")


def update_project(conn: sqlite3.Connection, project_id: int, patch: dict) -> Optional[dict]:
    """Patch the given fields (only known columns). Setting status='closed' stamps
    closed_at; reopening ('open') clears it. Returns the updated project, or None if
    unknown. Raises ``ValueError`` on an out-of-vocabulary status (so a bad value cannot
    enter the store or un-stamp closed_at)."""
    ensure_benchmark_tables(conn)
    if patch.get("status") is not None and patch["status"] not in _STATUSES:
        raise ValueError(f"unknown status {patch['status']!r} (use one of {_STATUSES})")
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


# ---------------------------------------------------------------------------
# Variance records — WRITTEN ONLY by the confirm gate (Layer 4). Variance math is
# Layer 1 (rules_engine.variance); this module only persists and reads.
# ---------------------------------------------------------------------------
def _variance_dict(row: sqlite3.Row) -> dict:
    keys = ("id", "project_id", "tender_item_id", "actual_item_id", "item_ref", "granularity",
            "match_tier", "tender_rate", "actual_rate", "tender_qty", "actual_qty",
            "tender_amount", "actual_amount", "rate_delta", "rate_delta_pct", "amount_delta",
            "amount_delta_qty", "amount_delta_rate", "reason_code", "reason_note", "tagged_by",
            "confirmed_at", "source")
    d = {k: row[k] for k in keys}
    d["item_ref"] = d["item_ref"] or ""
    d["reason_code"] = d["reason_code"] or ""
    d["reason_note"] = d["reason_note"] or ""
    d["tagged_by"] = d["tagged_by"] or ""
    return d


def confirm_matches(conn: sqlite3.Connection, project_id: int, confirmations: list[dict], *,
                    confirmed_by: str = "operator") -> list[dict]:
    """The ONLY writer of ``variance_records`` (the Layer-4 confirm gate). Each confirmation
    is ``{tender_item_id?, actual_item_id?, match_tier}``; the referenced items are resolved
    within the project, the rate-primary variance is computed (Layer 1), and one record is
    upserted per pair identity (re-confirming updates, never duplicates). Atomic. Returns the
    project's full variance table. Raises ``ValueError`` if an id is not in the project."""
    from rules_engine.variance import variance_between  # Layer 1; local import keeps the graph flat

    ensure_benchmark_tables(conn)
    tmap = {r["id"]: _item_dict(r) for r in conn.execute("SELECT * FROM tender_items WHERE project_id = ?", (project_id,))}
    amap = {r["id"]: _actual_dict(r) for r in conn.execute("SELECT * FROM actual_items WHERE project_id = ?", (project_id,))}
    try:
        for c in confirmations:
            tid, aid = c.get("tender_item_id"), c.get("actual_item_id")
            tier = int(c.get("match_tier") or 3)
            if tid and tid not in tmap:
                raise ValueError(f"tender_item {tid} is not in project {project_id}")
            if aid and aid not in amap:
                raise ValueError(f"actual_item {aid} is not in project {project_id}")
            tender = tmap.get(tid) if tid else None
            actual = amap.get(aid) if aid else None
            if tender is None and actual is None:
                continue
            v = variance_between(tender, actual)
            item_ref = ((tender or {}).get("item_ref") or (actual or {}).get("item_ref") or "")
            granularity = actual.get("granularity") if actual else "item"
            # Upsert by pair identity (NULL-safe via IS), so re-confirming a pair updates it.
            conn.execute(
                "DELETE FROM variance_records WHERE project_id = ? AND tender_item_id IS ? AND actual_item_id IS ?",
                (project_id, tid, aid),
            )
            conn.execute(
                "INSERT INTO variance_records (project_id, tender_item_id, actual_item_id, item_ref, granularity, "
                "match_tier, tender_rate, actual_rate, tender_qty, actual_qty, tender_amount, actual_amount, "
                "rate_delta, rate_delta_pct, amount_delta, amount_delta_qty, amount_delta_rate, "
                "confirmed_at, source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, tid, aid, item_ref, granularity, tier,
                 v["tender_rate"], v["actual_rate"], v["tender_qty"], v["actual_qty"],
                 v["tender_amount"], v["actual_amount"], v["rate_delta"], v["rate_delta_pct"],
                 v["amount_delta"], v["amount_delta_qty"], v["amount_delta_rate"], _now(), "confirm-gate", _now()),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return variance_records(conn, project_id)


def variance_records(conn: sqlite3.Connection, project_id: int) -> list[dict]:
    if not has_benchmark_tables(conn):
        return []
    rows = conn.execute("SELECT * FROM variance_records WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [_variance_dict(r) for r in rows]


def set_reason(conn: sqlite3.Connection, project_id: int, record_id: int, *,
               reason_code: str, note: str = "", tagged_by: str = "operator") -> Optional[dict]:
    """Set a variance record's reason (the human's code — required and validated). Returns
    the updated record, or None if the record is not in the project. Raises ``ValueError``
    on an unknown reason code."""
    ensure_benchmark_tables(conn)
    if reason_code not in REASON_CODE_SET:
        raise ValueError(f"unknown reason_code {reason_code!r}")
    row = conn.execute(
        "SELECT id FROM variance_records WHERE id = ? AND project_id = ?", (record_id, project_id)
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE variance_records SET reason_code = ?, reason_note = ?, tagged_by = ? WHERE id = ?",
        (reason_code, note, tagged_by, record_id),
    )
    conn.commit()
    rec = conn.execute("SELECT * FROM variance_records WHERE id = ?", (record_id,)).fetchone()
    return _variance_dict(rec)


# ---------------------------------------------------------------------------
# EOS narrative (Phase 2) — one per-project End-of-Site field report attached to a
# benchmark project. Narrative-only (reasons, never numbers); the reason still comes
# from a human confirm on variance_records. attach_eos replaces (one report per project).
# ---------------------------------------------------------------------------
def _has_project_eos_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='project_eos'"
    ).fetchone()
    return row is not None


def _eos_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "project_id": row["project_id"], "narrative": row["narrative"] or "",
        "summary": row["summary"] or "", "source_doc": row["source_doc"] or "",
        "has_images": bool(row["has_images"]), "provenance": row["provenance"] or "live",
        "created_at": row["created_at"] or "",
    }


def attach_eos(conn: sqlite3.Connection, project_id: int, *, narrative: str, summary: str = "",
               source_doc: str = "", has_images: bool = False, provenance: str = "live") -> dict:
    """Attach (or replace) the project's EOS narrative. One report per project — a
    re-upload replaces, never double-attaches. Atomic. Returns the stored record."""
    ensure_benchmark_tables(conn)
    try:
        conn.execute("DELETE FROM project_eos WHERE project_id = ?", (project_id,))
        conn.execute(
            "INSERT INTO project_eos (project_id, narrative, summary, source_doc, has_images, provenance, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, narrative, summary, source_doc, int(bool(has_images)), provenance, _now()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_eos(conn, project_id)


def get_eos(conn: sqlite3.Connection, project_id: int) -> Optional[dict]:
    """The project's EOS narrative, or None if none is attached (or the table predates
    Phase 2)."""
    if not _has_project_eos_table(conn):
        return None
    row = conn.execute(
        "SELECT * FROM project_eos WHERE project_id = ? ORDER BY id DESC LIMIT 1", (project_id,)
    ).fetchone()
    return _eos_dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Rate-precedent corpus (Phase 3) — the priced tender history the estimator prices
# against. All benchmark projects in THIS DB, each priced tender line left-joined to its
# confirmed variance (reason_code + rate movement). The DB profile is the gate: the demo
# DB carries the fictional demo project, the live DB is empty until a real archive lands.
# ---------------------------------------------------------------------------
def corpus_rate_rows(conn: sqlite3.Connection) -> list[dict]:
    """Priced tender lines across the benchmark corpus, each with the confirmed variance's
    ``reason_code`` and ``rate_delta`` (both null when the line was never matched/varied).
    Only rated lines (a rate-only precedent is meaningful; an unpriced line is not)."""
    if not has_benchmark_tables(conn):
        return []
    rows = conn.execute(
        "SELECT ti.item_ref AS item_ref, ti.description AS description, ti.rate AS tender_rate, "
        "ti.project_id AS project_id, vr.reason_code AS reason_code, vr.rate_delta AS rate_delta "
        "FROM tender_items ti LEFT JOIN variance_records vr ON vr.tender_item_id = ti.id "
        "WHERE ti.rate IS NOT NULL"
    ).fetchall()
    return [{
        "item_ref": r["item_ref"] or "", "description": r["description"] or "",
        "tender_rate": r["tender_rate"], "project_id": r["project_id"],
        "reason_code": r["reason_code"] or "", "rate_delta": r["rate_delta"],
    } for r in rows]


# ---------------------------------------------------------------------------
# Summary — counts the LIVE profile only (provenance='live'), never demo fixtures.
# ---------------------------------------------------------------------------
def summary(conn: sqlite3.Connection) -> dict:
    """Projects / record counts / coverage by trade and granularity across LIVE projects
    only. Demo-provenance projects (the pitch scenario) are excluded, so the live profile
    reads zero until real data lands."""
    empty = {"projects": 0, "tender_items": 0, "actual_items": 0, "variance_records": 0,
             "reasoned_records": 0, "coverage_by_trade": {}, "coverage_by_granularity": {}}
    if not has_benchmark_tables(conn):
        return empty
    live_ids = [r["id"] for r in conn.execute("SELECT id FROM projects WHERE provenance = 'live'")]
    if not live_ids:
        return empty
    placeholders = ",".join("?" * len(live_ids))

    def count(table: str, extra: str = "") -> int:
        return int(conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE project_id IN ({placeholders}) {extra}", live_ids
        ).fetchone()["n"])

    by_trade: dict[str, int] = {}
    for r in conn.execute(
        f"SELECT trade, COUNT(*) AS n FROM projects WHERE provenance = 'live' GROUP BY trade"
    ):
        by_trade[r["trade"] or ""] = int(r["n"])

    by_gran: dict[str, int] = {}
    for r in conn.execute(
        f"SELECT granularity, COUNT(*) AS n FROM variance_records WHERE project_id IN ({placeholders}) "
        f"GROUP BY granularity", live_ids
    ):
        by_gran[r["granularity"]] = int(r["n"])

    return {
        "projects": len(live_ids),
        "tender_items": count("tender_items"),
        "actual_items": count("actual_items"),
        "variance_records": count("variance_records"),
        "reasoned_records": count("variance_records", "AND reason_code IS NOT NULL"),
        "coverage_by_trade": by_trade,
        "coverage_by_granularity": by_gran,
    }
