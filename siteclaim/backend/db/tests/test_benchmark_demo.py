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


def _gi_project(conn):
    """The GI demo project — selected by trade, since the demo profile now also carries the
    golden scenario's self-perform corpus (Fire Services + Joinery), and list_projects is id-desc."""
    return next(p for p in benchmark.list_projects(conn) if p["trade"] == "ground_investigation")


def test_demo_profile_carries_the_fictional_project(demo_conn):
    projects = benchmark.list_projects(demo_conn)
    # the GI demo plus the golden scenario's two self-perform corpus projects (Fire, Joinery)
    assert len(projects) == 3
    assert all(p["provenance"] == "demo" for p in projects)
    proj = _gi_project(demo_conn)
    assert proj["name"].startswith("DEMO —")
    assert proj["tender_item_count"] == 4 and proj["actual_item_count"] == 5 and proj["variance_count"] == 5


def test_demo_variance_story_is_coherent_and_engine_computed(demo_conn):
    pid = _gi_project(demo_conn)["id"]
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


def test_demo_project_carries_a_fictional_eos_narrative(demo_conn):
    # Phase 2: the demo project has an attached EOS field report (provenance='demo') whose
    # sentences are the evidence for the reason candidates.
    pid = _gi_project(demo_conn)["id"]
    eos = benchmark.get_eos(demo_conn, pid)
    assert eos is not None and eos["provenance"] == "demo" and eos["has_images"] is True
    assert eos["narrative"].startswith("The rotary drilling rig stood idle")
    assert "not priced in the tender" in eos["narrative"]  # the G5 omission evidence
    assert eos["summary"]


def test_live_profile_ships_no_eos(live_conn):
    # The clean live profile carries no fabricated EOS narrative.
    assert live_conn.execute("SELECT COUNT(*) AS n FROM project_eos").fetchone()["n"] == 0


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
