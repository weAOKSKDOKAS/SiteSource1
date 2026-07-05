"""The baked, clearly-fictional demo benchmark scenario (Phase B1f).

Seeded ONLY into the demo profile (like the fabricated EOS/pricing layer), so the flow can
be pitched offline before any real archive exists. Everything here is invented and named so
it cannot be mistaken for real; the project carries ``provenance='demo'`` so it never counts
in ``/benchmark/summary`` (which sums ``provenance='live'`` only). The live profile ships
with empty benchmark tables. No model calls, no network — pure inserts, variance computed by
the Layer-1 engine so the demo numbers are exactly what the real math produces.
"""

from __future__ import annotations

import sqlite3

DEMO_PROJECT = {
    "name": "DEMO — Illustrative GI Term Contract",
    "trade": "ground_investigation",
    "client": "DEMO — Illustrative Works Bureau",
    "contract_ref": "DEMO/GI/0000",
    "notes": "Fully fictional pitch scenario — not a real contract. Illustrates the "
             "tender-vs-outturn variance flow before any real archive exists.",
}

# Priced tender snapshot (fictional GI Schedule of Rates).
DEMO_TENDER = [
    {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m", "qty": 200.0, "rate": 1200.0, "section": "A"},
    {"item_ref": "G2", "description": "Rotary drilling in rock", "unit": "m", "qty": 80.0, "rate": 1800.0, "section": "A"},
    {"item_ref": "G3", "description": "Standard penetration test (SPT)", "unit": "no", "qty": 60.0, "rate": 450.0, "section": "B"},
    {"item_ref": "G4", "description": "Undisturbed sample (U100)", "unit": "no", "qty": 40.0, "rate": 550.0, "section": "B"},
]

# Actual outturn (fictional). G1/G2 over-ran on rate (rig standing); G3 remeasured up; G4 as
# tendered; G5 arrived with no tender line (an omission at tender).
DEMO_ACTUALS = [
    {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m", "qty": 200.0, "rate": 1500.0, "section": "A", "granularity": "item"},
    {"item_ref": "G2", "description": "Rotary drilling in rock", "unit": "m", "qty": 80.0, "rate": 2100.0, "section": "A", "granularity": "item"},
    {"item_ref": "G3", "description": "Standard penetration test (SPT)", "unit": "no", "qty": 65.0, "rate": 450.0, "section": "B", "granularity": "item"},
    {"item_ref": "G4", "description": "Undisturbed sample (U100)", "unit": "no", "qty": 40.0, "rate": 550.0, "section": "B", "granularity": "item"},
    {"item_ref": "G5", "description": "Obstruction removal (unforeseen)", "unit": "item", "qty": 15.0, "rate": 2000.0, "section": "A", "granularity": "item"},
]

# Pre-confirmed matches with tagged reasons: (tender_ref, actual_ref, tier, reason, note).
DEMO_PAIRS = [
    ("G1", "G1", 1, "standing_time", "Rig standing during utility diversions pushed the rate up."),
    ("G2", "G2", 1, "standing_time", "Rig standing awaiting rock-coring instruction."),
    ("G3", "G3", 1, "quantity_remeasure", "Five extra SPTs remeasured on site."),
    ("G4", "G4", 1, "", ""),                                   # confirmed but left untagged (needs a reason)
    (None, "G5", 3, "omission_at_tender", "Obstruction removal not priced in the tender."),
]

# The fictional End-of-Site (EOS) field report for the demo project (Phase 2) — the
# narrative account of WHY the prices moved. Its sentences are the evidence the reason
# extractor quotes: G1/G2 standing time, G3 remeasure, G5 an unpriced obstruction. It
# supplies reasons, never numbers (the cost figures come from the tender/actuals above).
# Fully fictional, provenance='demo' — it never reads as live.
DEMO_EOS_SUMMARY = (
    "Rig standing time (utility diversions, then awaiting the rock-coring instruction) drove the "
    "drilling rate over-runs; five extra SPTs were remeasured; an unforeseen obstruction was "
    "removed as an item not priced in the tender."
)
DEMO_EOS_NARRATIVE = (
    "The rotary drilling rig stood idle for extended periods while utility diversions were "
    "completed, which pushed the achieved rate for the soil drilling item above the tendered rate. "
    "The rig also stood waiting for the Engineer's instruction to core into rock, raising the rock "
    "drilling rate over the tendered rate. "
    "Ground conditions were otherwise broadly as anticipated. "
    "Five additional standard penetration tests were instructed and remeasured on site beyond the "
    "tendered quantity. "
    "During excavation an unforeseen obstruction was encountered that required removal; this work "
    "was not priced in the tender and was carried out as an additional item. "
    "Weather standing over the contract period was minimal."
)


def seed_demo_benchmark(conn: sqlite3.Connection, *, now: str) -> int:
    """Insert the fictional demo project, tender, actuals and tagged variance records.
    ``now`` is passed in (the seed already stamps a build time) so the module stays pure."""
    from rules_engine.variance import variance_between

    cur = conn.execute(
        "INSERT INTO projects (name, trade, client, contract_ref, status, provenance, source, notes, created_at, closed_at) "
        "VALUES (?, ?, ?, ?, 'closed', 'demo', 'demo', ?, ?, ?)",
        (DEMO_PROJECT["name"], DEMO_PROJECT["trade"], DEMO_PROJECT["client"], DEMO_PROJECT["contract_ref"],
         DEMO_PROJECT["notes"], now, now),
    )
    pid = cur.lastrowid

    tender_ids: dict[str, int] = {}
    for it in DEMO_TENDER:
        c = conn.execute(
            "INSERT INTO tender_items (project_id, item_ref, description, unit, qty, rate, amount, section, source, source_doc, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'demo', 'DEMO tender', ?)",
            (pid, it["item_ref"], it["description"], it["unit"], it["qty"], it["rate"],
             it["qty"] * it["rate"], it["section"], now),
        )
        tender_ids[it["item_ref"]] = c.lastrowid

    actual_ids: dict[str, int] = {}
    for it in DEMO_ACTUALS:
        c = conn.execute(
            "INSERT INTO actual_items (project_id, item_ref, description, unit, qty, rate, amount, section, granularity, source, source_doc, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo', 'DEMO final account', ?)",
            (pid, it["item_ref"], it["description"], it["unit"], it["qty"], it["rate"],
             it["qty"] * it["rate"], it["section"], it["granularity"], now),
        )
        actual_ids[it["item_ref"]] = c.lastrowid

    tmap = {it["item_ref"]: it for it in DEMO_TENDER}
    amap = {it["item_ref"]: it for it in DEMO_ACTUALS}
    for (tref, aref, tier, reason, note) in DEMO_PAIRS:
        tender = tmap.get(tref)
        actual = amap.get(aref)
        v = variance_between(tender, actual)
        gran = (actual or {}).get("granularity", "item")
        conn.execute(
            "INSERT INTO variance_records (project_id, tender_item_id, actual_item_id, item_ref, granularity, match_tier, "
            "tender_rate, actual_rate, tender_qty, actual_qty, tender_amount, actual_amount, rate_delta, rate_delta_pct, "
            "amount_delta, amount_delta_qty, amount_delta_rate, reason_code, reason_note, tagged_by, confirmed_at, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo', ?)",
            (pid, tender_ids.get(tref), actual_ids.get(aref), (tref or aref), gran, tier,
             v["tender_rate"], v["actual_rate"], v["tender_qty"], v["actual_qty"], v["tender_amount"], v["actual_amount"],
             v["rate_delta"], v["rate_delta_pct"], v["amount_delta"], v["amount_delta_qty"], v["amount_delta_rate"],
             reason or None, note or None, ("DEMO" if reason else None), now, now),
        )

    # The per-project EOS field report (Phase 2) — the narrative that explains WHY each line
    # moved. provenance='demo'; has_images=1 (a real field report carries site photos, noted
    # but never parsed for numbers).
    conn.execute(
        "INSERT INTO project_eos (project_id, narrative, summary, source_doc, has_images, provenance, created_at) "
        "VALUES (?, ?, ?, ?, 1, 'demo', ?)",
        (pid, DEMO_EOS_NARRATIVE, DEMO_EOS_SUMMARY, "DEMO EOS field report.pdf", now),
    )
    return pid
