"""Baked demo benchmark corpus for the golden scenario's self-perform trades (Prompt A).

The golden walkthrough routes Fire Services and Joinery & Fitting-out to self-perform, so
their routed estimates must open with real rate precedent rather than an empty skeleton.
This module seeds a completed, clearly-fictional benchmark project for each — a tender
snapshot, the outturn actuals, confirmed variance records, and an EOS field report — using
the SAME item_refs as the clean / Kwun Tong scope packages (F-01..F-03, J-01..J-04). So
when the estimator retrieves precedent (Tier-1 exact ``item_ref``), every line matches and
shows the historical rate band; exactly one line per trade over-ran on RATE (a rate-moving
reason code with a non-zero rate delta) so the "over-ran on rate" warning fires on one line.

Seeded ONLY into the demo profile, the same way as ``benchmark_demo`` (the GI demo): every
project carries ``provenance='demo'`` so it never counts in ``/benchmark/summary`` (which
sums ``provenance='live'`` only). Variance is computed by the Layer-1 engine, so the numbers
are exactly what the real math produces. Nothing is pre-priced — the precedent guides the
human, who prices every line. No model calls, no network — pure inserts.
"""

from __future__ import annotations

import sqlite3

# One completed project per self-perform trade. Each line is
# (item_ref, description, unit, tender_qty, tender_rate, actual_qty, actual_rate, reason, note).
# ``rate`` (tender_rate) is the precedent the estimator retrieves; the actual side drives the
# confirmed variance. ``reason`` is set only where the line genuinely moved: one rate over-run
# per trade (the "over-ran on rate" warning) plus a quantity remeasure (a precedent with no
# rate warning, since its rate held) — the rest ran to the tendered rate.
GOLDEN_PROJECTS = [
    {
        "project": {
            "name": "DEMO — Illustrative Fire Services Installation",
            "trade": "fire_services",
            "client": "DEMO — Illustrative Property Developer",
            "contract_ref": "DEMO/FS/0000",
            "notes": "Fully fictional pitch scenario — a completed fire-services package kept "
                     "as rate precedent for the self-perform estimator. Not a real contract.",
        },
        "lines": [
            ("F-01", "Sprinkler heads and pipework", "no", 1180.0, 2300.0, 1180.0, 2300.0, "", ""),
            ("F-02", "Fire detection and alarm devices", "no", 395.0, 1850.0, 395.0, 2150.0,
             "access_restriction",
             "Detection and alarm devices were installed out of hours in tenanted areas; the "
             "restricted access pushed the achieved rate above the tendered rate."),
            ("F-03", "Hydrants and hose reels", "no", 34.0, 9000.0, 40.0, 9000.0,
             "quantity_remeasure",
             "Additional hose reels were remeasured against the revised floor plate; the rate held."),
        ],
        "eos_summary": (
            "Fire detection and alarm devices over-ran on rate (restricted out-of-hours access in "
            "tenanted areas); additional hose reels were remeasured; the sprinkler installation ran "
            "to the tendered rate."
        ),
        "eos_narrative": (
            "The fire detection and alarm devices were installed out of hours in tenanted areas, and "
            "the restricted access lifted the achieved rate above the tendered rate. "
            "Additional hose reels were remeasured against the revised floor plate, at the tendered rate. "
            "The sprinkler heads and pipework were installed to programme at the tendered rate."
        ),
    },
    {
        "project": {
            "name": "DEMO — Illustrative Fit-out Joinery Package",
            "trade": "joinery_fitting_out",
            "client": "DEMO — Illustrative Property Developer",
            "contract_ref": "DEMO/JF/0000",
            "notes": "Fully fictional pitch scenario — a completed fit-out joinery package kept "
                     "as rate precedent for the self-perform estimator. Not a real contract.",
        },
        "lines": [
            ("J-01", "Demountable partitions", "m2", 880.0, 1400.0, 880.0, 1400.0, "", ""),
            ("J-02", "Suspended ceilings", "m2", 2950.0, 760.0, 3080.0, 760.0,
             "quantity_remeasure",
             "Ceiling area was remeasured up against the revised reflected-ceiling plan; the rate held."),
            ("J-03", "Doors and ironmongery", "no", 138.0, 7600.0, 138.0, 7600.0, "", ""),
            ("J-04", "Bespoke joinery — reception and tea rooms", "item", 1.0, 760000.0, 1.0, 860000.0,
             "rate_reprice",
             "The reception feature joinery was repriced above the tendered rate once the veneer "
             "and stone selections were confirmed."),
        ],
        "eos_summary": (
            "Reception feature joinery was repriced above tender (veneer and stone selections); "
            "the ceiling area was remeasured up; partitions, doors and ironmongery ran to the "
            "tendered rates."
        ),
        "eos_narrative": (
            "The reception feature joinery was repriced above the tendered rate once the veneer and "
            "stone selections were confirmed. "
            "The suspended ceiling area was remeasured up against the revised reflected-ceiling plan, "
            "at the tendered rate. "
            "The demountable partitions, doors and ironmongery were installed to the tendered rates."
        ),
    },
]


