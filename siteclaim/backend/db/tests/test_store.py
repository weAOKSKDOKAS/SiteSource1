"""The database loads and answers the queries the pipeline depends on."""

from db import store
from db.tests.conftest import ELECTRICAL_SCOPE_QUERY
from schemas.models import SignalType

_ELECTRICAL = {"F-EL-01", "F-EL-02", "F-EL-03", "F-EL-04"}


def test_db_loads_all_firms(conn):
    firms = store.all_firms(conn)
    assert len(firms) >= 12
    ids = {f.firm_id for f in firms}
    assert _ELECTRICAL <= ids  # the gotcha and the runner-up are both seeded


def test_at_least_four_trades_seeded(conn):
    trades = {t for firm in store.all_firms(conn) for t in firm.trades}
    assert "electrical" in trades
    assert len(trades) >= 4


def test_firms_for_trade_returns_the_seeded_firms(conn):
    electrical = store.firms_for_trade(conn, "electrical")
    ids = {f.firm_id for f in electrical}
    assert _ELECTRICAL <= ids
    assert all("electrical" in f.trades for f in electrical)


def test_firm_profile_carries_raw_public_signals(conn):
    gotcha = store.firm_profile(conn, "F-EL-01")
    assert gotcha is not None and gotcha.name == "Subcontractor E (illustrative)"
    signal_types = {ev.signal_type for flag in gotcha.public_flags for ev in flag.evidence}
    assert SignalType.WINDING_UP in signal_types
    assert SignalType.SAFETY_PROSECUTION in signal_types
    # a delayed closeout from the EOS surfaces as a raw closeout-performance signal
    assert SignalType.CLOSEOUT_PERFORMANCE in signal_types
    # every raw signal cites a reference
    assert all(ev.reference for flag in gotcha.public_flags for ev in flag.evidence)


def test_historical_pricing_band(conn):
    band = store.historical_pricing(conn, "electrical")
    assert band is not None
    low, median, high = band
    assert 0 < low <= median <= high


def test_coverage_counts_only_real_provenance(conn):
    cov = store.coverage(conn)
    assert cov["provenance"] == "public_register"
    # the illustrative demo firms are excluded from the public-register claim; the
    # total is the real CIC register (~1,366) plus the enforcement/offer overlay
    assert cov["total_firms"] == 1410
    assert cov["flagged_firms"] == 47
    # demo-only signal types (illustrative references) never appear in the claim
    assert "adjudication" not in cov["flags_by_type"]
    assert "distress_filing" not in cov["flags_by_type"]


def test_semantic_matches_are_electrical_and_in_range(conn):
    matches = store.semantic_closeout_matches(conn, ELECTRICAL_SCOPE_QUERY, "electrical", k=4)
    assert matches
    ids = {fid for fid, _ in matches}
    assert ids <= _ELECTRICAL  # never returns a firm from another trade
    assert all(0.0 <= score <= 1.0 for _, score in matches)
    # the clean runner-up's closeout text matches the electrical scope strongly
    assert "F-EL-02" in ids
