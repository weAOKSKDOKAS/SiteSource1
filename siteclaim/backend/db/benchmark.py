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

import sqlite3

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
