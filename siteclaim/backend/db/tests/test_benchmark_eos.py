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


def test_ensure_benchmark_tables_project_outcomes_matches_schema(tmp_path):
    # The tender-outcome's own slot must migrate to the same shape schema.sql builds — the same
    # parity guarantee project_eos already has.
    a = sqlite3.connect(":memory:")
    a.executescript(Path("db/schema.sql").read_text())
    b = sqlite3.connect(":memory:")
    bench.ensure_benchmark_tables(b)
    ca = [(r[1], r[2], r[3]) for r in a.execute("PRAGMA table_info(project_outcomes)")]
    cb = [(r[1], r[2], r[3]) for r in b.execute("PRAGMA table_info(project_outcomes)")]
    assert ca == cb and ca


# ---------------------------------------------------------------------------
# THE CROSSING TEST — the collision the suite was missing (both writers, one project).
# ---------------------------------------------------------------------------
# Before the fix, the tender-outcome feed wrote through `attach_eos`, so on any project that carried
# BOTH an operator's EoS document AND a fed tender outcome, whichever ran second DELETEd the other
# and `get_eos` returned the wrong kind — silently, and into the variance reason-suggestion path
# too. The outcome now lives in its own slot (`project_outcomes`); these prove the two coexist in
# BOTH orders and that each reader gets only its own kind.
def _crossing_project(conn) -> int:
    return bench.create_project(conn, name="Crossing test", trade="ground_investigation")["id"]


def _write_eos(conn, pid):
    return bench.attach_eos(conn, pid, narrative="EoS: rig stood idle during utility diversions.",
                            summary="Standing time", source_doc="eos.pdf")


def _write_outcome(conn, pid):
    return bench.attach_project_outcome(
        conn, pid, status="won", narrative="# Tender outcome: WON\n\nAwarded at HK$1.25m.",
        source_doc="tender-outcome")


@pytest.mark.parametrize("order", ["eos-then-outcome", "outcome-then-eos"])
def test_an_eos_and_a_tender_outcome_coexist_on_one_project(tmp_path, order):
    path = tmp_path / f"cross-{order}.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        pid = _crossing_project(conn)
        if order == "eos-then-outcome":
            _write_eos(conn, pid)
            _write_outcome(conn, pid)
        else:
            _write_outcome(conn, pid)
            _write_eos(conn, pid)

        # BOTH survive, and each reader gets ONLY its own kind — never the other's.
        eos = bench.get_eos(conn, pid)
        outcome = bench.get_project_outcome(conn, pid)
        assert eos is not None and outcome is not None, "neither clobbered the other"
        assert eos["source_doc"] == "eos.pdf" and "rig stood idle" in eos["narrative"]
        assert "Tender outcome" not in eos["narrative"], "the EoS reader never sees the outcome"
        assert outcome["source_doc"] == "tender-outcome" and outcome["status"] == "won"
        assert "utility diversions" not in outcome["narrative"], "the outcome reader never sees the EoS"

        # One row per slot per project — the one-report contract holds on BOTH slots.
        for table in ("project_eos", "project_outcomes"):
            n = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE project_id = ?", (pid,)).fetchone()["n"]
            assert n == 1, f"{table} kept exactly one row"
    finally:
        conn.close()


def test_re_uploading_an_eos_does_not_disturb_the_outcome(tmp_path):
    """The EoS-upload's own 'one report per project, a re-upload replaces' contract is intact — and
    replacing the EoS leaves the tender outcome exactly where it was."""
    path = tmp_path / "cross-reupload.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    try:
        pid = _crossing_project(conn)
        _write_outcome(conn, pid)
        bench.attach_eos(conn, pid, narrative="first EoS", source_doc="a.pdf")
        bench.attach_eos(conn, pid, narrative="second EoS", source_doc="b.pdf")

        assert bench.get_eos(conn, pid)["narrative"] == "second EoS", "EoS still replaces in place"
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM project_eos WHERE project_id = ?", (pid,)).fetchone()["n"] == 1
        assert bench.get_project_outcome(conn, pid)["status"] == "won", "the outcome is untouched"
    finally:
        conn.close()
