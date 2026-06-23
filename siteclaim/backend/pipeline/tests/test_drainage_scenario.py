"""Drainage scenario (Contract GE/2026/14) — a civil GI tender that proves four
things on the real tender documents: ingest splitting by work section, a working
public-record risk screen (the cautionary bidder GI-1 carries two safety-prosecution
convictions, a fatal flag, and is demoted below every clean firm exactly like the
electrical hero), bid leveling where the apparent-cheapest bid loses once excluded
scope is added back, and a recommendation that lands on a REAL Hong Kong GI
contractor drawn from the register.

Every work section is a three-column comparison: the tender's own Schedule of Rates
(the benchmark "bid", firm_id ``tender-scheduled-rates``) plus the two firms taken to
bid. Field testing (G) levels Gold Ram and the cautionary fictional GI-1; field
installations (H) levels the real Kai Wai offer and a representative competitor
(Fugro); geophysical survey (J) levels the real Sixense offer and a representative
competitor (Geotechnics). The named bidders are real, award-bearing registry firms
whose figures are representative for the demo; GI-1 is fictional and never a real
named company.
"""

import pytest

from db import seed, store
from pipeline.stage_01_ingest.ingest import ingest_tender
from pipeline.stage_02_shortlist.shortlist import shortlist
from pipeline.stage_04_level.level import level_bids, load_demo_replies
from pipeline.stage_05_recommend.recommend import recommend
from schemas.models import DocType, Severity, TenderDocument, TenderPackage

_SCOPE_FIXTURE = "cases/scenarios/drainage_scope.json"
_REPLIES_FIXTURE = "cases/scenarios/drainage_replies.json"
_RATIONALE_FIXTURE = "cases/scenarios/drainage_rationale.json"

# the section bidders are real, award-bearing registry firms; GI-1 stays fictional.
# Field testing (G): Gold Ram and the cautionary GI-1 (DrilTech stays an assessable
# shortlist firm but is not taken to bid here).
GOLD = "gold-ram-engineering-development-limited-9bbd"
DRIL = "driltech-ground-engineering-limited-a721"
# Field installations (H): the real Kai Wai offer plus the representative competitor
# Fugro. Geophysical survey (J): the real Sixense offer plus the representative
# competitor Geotechnics. Every section is priced against the tender's own scheduled
# rates (the benchmark "bid").
KAIWAI = "kai-wai-engineering-survey-and-geophysics-limited-3f7b"
FUGRO = "fugro-geotechnical-services-limited-af2a"
SIXENSE = "sixense-limited-5d2c"
GEOTECH = "geotechnics-concrete-engineering-hong-kong-limited-b412"
BENCH = "tender-scheduled-rates"


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("drainage") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def scope():
    tender = TenderPackage(
        project_name="GE/2026/14 — Ground Investigation",
        description="Ground investigation, man-made slopes.",
        documents=[TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename="I-GE_2026_14_TSC-SR-01.pdf")],
    )
    return ingest_tender(tender, demo_fixture=_SCOPE_FIXTURE)


@pytest.fixture
def levelled(conn):
    return level_bids(load_demo_replies(_REPLIES_FIXTURE), conn=conn)


def _by_firm(levelled, trade="field_testing"):
    # one bid per firm WITHIN a section (a firm now bids on all three GI sections)
    return {b.firm_id: b for b in levelled if b.trade == trade}


def test_ingest_splits_the_civil_tender_by_work_section(scope):
    trades = [p.trade for p in scope.packages]
    assert trades == ["field_testing", "field_installations", "geophysical_survey"]
    field = next(p for p in scope.packages if p.trade == "field_testing")
    assert [i.item_ref for i in field.sor_items] == ["G11", "G12", "G13", "G14", "G15", "G16", "G17a", "G17b"]


