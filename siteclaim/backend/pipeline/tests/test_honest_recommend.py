"""Honest recommend + award gating (return round-trip v2, Commit 2): a return that priced nothing
is not a valid bid — excluded from the ranking, never recommended at HK$0, and a unit with only
invalid returns withholds the award. Deterministic, offline (DEMO_MODE)."""

from pipeline.stage_04_level.level import level_bids
from pipeline.stage_05_recommend.recommend import recommend
from schemas.models import BidLineItem, BidReply


def _priced(firm, trade, refs_rates):
    return BidReply(firm_id=firm, trade=trade,
                    line_items=[BidLineItem(item_ref=r, qty=1.0, rate=v, amount=v) for r, v in refs_rates])


def _empty(firm, trade):  # a return that priced nothing for this unit (no line items)
    return BidReply(firm_id=firm, trade=trade)


def test_a_return_that_priced_nothing_gates_the_award():
    rec = recommend(level_bids([_empty("F-A", "ground_investigation:H")]), "ground_investigation:H", unit_total=31)
    assert rec.recommended_firm_id is None                       # no HK$0 "cheapest clean" winner
    assert rec.awaiting_valid_return is True                     # the award gate closes
    assert rec.ranked and rec.ranked[0].no_priced_coverage is True
    assert "0 of 31 items priced" in rec.ranked[0].reason        # the human-readable coverage reason
    assert rec.bid_distribution == []                            # never an HK$0 point on the chart
    assert "withheld" in rec.rationale.lower()


def test_a_zero_priced_bid_is_excluded_but_a_priced_bid_still_recommends():
    bids = level_bids([_priced("F-A", "ground_investigation:H", [("H1", 100.0)]),
                       _empty("F-B", "ground_investigation:H")])
    rec = recommend(bids, "ground_investigation:H", unit_total=1)
    assert rec.recommended_firm_id == "F-A" and rec.awaiting_valid_return is False
    fb = next(r for r in rec.ranked if r.firm_id == "F-B")
    assert fb.no_priced_coverage is True                         # surfaced, excluded from the winner
    assert all(not r.no_priced_coverage for r in rec.ranked if r.firm_id == "F-A")
    assert [p.firm_name for p in rec.bid_distribution] and all(p.corrected_total > 0 for p in rec.bid_distribution)


def test_a_normal_priced_return_recommends_exactly_as_before():
    bids = level_bids([_priced("F-A", "ground_investigation:H", [("H1", 100.0)]),
                       _priced("F-B", "ground_investigation:H", [("H1", 120.0)])])
    rec = recommend(bids, "ground_investigation:H")
    assert rec.recommended_firm_id == "F-A"                      # cheapest clean, unchanged
    assert rec.awaiting_valid_return is False
    assert all(not r.no_priced_coverage for r in rec.ranked)
    assert len(rec.bid_distribution) == 2


def test_a_rate_only_bid_with_zero_corrected_total_still_counts_as_priced():
    # A rate-only SoR (rates present, no quantities -> corrected_total 0) IS a valid priced bid —
    # corrected_total == 0 must not be mistaken for "priced nothing".
    rate_only = BidReply(firm_id="F-A", trade="ground_investigation:H",
                         line_items=[BidLineItem(item_ref="H1", rate=100.0)])  # no qty -> no amount
    rec = recommend(level_bids([rate_only]), "ground_investigation:H", unit_total=1)
    assert rec.awaiting_valid_return is False and rec.recommended_firm_id == "F-A"
    assert all(not r.no_priced_coverage for r in rec.ranked)


def test_a_rate_only_zero_bid_never_wins_over_a_firm_that_priced_an_extended_total():
    # The HK$0 trap: a rate-only return (rates, no quantities -> corrected_total 0) must NOT rank as
    # the "cheapest clean bid" at HK$0 over a firm that actually extended a comparable total. It is
    # still a valid priced bid (surfaced, not gated) — it just never wins the award at HK$0.
    rate_only = BidReply(firm_id="F-A", trade="ground_investigation:H",
                         line_items=[BidLineItem(item_ref="H1", rate=100.0)])  # total 0
    extended = _priced("F-B", "ground_investigation:H", [("H1", 2000.0)])       # qty*rate -> total 2000
    rec = recommend(level_bids([rate_only, extended]), "ground_investigation:H", unit_total=1)
    assert rec.recommended_firm_id == "F-B"                   # the comparable-total firm wins, not HK$0 F-A
    assert rec.awaiting_valid_return is False
    assert all(not r.no_priced_coverage for r in rec.ranked)  # F-A stays a valid (rate-only) priced bid


def test_when_every_bid_is_rate_only_the_lone_clean_firm_still_recommends():
    # A genuinely rate-only tender (no firm extended a total): comparison is rate-first, so a zero-
    # total clean bid may still stand as the recommendation — the positive-total preference only
    # applies when SOME firm priced a comparable total.
    a = BidReply(firm_id="F-A", trade="ground_investigation:H", line_items=[BidLineItem(item_ref="H1", rate=90.0)])
    b = BidReply(firm_id="F-B", trade="ground_investigation:H", line_items=[BidLineItem(item_ref="H1", rate=110.0)])
    rec = recommend(level_bids([a, b]), "ground_investigation:H", unit_total=1)
    assert rec.recommended_firm_id in {"F-A", "F-B"} and rec.awaiting_valid_return is False
