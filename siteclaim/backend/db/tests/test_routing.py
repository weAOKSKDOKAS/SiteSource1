"""Routing gate storage (Phase P1a) — table + proposal round-trip + the confirm gate."""

import sqlite3

import pytest

from db import routing, seed, store


@pytest.fixture(scope="module")
def conns(tmp_path_factory):
    out = {}
    for profile in ("demo", "live"):
        path = tmp_path_factory.mktemp(f"route_{profile}") / f"{profile}.db"
        seed.build_database(path, profile=profile)
        out[profile] = store.get_connection(path)
    yield out
    for c in out.values():
        c.close()


def test_package_routes_table_exists_in_both_profiles(conns):
    assert routing.has_routing_table(conns["demo"])
    assert routing.has_routing_table(conns["live"])


def test_write_read_and_confirm_round_trip(tmp_path):
    path = tmp_path / "r.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        proposal = routing.write_proposal(conn, "ge-2026-14", [
            {"package_key": "ground_investigation", "trade": "ground_investigation",
             "scope_summary": "GI works", "recommended_route": "sublet",
             "rationale": "specialist trade with a live pool", "signals": {"trade_firm_count": 6}, "source": "route-suggest"},
            {"package_key": "electrical", "trade": "electrical", "recommended_route": "self_perform",
             "rationale": "strong in-house history", "signals": {"in_house_history": 3}, "source": "fallback"},
        ])
        assert len(proposal) == 2
        gi = next(p for p in proposal if p["package_key"] == "ground_investigation")
        assert gi["recommended_route"] == "sublet" and gi["signals"]["trade_firm_count"] == 6
        assert gi["chosen_route"] is None  # not decided yet

        # the confirm gate is the sole writer of chosen_route
        after = routing.confirm_decisions(conn, "ge-2026-14",
                                          {"ground_investigation": "sublet", "electrical": "self_perform"},
                                          decided_by="ops")
        gi2 = next(p for p in after if p["package_key"] == "ground_investigation")
        assert gi2["chosen_route"] == "sublet" and gi2["decided_by"] == "ops" and gi2["decided_at"]
    finally:
        conn.close()


def test_write_proposal_replaces_not_appends(tmp_path):
    path = tmp_path / "r2.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        routing.write_proposal(conn, "run1", [{"package_key": "a", "recommended_route": "sublet"}])
        again = routing.write_proposal(conn, "run1", [{"package_key": "b", "recommended_route": "self_perform"}])
        assert [p["package_key"] for p in again] == ["b"]  # replaced
    finally:
        conn.close()


def test_ensure_routing_table_matches_schema(tmp_path):
    # A migrated (IF NOT EXISTS) table must match the schema.sql definition column-for-column.
    a = sqlite3.connect(":memory:")
    from pathlib import Path

    a.executescript(Path("db/schema.sql").read_text())
    b = sqlite3.connect(":memory:")
    routing.ensure_routing_table(b)
    ca = [(r[1], r[2], r[3]) for r in a.execute("PRAGMA table_info(package_routes)")]
    cb = [(r[1], r[2], r[3]) for r in b.execute("PRAGMA table_info(package_routes)")]
    assert ca == cb