def test_shortlist_screens_real_firms_with_the_flagged_one_demoted(scope, conn):
    cands = shortlist(scope, conn=conn).per_trade["field_testing"]
    ids = {c.firm.firm_id for c in cands}
    # the shortlist is drawn from the register: the real award-bearing GI firms are
    # assessable and present, alongside the fictional cautionary firm GI-1
    assert {GOLD, DRIL, "F-GI-01"} <= ids
    # GI-1 carries two safety-prosecution convictions -> fatal, demoted last and
    # recommended against, regardless of match (the hero risk-screen pattern)
    gi1 = next(c for c in cands if c.firm.firm_id == "F-GI-01")
    assert gi1.recommended_against is True
    assert {f.rule_ref for f in gi1.risk_flags if f.severity is Severity.FATAL} == {"risk.safety_prosecutions"}
    assert cands[-1].firm.firm_id == "F-GI-01"
    # every clean firm (the real ones included) ranks ahead and is not recommended against
    assert cands[0].recommended_against is False
    assert all(not c.recommended_against for c in cands if c.firm.firm_id != "F-GI-01")
    # the real firms surface their public award history as citable candidacy evidence
    gold = next(c for c in cands if c.firm.firm_id == GOLD)
    assert any(e.reference.startswith("AWARDS:") for e in gold.evidence)


def test_other_gi_subtrades_are_populated_from_the_register(scope, conn):
    sl = shortlist(scope, conn=conn).per_trade
    # the two scopes that were empty now carry real, screened candidates
    assert len(sl["field_installations"]) >= 1
    assert len(sl["geophysical_survey"]) >= 1
    assert all(not c.firm.firm_id.startswith("F-") for c in sl["geophysical_survey"])


def test_gi1_has_two_scope_gaps_water_and_freeboard(levelled):
    gi1 = _by_firm(levelled)["F-GI-01"]
    gap_refs = {g.split(" ")[0] for g in gi1.scope_gaps}
    assert gap_refs == {"G14", "G16"}
    assert gi1.corrected_total == 1020590.0


def test_competitor_has_one_arithmetic_correction_on_h16(levelled):
    # the field-installations competitor understated its monitoring line: H16 is
    # 24 x 880 = 21,120, not the stated 20,000 — exactly one correction, and the
    # corrected sum uses the recomputed amount
    fugro = _by_firm(levelled, "field_installations")[FUGRO]
    findings = fugro.arithmetic_findings
    assert len(findings) == 1
    h16 = findings[0]
    assert h16.location == "line H16"
    assert h16.corrected_value == 21120.0  # 24 x 880, not the stated 20,000
    assert fugro.corrected_total == 187480.0


def test_normalized_totals_put_every_bid_on_the_same_scope_basis(levelled):
    by = _by_firm(levelled, "field_testing")
    assert by[GOLD].normalized_total == 1114790.0
    # corrected (1,020,590) + peer water (G14, median of Gold 15,000 & benchmark
    # 14,400 = 14,700) + peer freeboard (G16, median of 91,200 & 90,000 = 90,600)
    assert by["F-GI-01"].normalized_total == 1125890.0
    # the benchmark prices the full scope, so its normalised sum equals its corrected
    assert by[BENCH].normalized_total == 1112990.0


def test_all_three_gi_sections_are_levelled_with_real_bidders(levelled):
    # the tender's three work sections (G/H/J) are each levelled, not just field testing
    trades = {b.trade for b in levelled}
    assert trades == {"field_testing", "field_installations", "geophysical_survey"}
    bidders = lambda t: {b.firm_id for b in levelled if b.trade == t}  # noqa: E731
    # every section is benchmark + exactly the two firms taken to bid
    # field testing: Gold Ram and the cautionary fictional firm, against the benchmark
    assert bidders("field_testing") == {BENCH, GOLD, "F-GI-01"}
    # field installations: the real Kai Wai offer and the competitor Fugro
    assert bidders("field_installations") == {BENCH, KAIWAI, FUGRO}
    # geophysical survey: the real Sixense offer and the competitor Geotechnics
    assert bidders("geophysical_survey") == {BENCH, SIXENSE, GEOTECH}


