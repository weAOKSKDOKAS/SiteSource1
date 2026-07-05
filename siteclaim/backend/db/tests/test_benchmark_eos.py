"""EOS narrative storage (Phase P2a) — attach/get round-trip, replace, schema parity."""

import sqlite3
from pathlib import Path

import pytest

from db import benchmark as bench, seed, store


@pytest.fixture(scope="module")
def conns(tmp_path_factory):
    out = {}
    for profile in ("demo", "live"):
        path = tmp_path_factory.mktemp(f"eos_{profile}") / f"{profile}.db"
        seed.build_database(path, profile=profile)
        out[profile] = store.get_connection(path)
    yield out
    for c in out.values():
        c.close()


def test_project_eos_table_exists_in_both_profiles(conns):
    for profile in ("demo", "live"):
        assert bench._has_project_eos_table(conns[profile])


def _new_live_project(conn) -> int:
    return bench.create_project(conn, name="EOS test", trade="ground_investigation")["id"]


def test_attach_and_get_round_trip(tmp_path):
    path = tmp_path / "e.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        pid = _new_live_project(conn)
        assert bench.get_eos(conn, pid) is None  # none attached yet
        stored = bench.attach_eos(
            conn, pid, narrative="Rig stood idle during utility diversions.",
            summary="Standing time drove the drilling rates up.", source_doc="eos.pdf",
            has_images=True, provenance="live",
        )
        assert stored["narrative"].startswith("Rig stood idle")
        assert stored["summary"] and stored["has_images"] is True and stored["provenance"] == "live"
        got = bench.get_eos(conn, pid)
        assert got["id"] == stored["id"] and got["source_doc"] == "eos.pdf"
    finally:
        conn.close()


def test_attach_replaces_not_appends(tmp_path):
    path = tmp_path / "e2.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        pid = _new_live_project(conn)
        bench.attach_eos(conn, pid, narrative="first")
        bench.attach_eos(conn, pid, narrative="second")
        assert bench.get_eos(conn, pid)["narrative"] == "second"
        assert conn.execute("SELECT COUNT(*) AS n FROM project_eos WHERE project_id = ?", (pid,)).fetchone()["n"] == 1
    finally:
        conn.close()


def test_ensure_benchmark_tables_project_eos_matches_schema(tmp_path):
    # The migrated (IF NOT EXISTS) project_eos must match schema.sql column-for-column.
    a = sqlite3.connect(":memory:")
    a.executescript(Path("db/schema.sql").read_text())
    b = sqlite3.connect(":memory:")
    bench.ensure_benchmark_tables(b)
    ca = [(r[1], r[2], r[3]) for r in a.execute("PRAGMA table_info(project_eos)")]
    cb = [(r[1], r[2], r[3]) for r in b.execute("PRAGMA table_info(project_eos)")]
    assert ca == cb and ca  # non-empty and identical
