"""Phase C — the seed profile split (demo vs live).

Post-register (Prompt E), 'demo' (the default) is the full pitch database (the CIC
register + the enforcement overlay + the 16 illustrative firms with their fabricated
EOS layer); 'live' is the clean engine database of the register + overlay only, with
none of the fabricated layer. The real-provenance population is ~1,407 (the CIC
register merged with the enforcement overlay); demo adds the 16 illustrative firms
on top. Both profiles are built into hermetic temp DBs so the committed sitesource.db
and the shared session DB are never touched. Counts are asserted as ranges so a minor
register refresh does not break the suite.
"""

import pytest

from db import seed, store
from db.cross_reference import cross_reference


@pytest.fixture(scope="module")
def live_conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("live") / "live.db"
    seed.build_database(path, profile="live")
    conn = store.get_connection(path)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def demo_conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("demo") / "demo.db"
    seed.build_database(path, profile="demo")
    conn = store.get_connection(path)
    yield conn
    conn.close()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_live_profile_holds_only_real_firms(live_conn):
    firms = store.all_firms(live_conn)
    # live = the CIC register + the enforcement overlay (~1,407 today). Assert a range and
    # that it matches the coverage total (the same real-provenance population).
    assert 1350 <= len(firms) <= 1450
    assert len(firms) == store.coverage(live_conn)["total_firms"]
    assert not any(f.firm_id.startswith("F-") for f in firms)  # no illustrative stubs
    provenances = {row["provenance"] for row in live_conn.execute("SELECT provenance FROM firms")}
    assert provenances == {"public_register"}


def test_live_profile_drops_the_fabricated_layer(live_conn):
    assert _count(live_conn, "closeout_embeddings") == 0
    assert _count(live_conn, "project_closeouts") == 0
    assert _count(live_conn, "trade_pricing") == 0
    assert store.eos_firm_ids(live_conn) == set()
    assert store.all_contacts(live_conn) == []
    assert store.historical_pricing(live_conn, "electrical") is None  # recommend tolerates None


def test_live_profile_coverage_matches_the_demo_claim(live_conn):
    cov = store.coverage(live_conn)
    assert 1350 <= cov["total_firms"] <= 1450
    assert cov["flagged_firms"] == 46  # every enforcement-flagged firm survives the merge
    assert set(cov["flags_by_type"]) == {"debarment", "safety_prosecution", "winding_up"}
    assert store._meta(live_conn, "profile", "") == "live"


def test_live_include_public_shortlists_real_firms_default_is_empty(live_conn):
    trade = sorted({t for f in store.all_firms(live_conn) for t in f.trades})[0]
    public = cross_reference(live_conn, trade, "general building works", include_public=True)
    assert public  # the live engine can shortlist on the public screen
    assert all(not c.firm.firm_id.startswith("F-") for c in public)
    # default (assessed-firm) mode is intentionally empty in live: no EOS records exist
    assert cross_reference(live_conn, trade, "general building works") == []


def test_demo_profile_keeps_all_firms_and_the_hero(demo_conn):
    all_firms = store.all_firms(demo_conn)
    illustrative = [f for f in all_firms if f.firm_id.startswith("F-")]
    assert len(illustrative) == 16  # the fabricated layer is intact in demo
    # demo = the real register/overlay + the 16 illustrative firms; coverage counts real only.
    assert len(all_firms) == store.coverage(demo_conn)["total_firms"] + 16
    assert store._meta(demo_conn, "profile", "") == "demo"
    # the demo hero order is intact — the shortlist still draws from the illustrative
    # assessable firms (the register firms carry no EOS closeout record).
    from db.tests.conftest import ELECTRICAL_SCOPE_QUERY

    order = [c.firm.firm_id for c in cross_reference(demo_conn, "electrical", ELECTRICAL_SCOPE_QUERY)]
    assert order == ["F-EL-02", "F-EL-04", "F-EL-03", "F-EL-01"]
    assert 1350 <= store.coverage(demo_conn)["total_firms"] <= 1450  # counts only real, both profiles


def test_ground_investigation_is_register_backed_and_real(live_conn):
    # Post-register, ground investigation is a register specialty (of foundation/piling and
    # civil contractors) plus the curated GI specialists — many firms now, all real-provenance,
    # never illustrative. The specialty groupings the loader derives are present too.
    gi = [f for f in store.all_firms(live_conn) if "ground_investigation" in f.trades]
    assert len(gi) >= 6
    assert not any(f.firm_id.startswith("F-") for f in gi)  # verified-real only, no illustrative
    assert {row["provenance"] for row in live_conn.execute(
        "SELECT provenance FROM firms WHERE trades LIKE '%ground_investigation%'")} == {"public_register"}
    trades = {t for f in store.all_firms(live_conn) for t in f.trades}
    assert {"ground_investigation", "field_testing", "field_installations"} <= trades


def test_ground_investigation_shortlists_through_include_public(live_conn):
    from db.cross_reference import cross_reference

    query = "ground investigation boreholes rotary drilling sampling in-situ field testing"
    public = cross_reference(live_conn, "ground_investigation", query, include_public=True)
    assert {c.firm.firm_id for c in public} == {
        f.firm_id for f in store.all_firms(live_conn) if "ground_investigation" in f.trades
    }
    assert all(not c.recommended_against for c in public)  # clean — no invented flags
    # the assessed-firm default is empty: GI firms carry no EOS closeout record
    assert cross_reference(live_conn, "ground_investigation", query) == []


def test_invalid_profile_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        seed.build_database(tmp_path / "x.db", profile="nonsense")


def test_get_connection_honours_sitesource_db_env(tmp_path, monkeypatch):
    live = tmp_path / "live.db"
    seed.build_database(live, profile="live")
    demo = tmp_path / "demo.db"
    seed.build_database(demo, profile="demo")

    monkeypatch.setenv("SITESOURCE_DB", str(live))
    conn = store.get_connection()  # no arg -> env
    try:
        live_n = len(store.all_firms(conn))
        assert 1350 <= live_n <= 1450  # live = register + overlay
    finally:
        conn.close()

    # an explicit path always beats the env override; demo adds the 16 illustrative firms
    conn2 = store.get_connection(demo)
    try:
        assert len(store.all_firms(conn2)) == live_n + 16
    finally:
        conn2.close()
