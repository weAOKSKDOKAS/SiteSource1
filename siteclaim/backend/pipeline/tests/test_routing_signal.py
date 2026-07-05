"""Routing Layer-1 signal (Phase P1b) — deterministic coverage inputs, offline."""

import pytest

from db import seed, store
from pipeline.routing.signal import THIN_POOL_THRESHOLD, package_signal


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    path = tmp_path_factory.mktemp("rsig") / "demo.db"
    seed.build_database(path, profile="demo")
    connection = store.get_connection(path)
    yield connection
    connection.close()


def test_signal_reports_pool_coverage_for_a_populated_trade(conn):
    sig = package_signal(conn, "electrical", "LV distribution")
    assert sig["trade"] == "electrical"
    assert sig["trade_firm_count"] >= 1
    assert sig["assessable_firm_count"] >= 1        # electrical has assessable firms in demo
    assert sig["has_sublet_pool"] is True
    assert sig["thin_pool"] is (sig["trade_firm_count"] < THIN_POOL_THRESHOLD)


def test_signal_is_deterministic(conn):
    assert package_signal(conn, "electrical") == package_signal(conn, "electrical")


def test_unknown_trade_has_no_pool(conn):
    sig = package_signal(conn, "underwater_basket_weaving")
    assert sig["trade_firm_count"] == 0 and sig["assessable_firm_count"] == 0
    assert sig["thin_pool"] is True and sig["has_sublet_pool"] is False


def test_in_house_history_is_zero_on_a_clean_live_profile(tmp_path):
    path = tmp_path / "live.db"
    seed.build_database(path, profile="live")
    c = store.get_connection(path)
    try:
        # the demo GI project is provenance='demo' and absent in live -> no in-house history
        assert package_signal(c, "ground_investigation")["in_house_history"] == 0
    finally:
        c.close()
