"""Estimator storage (Phase P3a) — project/item CRUD, rate-primary rollup, schema parity."""

import sqlite3
from pathlib import Path

import pytest

from db import estimate as est, seed, store


@pytest.fixture(scope="module")
def conns(tmp_path_factory):
    out = {}
    for profile in ("demo", "live"):
        path = tmp_path_factory.mktemp(f"est_{profile}") / f"{profile}.db"
        seed.build_database(path, profile=profile)
        out[profile] = store.get_connection(path)
    yield out
    for c in out.values():
        c.close()


def test_estimate_tables_exist_in_both_profiles(conns):
    for profile in ("demo", "live"):
        assert est.has_estimate_tables(conns[profile])


def test_project_crud_and_status_lifecycle(tmp_path):
    path = tmp_path / "e.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        p = est.create_project(conn, name="Fit-out estimate", trade="joinery_fitting_out")
        assert p["status"] == "draft" and p["provenance"] == "live" and p["item_count"] == 0 and p["total"] is None
        pid = p["id"]
        assert any(x["id"] == pid for x in est.list_projects(conn))
        # close stamps closed_at; a bogus status is rejected
        closed = est.update_project(conn, pid, {"status": "closed"})
        assert closed["status"] == "closed" and closed["closed_at"]
        with pytest.raises(ValueError):
            est.update_project(conn, pid, {"status": "banana"})
        assert est.get_project(conn, 999999) is None
    finally:
        conn.close()


def test_items_rate_primary_rollup(tmp_path):
    path = tmp_path / "e2.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        pid = est.create_project(conn, name="P", trade="ground_investigation")["id"]
        est.replace_items(conn, pid, [
            {"item_ref": "G1", "description": "Drilling", "unit": "m", "qty": 100.0, "rate": 1200.0},
            {"item_ref": "G2", "description": "Rate-only SoR line", "unit": "m", "qty": None, "rate": 1500.0},
            {"item_ref": "G3", "description": "Unpriced", "unit": "no", "qty": 10.0, "rate": None},
            {"item_ref": "", "description": "no ref -> skipped"},
        ], source="scope-link")
        items = {i["item_ref"]: i for i in est.items_for(conn, pid)}
        assert set(items) == {"G1", "G2", "G3"}  # the ref-less row was skipped
        assert items["G1"]["amount"] == 120000.0        # qty*rate computed
        assert items["G2"]["amount"] is None            # rate-only -> no fabricated amount
        assert items["G3"]["amount"] is None            # unpriced -> none
        proj = est.get_project(conn, pid)
        assert proj["item_count"] == 3 and proj["priced_item_count"] == 2   # G1, G2 carry a rate
        assert proj["total"] == 120000.0                # only the computable amount contributes
    finally:
        conn.close()


def test_update_item_reprices_and_recomputes_amount(tmp_path):
    path = tmp_path / "e3.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        pid = est.create_project(conn, name="P")["id"]
        est.replace_items(conn, pid, [{"item_ref": "A1", "unit": "m", "qty": 50.0, "rate": None}], source="manual")
        item_id = est.items_for(conn, pid)[0]["id"]
        priced = est.update_item(conn, pid, item_id, {"rate": 200.0})
        assert priced["rate"] == 200.0 and priced["amount"] == 10000.0   # 50 * 200
        assert est.update_item(conn, pid, 999999, {"rate": 1.0}) is None  # unknown line
        assert est.get_project(conn, pid)["total"] == 10000.0
    finally:
        conn.close()


def test_find_by_route_is_idempotent_key(tmp_path):
    path = tmp_path / "e4.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        assert est.find_by_route(conn, "run-1", "electrical") is None
        p = est.create_project(conn, name="E", trade="electrical", source="routing",
                               run_ref="run-1", package_key="electrical")
        found = est.find_by_route(conn, "run-1", "electrical")
        assert found is not None and found["id"] == p["id"]
    finally:
        conn.close()


@pytest.mark.parametrize("table", ["estimate_projects", "estimate_items"])
def test_ensure_estimate_tables_match_schema(table):
    a = sqlite3.connect(":memory:")
    a.executescript(Path("db/schema.sql").read_text())
    b = sqlite3.connect(":memory:")
    est.ensure_estimate_tables(b)
    ca = [(r[1], r[2], r[3]) for r in a.execute(f"PRAGMA table_info({table})")]
    cb = [(r[1], r[2], r[3]) for r in b.execute(f"PRAGMA table_info({table})")]
    assert ca == cb and ca
