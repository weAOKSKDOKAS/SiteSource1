"""Unified project spine (Phase P4a) — the run_ref umbrella, idempotent, benchmark link."""

import sqlite3
from pathlib import Path

import pytest

from db import project as uproject, seed, store


@pytest.fixture(scope="module")
def conns(tmp_path_factory):
    out = {}
    for profile in ("demo", "live"):
        path = tmp_path_factory.mktemp(f"up_{profile}") / f"{profile}.db"
        seed.build_database(path, profile=profile)
        out[profile] = store.get_connection(path)
    yield out
    for c in out.values():
        c.close()


def test_unified_table_exists_in_both_profiles(conns):
    for profile in ("demo", "live"):
        assert uproject.has_unified_table(conns[profile])


def test_get_or_create_is_idempotent_and_backfills_name(tmp_path):
    path = tmp_path / "u.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        assert uproject.get(conn, "run-1") is None
        a = uproject.get_or_create(conn, "run-1", name="")
        b = uproject.get_or_create(conn, "run-1", name="Kwun Tong Tower")   # same run -> same row, name backfilled
        assert a["id"] == b["id"] and b["name"] == "Kwun Tong Tower"
        assert len(uproject.list_projects(conn)) == 1
    finally:
        conn.close()


def test_link_benchmark_records_the_capture(tmp_path):
    path = tmp_path / "u2.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        uproject.get_or_create(conn, "run-2", name="R2")
        linked = uproject.link_benchmark(conn, "run-2", 7)
        assert linked["benchmark_project_id"] == 7
        assert uproject.link_benchmark(conn, "does-not-exist", 1) is None
    finally:
        conn.close()


def test_ensure_unified_table_matches_schema(tmp_path):
    a = sqlite3.connect(":memory:")
    a.executescript(Path("db/schema.sql").read_text())
    b = sqlite3.connect(":memory:")
    uproject.ensure_unified_table(b)
    ca = [(r[1], r[2], r[3]) for r in a.execute("PRAGMA table_info(unified_projects)")]
    cb = [(r[1], r[2], r[3]) for r in b.execute("PRAGMA table_info(unified_projects)")]
    assert ca == cb and ca
