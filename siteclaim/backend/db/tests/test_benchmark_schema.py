"""Benchmark estimator (Phase B1a) — schema round-trip + the reason vocabulary.

Builds hermetic temp DBs (never the committed sitesource.db) and checks the six new
tables exist with their provenance columns, the ten reason codes seed in every profile,
rubric_items ships empty, and a project→tender→actual→variance chain round-trips.
"""

import pytest

from db import seed, store
from db.benchmark import REASON_CODES, has_benchmark_tables


@pytest.fixture(scope="module")
def live_conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("bench_live") / "live.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def demo_conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("bench_demo") / "demo.db"
    seed.build_database(path, profile="demo")
    conn = store.get_connection(path)
    yield conn
    conn.close()


def test_benchmark_tables_exist_in_both_profiles(live_conn, demo_conn):
    assert has_benchmark_tables(live_conn)
    assert has_benchmark_tables(demo_conn)


def test_reason_vocabulary_seeds_ten_codes_in_every_profile(live_conn, demo_conn):
    assert len(REASON_CODES) == 10
    for conn in (live_conn, demo_conn):
        codes = {r["code"] for r in conn.execute("SELECT code FROM reason_codes")}
        assert len(codes) == 10
        # the two codes the demo story leans on, plus a GI-specific one
        assert {"standing_time", "omission_at_tender", "ground_conditions"} <= codes


def test_rubric_items_ships_empty_in_both_profiles(live_conn, demo_conn):
    for conn in (live_conn, demo_conn):
        assert conn.execute("SELECT COUNT(*) AS n FROM rubric_items").fetchone()["n"] == 0


def test_provenance_and_granularity_columns_are_present(live_conn):
    proj_cols = {r["name"] for r in live_conn.execute("PRAGMA table_info(projects)")}
    assert {"provenance", "source", "created_at", "closed_at", "status"} <= proj_cols
    actual_cols = {r["name"] for r in live_conn.execute("PRAGMA table_info(actual_items)")}
    assert {"granularity", "source", "source_doc"} <= actual_cols
    var_cols = {r["name"] for r in live_conn.execute("PRAGMA table_info(variance_records)")}
    assert {"tagged_by", "confirmed_at", "amount_delta_qty", "amount_delta_rate", "match_tier"} <= var_cols


def test_project_tender_actual_variance_round_trips(tmp_path):
    import sqlite3

    path = tmp_path / "rt.db"
    seed.build_database(path, profile="live")
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "INSERT INTO projects (name, trade, provenance, source, created_at) VALUES (?, ?, ?, ?, ?)",
            ("RT project", "ground_investigation", "live", "manual", "2026-07-05T00:00:00Z"),
        )
        pid = conn.execute("SELECT id FROM projects").fetchone()["id"]
        conn.execute(
            "INSERT INTO tender_items (project_id, item_ref, description, unit, qty, rate, section, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, "A1a(a)", "Rotary drilling", "m", 100.0, 1200.0, "A", "tender-xlsx", "2026-07-05T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO actual_items (project_id, item_ref, qty, rate, granularity, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, "A1a(a)", 120.0, 1300.0, "item", "actuals-xlsx", "2026-07-05T00:00:00Z"),
        )
        ti = conn.execute("SELECT id FROM tender_items").fetchone()["id"]
        ai = conn.execute("SELECT id FROM actual_items").fetchone()["id"]
        conn.execute(
            "INSERT INTO variance_records (project_id, tender_item_id, actual_item_id, item_ref, match_tier, "
            "rate_delta, reason_code, tagged_by, confirmed_at, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, ti, ai, "A1a(a)", 1, 100.0, "standing_time", "operator", "2026-07-05T00:00:00Z", "confirm-gate", "2026-07-05T00:00:00Z"),
        )
        conn.commit()

        rec = conn.execute("SELECT * FROM variance_records").fetchone()
        assert rec["item_ref"] == "A1a(a)" and rec["match_tier"] == 1
        assert rec["rate_delta"] == 100.0 and rec["reason_code"] == "standing_time"
        assert rec["tagged_by"] == "operator" and rec["source"] == "confirm-gate"
        # the FK to reason_codes resolves
        label = conn.execute(
            "SELECT rc.label FROM variance_records v JOIN reason_codes rc ON rc.code = v.reason_code"
        ).fetchone()["label"]
        assert label == "Standing time"
    finally:
        conn.close()