def test_conductivity_probe_is_the_one_line_above_benchmark(levelled):
    # H14c: the real bidder's dual-tip conductivity probe is the outlier above the
    # tender scheduled rate (30,000 vs 13,000) — it must be visible per line item
    reps = load_demo_replies(_REPLIES_FIXTURE)
    kw = next(r for r in reps if r.firm_id == KAIWAI and r.trade == "field_installations")
    bench = next(r for r in reps if r.firm_id == BENCH and r.trade == "field_installations")
    kw_c = next(li for li in kw.line_items if li.item_ref == "H14c").rate
    bench_c = next(li for li in bench.line_items if li.item_ref == "H14c").rate
    assert kw_c == 30000.0 and bench_c == 13000.0 and kw_c > bench_c
    # and every other Kai Wai instrument line is at or below the benchmark
    bench_rate = {li.item_ref: li.rate for li in bench.line_items}
    above = [li.item_ref for li in kw.line_items if li.rate is not None and li.rate > bench_rate[li.item_ref]]
    assert above == ["H14c"]


def test_recommendation_runs_per_section_with_a_different_winner_each(levelled, conn):
    wins = {}
    for trade in ("field_testing", "field_installations", "geophysical_survey"):
        rec = recommend(levelled, trade, conn=conn)
        wins[trade] = rec.recommended_firm_id
        # the tender benchmark is never the recommended firm (it is a baseline, not a bid)
        assert rec.recommended_firm_id != BENCH
    assert wins == {"field_testing": GOLD, "field_installations": KAIWAI, "geophysical_survey": SIXENSE}
    assert len(set(wins.values())) == 3  # a different real firm wins each section


def test_leveling_names_resolve_from_the_db_profile(levelled, conn):
    # name consistency: the firm shown in leveling is the DB profile of the replied
    # firm, so it matches the name a user saw at shortlist/dispatch
    for b in levelled:
        profile = store.firm_profile(conn, b.firm_id)
        assert profile is not None and b.firm_name == profile.name
    # the real section bidders are the firms the shortlist would surface for that trade
    assert SIXENSE in {f.firm_id for f in store.shortlistable_firms_for_trade(conn, "geophysical_survey")}
    assert KAIWAI in {f.firm_id for f in store.shortlistable_firms_for_trade(conn, "field_installations")}


def test_leveling_ranks_the_real_winner_first_by_normalized_total(levelled):
    # rank the firms taken to bid (the benchmark is a baseline, not a tenderer)
    ft = [b for b in levelled if b.trade == "field_testing" and b.firm_id != BENCH]
    order = sorted(ft, key=lambda b: b.normalized_total)
    assert [b.firm_id for b in order] == [GOLD, "F-GI-01"]
    # the apparent-cheapest bid (GI-1, lowest corrected) is NOT the leveled winner
    cheapest_corrected = min(ft, key=lambda b: b.corrected_total)
    assert cheapest_corrected.firm_id == "F-GI-01"
    assert order[0].firm_id != cheapest_corrected.firm_id


def test_recommend_picks_the_real_firm_against_the_flagged_gi1(levelled, conn):
    rec = recommend(levelled, "field_testing", demo_fixture=_RATIONALE_FIXTURE, conn=conn)
    # the recommendation lands on a real, register-resident GI contractor
    assert rec.recommended_firm_id == GOLD
    gi1 = next(r for r in rec.ranked if r.firm_id == "F-GI-01")
    assert gi1.recommended_against is True
    assert "risk.safety_prosecutions" in gi1.reason
    assert rec.historical_band is None
    assert "1,114,790" in rec.rationale and "1,125,890" in rec.rationale
    assert "safety-prosecution" in rec.rationale
