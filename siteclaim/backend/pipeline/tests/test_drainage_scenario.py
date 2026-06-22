"""Drainage scenario (Contract GE/2026/14) — a civil GI tender that proves two
things the electrical scenarios cannot: ingest splitting by work section, and bid
leveling where the apparent-cheapest bid loses once excluded scope is added back.

No public-record risk screen applies here (the discovery DB holds building
contractors, not GI specialists), so the package is decided on leveled price alone.
"""

import pytest

from db import seed, store
from pipeline.stage_01_ingest.ingest import ingest_tender
from pipeline.stage_04_level.level import level_bids, load_demo_replies
from pipeline.stage_05_recommend.recommend import recommend
from schemas.models import DocType, TenderDocument, TenderPackage

_SCOPE_FIXTURE = "cases/scenarios/drainage_scope.json"
_REPLIES_FIXTURE = "cases/scenarios/drainage_replies.json"
_RATIONALE_FIXTURE = "cases/scenarios/drainage_rationale.json"


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("drainage") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def levelled(conn):
    return level_bids(load_demo_replies(_REPLIES_FIXTURE), conn=conn)


def _by_firm(levelled):
    return {b.firm_id: b for b in levelled}


def test_ingest_splits_the_civil_tender_by_work_section():
    tender = TenderPackage(
        project_name="GE/2026/14 — Ground Investigation",
        description="Ground investigation, man-made slopes.",
        documents=[TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename="I-GE_2026_14_TSC-SR-01.pdf")],
    )
    scope = ingest_tender(tender, demo_fixture=_SCOPE_FIXTURE)
    trades = [p.trade for p in scope.packages]
    # the generic taxonomy normalises the civil work sections to canonical keys
    assert trades == ["field_testing", "drilling", "sampling"]
    field = next(p for p in scope.packages if p.trade == "field_testing")
    assert [i.item_ref for i in field.sor_items] == ["G11", "G12", "G13", "G14", "G15", "G16", "G17a", "G17b"]


def test_no_gi_firms_are_shortlistable(conn):
    # the discovery DB holds building contractors, not GI specialists, so the
    # field_testing shortlist is honestly empty
    assert store.shortlistable_firms_for_trade(conn, "field_testing") == []


def test_gi1_has_two_scope_gaps_water_and_freeboard(levelled):
    gi1 = _by_firm(levelled)["F-GI-01"]
    gap_refs = {g.split(" ")[0] for g in gi1.scope_gaps}
    assert gap_refs == {"G14", "G16"}
    assert gi1.corrected_total == 1020590.0


def test_gi3_has_one_arithmetic_correction_on_g13(levelled):
    gi3 = _by_firm(levelled)["F-GI-03"]
    findings = gi3.arithmetic_findings
    assert len(findings) == 1
    g13 = findings[0]
    assert g13.location == "line G13"
    assert g13.corrected_value == 366000.0  # 12 x 30,500, not the stated 300,000
    assert gi3.corrected_total == 1133150.0


def test_normalized_totals_put_every_bid_on_the_same_scope_basis(levelled):
    by = _by_firm(levelled)
    assert by["F-GI-02"].normalized_total == 1114790.0
    assert by["F-GI-01"].normalized_total == 1127890.0  # corrected + peer water + peer freeboard
    assert by["F-GI-03"].normalized_total == 1133150.0


def test_leveling_ranks_gi2_first_by_normalized_total(levelled):
    order = sorted(levelled, key=lambda b: b.normalized_total)
    assert [b.firm_id for b in order] == ["F-GI-02", "F-GI-01", "F-GI-03"]
    # the apparent-cheapest bid (GI-1, lowest corrected) is NOT the leveled winner
    cheapest_corrected = min(levelled, key=lambda b: b.corrected_total)
    assert cheapest_corrected.firm_id == "F-GI-01"
    assert order[0].firm_id != cheapest_corrected.firm_id


def test_recommend_picks_gi2_on_a_leveled_basis(levelled, conn):
    rec = recommend(levelled, "field_testing", demo_fixture=_RATIONALE_FIXTURE, conn=conn)
    assert rec.recommended_firm_id == "F-GI-02"
    assert not any(r.recommended_against for r in rec.ranked)  # no risk screen, no fatal flags
    assert rec.historical_band is None  # no GI pricing samples in the building-firm DB
    assert "1,114,790" in rec.rationale and "1,127,890" in rec.rationale
