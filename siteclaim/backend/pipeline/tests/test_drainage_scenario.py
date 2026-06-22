"""Drainage scenario (Contract GE/2026/14) — a civil GI tender that proves four
things on the real tender documents: ingest splitting by work section, a working
public-record risk screen (the cautionary bidder GI-1 carries two safety-prosecution
convictions, a fatal flag, and is demoted below every clean firm exactly like the
electrical hero), bid leveling where the apparent-cheapest bid loses once excluded
scope is added back, and a recommendation that lands on a REAL Hong Kong GI
contractor drawn from the register. The two clean bidders are real, award-bearing
registry firms (Gold Ram, DrilTech); their submitted quotes are representative for
the demo. GI-1 is a fictional cautionary firm and is never a real named company.
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

# the two clean bidders are now real, award-bearing registry firms; GI-1 stays fictional
GOLD = "gold-ram-engineering-development-limited-9bbd"
DRIL = "driltech-ground-engineering-limited-a721"


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


def test_runner_up_has_one_arithmetic_correction_on_g13(levelled):
    dril = _by_firm(levelled)[DRIL]
    findings = dril.arithmetic_findings
    assert len(findings) == 1
    g13 = findings[0]
    assert g13.location == "line G13"
    assert g13.corrected_value == 366000.0  # 12 x 30,500, not the stated 300,000
    assert dril.corrected_total == 1133150.0


def test_normalized_totals_put_every_bid_on_the_same_scope_basis(levelled):
    by = _by_firm(levelled, "field_testing")
    assert by[GOLD].normalized_total == 1114790.0
    assert by["F-GI-01"].normalized_total == 1127890.0  # corrected + peer water + peer freeboard
    assert by[DRIL].normalized_total == 1133150.0


def test_all_three_gi_sections_are_levelled(levelled):
    # the tender's three work sections (G/H/J) are each levelled, not just field testing
    trades = {b.trade for b in levelled}
    assert trades == {"field_testing", "field_installations", "geophysical_survey"}
    # every clean firm submitted a full package quote across all three sections
    for firm in (GOLD, DRIL):
        assert {b.trade for b in levelled if b.firm_id == firm} == trades


def test_leveling_ranks_the_real_winner_first_by_normalized_total(levelled):
    ft = [b for b in levelled if b.trade == "field_testing"]
    order = sorted(ft, key=lambda b: b.normalized_total)
    assert [b.firm_id for b in order] == [GOLD, "F-GI-01", DRIL]
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
    assert "1,114,790" in rec.rationale and "1,127,890" in rec.rationale
    assert "safety-prosecution" in rec.rationale
