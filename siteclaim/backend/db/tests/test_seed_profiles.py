"""Phase C — the seed profile split (demo vs live).

'demo' (the default) is the 150-firm pitch database and must stay byte-for-byte
unchanged; 'live' is the clean engine database of only the 134 real public-register
firms, with none of the fabricated layer. Both are built into hermetic temp DBs so
the committed sitesource.db and the shared session DB are never touched.
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
    assert len(firms) == 134
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
    assert cov["total_firms"] == 134
    assert cov["flagged_firms"] == 46
    assert set(cov["flags_by_type"]) == {"debarment", "safety_prosecution", "winding_up"}
    assert store._meta(live_conn, "profile", "") == "live"


def test_live_include_public_shortlists_real_firms_default_is_empty(live_conn):
    trade = sorted({t for f in store.all_firms(live_conn) for t in f.trades})[0]
    public = cross_reference(live_conn, trade, "general building works", include_public=True)
    assert public  # the live engine can shortlist on the public screen
    assert all(not c.firm.firm_id.startswith("F-") for c in public)
    # default (assessed-firm) mode is intentionally empty in live: no EOS records exist
    assert cross_reference(live_conn, trade, "general building works") == []


def test_demo_profile_is_unchanged(demo_conn):
    assert len(store.all_firms(demo_conn)) == 150
    assert store._meta(demo_conn, "profile", "") == "demo"
    # the demo hero order is intact
    from db.tests.conftest import ELECTRICAL_SCOPE_QUERY

    order = [c.firm.firm_id for c in cross_reference(demo_conn, "electrical", ELECTRICAL_SCOPE_QUERY)]
    assert order == ["F-EL-02", "F-EL-04", "F-EL-03", "F-EL-01"]
    assert store.coverage(demo_conn)["total_firms"] == 134  # counts only real, both profiles


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
        assert len(store.all_firms(conn)) == 134
    finally:
        conn.close()

    # an explicit path always beats the env override
    conn2 = store.get_connection(demo)
    try:
        assert len(store.all_firms(conn2)) == 150
    finally:
        conn2.close()
