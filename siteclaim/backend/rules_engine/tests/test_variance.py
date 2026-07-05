"""Rate-primary variance math (Phase B1d) — decomposition, rate-only, and unmatched."""

from rules_engine.variance import computable_amount, variance_between


def _t(qty=None, rate=None, amount=None):
    return {"qty": qty, "rate": rate, "amount": amount}


def test_full_boq_pair_decomposes_exactly():
    # tender 100 @ 1200 = 120,000 ; actual 120 @ 1300 = 156,000
    v = variance_between(_t(100, 1200, 120000), _t(120, 1300, 156000))
    assert v["tender_amount"] == 120000.0 and v["actual_amount"] == 156000.0
    assert v["rate_delta"] == 100.0
    assert round(v["rate_delta_pct"], 2) == round(100 / 1200 * 100, 2)
    assert v["amount_delta"] == 36000.0
    # qty-driven = (120-100)*1200 = 24,000 ; rate-driven = 120*(1300-1200) = 12,000
    assert v["amount_delta_qty"] == 24000.0 and v["amount_delta_rate"] == 12000.0
    # the decomposition is exactly additive
    assert round(v["amount_delta_qty"] + v["amount_delta_rate"], 2) == v["amount_delta"]


def test_rate_only_pair_has_rate_delta_but_no_amount_or_decomposition():
    v = variance_between(_t(rate=1200), _t(rate=1500))  # no quantities anywhere
    assert v["rate_delta"] == 300.0
    assert v["amount_delta"] is None                     # no computable amount -> no fabricated delta
    assert v["amount_delta_qty"] is None and v["amount_delta_rate"] is None
    assert v["tender_amount"] is None and v["actual_amount"] is None


def test_qty_change_only_is_all_qty_driven():
    v = variance_between(_t(100, 1000, 100000), _t(150, 1000, 150000))
    assert v["rate_delta"] == 0.0
    assert v["amount_delta"] == 50000.0
    assert v["amount_delta_qty"] == 50000.0 and v["amount_delta_rate"] == 0.0


def test_omission_at_tender_has_tender_side_only():
    v = variance_between(_t(100, 1200, 120000), None)   # priced, no actual
    assert v["tender_amount"] == 120000.0 and v["actual_amount"] is None
    assert v["rate_delta"] is None and v["amount_delta"] is None


def test_arrived_unpriced_has_actual_side_only():
    v = variance_between(None, _t(50, 900, 45000))      # actual with no tender line
    assert v["actual_amount"] == 45000.0 and v["tender_amount"] is None
    assert v["rate_delta"] is None and v["amount_delta"] is None


def test_lump_sum_amounts_delta_without_decomposition():
    # both sides have a stated amount but no rate (section totals) -> amount_delta, no split
    v = variance_between(_t(amount=2000000), _t(amount=2400000))
    assert v["amount_delta"] == 400000.0
    assert v["amount_delta_qty"] is None and v["amount_delta_rate"] is None


def test_computable_amount_mirrors_leveling_discipline():
    assert computable_amount(3, 10, 999) == 30.0        # qty*rate wins over stated amount
    assert computable_amount(None, None, 500) == 500.0  # lump sum, no rate basis
    assert computable_amount(None, 42, None) is None     # rate-only -> no amount
    assert computable_amount(None, None, None) is None
