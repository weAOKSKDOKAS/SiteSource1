"""Benchmark demo scenario + demo/live profile separation (Phase B1f).

The demo profile carries a fully-fictional GI variance story; the live profile ships with
empty benchmark tables. The demo must NEVER leak into live counts.
"""

import pytest

from db import benchmark, seed, store


@pytest.fixture(scope="module")
def demo_conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("bd_demo") / "demo.db"
    seed.build_database(path, profile="demo")
    conn = store.get_connection(path)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def live_conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("bd_live") / "live.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    yield conn
    conn.close()


def test_demo_profile_carries_the_fictional_project(demo_conn):
    projects = benchmark.list_projects(demo_conn)
    assert len(projects) == 1
    proj = projects[0]
    assert proj["name"].startswith("DEMO —") and proj["provenance"] == "demo"
    assert proj["tender_item_count"] == 4 and proj["actual_item_count"] == 5 and proj["variance_count"] == 5


def test_demo_variance_story_is_coherent_and_engine_computed(demo_conn):
    pid = benchmark.list_projects(demo_conn)[0]["id"]
    recs = {r["item_ref"]: r for r in benchmark.variance_records(demo_conn, pid)}
    # two standing_time rate over-runs + one omission_at_tender (the required shape)
    reasons = [r["reason_code"] for r in recs.values()]
    assert reasons.count("standing_time") == 2
    assert "omission_at_tender" in reasons
    # G1 is a pure rate over-run: 200@1200 -> 200@1500
    g1 = recs["G1"]
    assert g1["rate_delta"] == 300.0 and g1["amount_delta"] == 60000.0
    assert g1["amount_delta_rate"] == 60000.0 and g1["amount_delta_qty"] == 0.0
    assert g1["reason_code"] == "standing_time" and g1["source"] == "demo"
    # G5 is arrived-unpriced (no tender side) -> omission_at_tender
    g5 = recs["G5"]
    assert g5["tender_item_id"] is None and g5["actual_item_id"] is not None
    assert g5["reason_code"] == "omission_at_tender"


def test_summary_on_the_live_profile_is_zero(live_conn):
    # THE separation assertion: the live profile has no benchmark data.
    assert benchmark.list_projects(live_conn) == []
    s = benchmark.summary(live_conn)
    assert s == {"projects": 0, "tender_items": 0, "actual_items": 0, "variance_records": 0,
                 "reasoned_records": 0, "coverage_by_trade": {}, "coverage_by_granularity": {}}


def test_demo_scenario_never_leaks_into_summary(demo_conn):
    # The demo project is present (list) but excluded from summary (provenance='demo').
    assert benchmark.list_projects(demo_conn)  # present
    assert benchmark.summary(demo_conn)["projects"] == 0  # never counted
    assert benchmark.summary(demo_conn)["variance_records"] == 0


def test_reason_codes_seed_in_both_profiles(demo_conn, live_conn):
    for conn in (demo_conn, live_conn):
        assert len(benchmark.all_reason_codes(conn)) == 10


def test_rubric_items_empty_in_both_profiles(demo_conn, live_conn):
    for conn in (demo_conn, live_conn):
        assert conn.execute("SELECT COUNT(*) AS n FROM rubric_items").fetchone()["n"] == 0