def seed_golden_benchmark(conn: sqlite3.Connection, *, now: str) -> list[int]:
    """Seed the golden self-perform corpus (Fire Services + Joinery) — one completed demo
    benchmark project per trade with tender, outturn actuals, confirmed variance records and
    an EOS narrative, keyed to the clean scope packages' item_refs. Demo profile only.
    ``now`` is passed in (the seed already stamps a build time) so the module stays pure.
    Returns the created project ids."""
    from rules_engine.variance import variance_between

    pids: list[int] = []
    for spec in GOLDEN_PROJECTS:
        p = spec["project"]
        cur = conn.execute(
            "INSERT INTO projects (name, trade, client, contract_ref, status, provenance, source, notes, created_at, closed_at) "
            "VALUES (?, ?, ?, ?, 'closed', 'demo', 'demo', ?, ?, ?)",
            (p["name"], p["trade"], p["client"], p["contract_ref"], p["notes"], now, now),
        )
        pid = cur.lastrowid
        pids.append(pid)

        for (ref, desc, unit, tqty, trate, aqty, arate, reason, note) in spec["lines"]:
            tc = conn.execute(
                "INSERT INTO tender_items (project_id, item_ref, description, unit, qty, rate, amount, section, source, source_doc, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'A', 'demo', 'DEMO tender', ?)",
                (pid, ref, desc, unit, tqty, trate, tqty * trate, now),
            )
            tender_item_id = tc.lastrowid
            ac = conn.execute(
                "INSERT INTO actual_items (project_id, item_ref, description, unit, qty, rate, amount, section, granularity, source, source_doc, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'A', 'item', 'demo', 'DEMO final account', ?)",
                (pid, ref, desc, unit, aqty, arate, aqty * arate, now),
            )
            actual_item_id = ac.lastrowid

            v = variance_between({"qty": tqty, "rate": trate}, {"qty": aqty, "rate": arate})
            conn.execute(
                "INSERT INTO variance_records (project_id, tender_item_id, actual_item_id, item_ref, granularity, match_tier, "
                "tender_rate, actual_rate, tender_qty, actual_qty, tender_amount, actual_amount, rate_delta, rate_delta_pct, "
                "amount_delta, amount_delta_qty, amount_delta_rate, reason_code, reason_note, tagged_by, confirmed_at, source, created_at) "
                "VALUES (?, ?, ?, ?, 'item', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'demo', ?)",
                (pid, tender_item_id, actual_item_id, ref,
                 v["tender_rate"], v["actual_rate"], v["tender_qty"], v["actual_qty"], v["tender_amount"], v["actual_amount"],
                 v["rate_delta"], v["rate_delta_pct"], v["amount_delta"], v["amount_delta_qty"], v["amount_delta_rate"],
                 reason or None, note or None, ("DEMO" if reason else None), now, now),
            )

        conn.execute(
            "INSERT INTO project_eos (project_id, narrative, summary, source_doc, has_images, provenance, created_at) "
            "VALUES (?, ?, ?, ?, 1, 'demo', ?)",
            (pid, spec["eos_narrative"], spec["eos_summary"], "DEMO EOS field report.pdf", now),
        )
    return pids
