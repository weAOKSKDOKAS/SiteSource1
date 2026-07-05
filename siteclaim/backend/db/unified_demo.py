"""The baked unified-engine demo scenario (Phase P5b).

Seeded ONLY into the demo profile (like the benchmark/EOS layer), so the whole loop is
pitchable offline: one tender splits into packages, routing recommends and a human decides
(here overriding the recommendation on the GI package — the decision is the record of truth),
one package goes LEFT (a priced self-perform estimate whose lines match the benchmark corpus,
so rate precedent + standing-time warnings light up) and one goes RIGHT (sublet → the existing
sourcing pipeline), and the run is linked to the completed benchmark project (which carries the
EOS narrative explaining the variance). Everything is invented and provenance='demo', so it
never counts in any live surface. Pure inserts — no model, no network.
"""

from __future__ import annotations

import json
import sqlite3

RUN_REF = "demo-gi-fitout-tender"
NAME = "DEMO — Illustrative GI + Fit-out Tender"

# Routing proposal for the run: (package_key, trade, scope, recommended, chosen, rationale, signals).
# GI: the AI leaned sublet (specialist, thin in-house pool) but the human chose self-perform —
# the override demonstrates that the human decision is the record of truth. Electrical: sublet.
DEMO_ROUTES = [
    ("electrical", "electrical", "Landlord LV distribution and final circuits",
     "sublet", "sublet", "A deep pool of assessable electrical subcontractors — sublet for competitive tension.",
     {"trade_firm_count": 20, "assessable_firm_count": 6, "thin_pool": False, "in_house_history": 0}),
    ("ground_investigation", "ground_investigation", "Ground investigation — rotary drilling and in-situ testing",
     "sublet", "self_perform", "Specialist GI with a thin sub pool; the team chose to self-perform in-house.",
     {"trade_firm_count": 6, "assessable_firm_count": 2, "thin_pool": True, "in_house_history": 1}),
]

# The left-track estimate for the GI package — priced lines that match the benchmark corpus
# (G1/G2 carry standing_time history; G3 a quantity remeasure), so the estimator's rate
# precedent and "over-ran on rate" warnings light up on the demo profile.
DEMO_ESTIMATE_SCOPE = (
    "Self-perform the ground investigation package: mobilise a rotary rig, sink boreholes "
    "through soil and rock, carry out SPTs and undisturbed sampling, and reinstate on completion."
)
DEMO_ESTIMATE_ITEMS = [
    {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m", "qty": 210.0, "rate": 1250.0, "section": "A"},
    {"item_ref": "G2", "description": "Rotary drilling in rock", "unit": "m", "qty": 85.0, "rate": 1900.0, "section": "A"},
    {"item_ref": "G3", "description": "Standard penetration test (SPT)", "unit": "no", "qty": 60.0, "rate": 460.0, "section": "B"},
    {"item_ref": "G-MOB", "description": "Mobilisation and demobilisation of rig", "unit": "sum", "qty": None, "rate": None, "section": "A"},
]


def seed_unified_demo(conn: sqlite3.Connection, *, now: str, benchmark_project_id: int) -> str:
    """Seed the unified demo run (routing + a left estimate) and link it to the completed
    benchmark project. Returns the run_ref. Demo profile only."""
    conn.execute(
        "INSERT INTO unified_projects (run_ref, name, provenance, benchmark_project_id, created_at) "
        "VALUES (?, ?, 'demo', ?, ?)",
        (RUN_REF, NAME, benchmark_project_id, now),
    )

    for (pkey, trade, scope, recommended, chosen, rationale, signals) in DEMO_ROUTES:
        conn.execute(
            "INSERT INTO package_routes (run_ref, package_key, trade, scope_summary, recommended_route, "
            "rationale, signals, chosen_route, decided_by, decided_at, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'DEMO', ?, 'demo', ?)",
            (RUN_REF, pkey, trade, scope, recommended, rationale, json.dumps(signals), chosen, now, now),
        )

    cur = conn.execute(
        "INSERT INTO estimate_projects (name, trade, client, contract_ref, status, provenance, source, "
        "run_ref, package_key, scope_of_works, notes, created_at) "
        "VALUES (?, 'ground_investigation', ?, 'DEMO/GI/0001', 'submitted', 'demo', 'routing', ?, "
        "'ground_investigation', ?, 'Fully fictional demo estimate.', ?)",
        (f"{NAME} — ground investigation", "DEMO — Illustrative Developer", RUN_REF, DEMO_ESTIMATE_SCOPE, now),
    )
    est_id = cur.lastrowid
    for it in DEMO_ESTIMATE_ITEMS:
        amount = it["qty"] * it["rate"] if (it["qty"] is not None and it["rate"] is not None) else None
        conn.execute(
            "INSERT INTO estimate_items (estimate_id, item_ref, description, unit, qty, rate, amount, section, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scope-link', ?)",
            (est_id, it["item_ref"], it["description"], it["unit"], it["qty"], it["rate"], amount, it["section"], now),
        )
    return RUN_REF
