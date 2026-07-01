"""Stage 04 leveling — corrects the messy reply's arithmetic, surfaces the missing
provisional sum and the exclusion, flips the clean-firm ranking, and exports Excel."""

import pytest
from openpyxl import load_workbook

from db import seed, store
from pipeline.stage_04_level.export_xlsx import OUT_PATH, export_leveling_xlsx
from pipeline.stage_04_level.level import level_bids, load_demo_replies
from schemas.models import Severity

_REPLIES_FIXTURE = "cases/messy/bid_replies.json"


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("level") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def replies():
    return load_demo_replies(_REPLIES_FIXTURE)


@pytest.fixture
def levelled(replies, conn):
    return level_bids(replies, conn=conn)


def _by_firm(levelled):
    return {b.firm_id: b for b in levelled}


def test_corrected_total_differs_from_claimed_on_the_messy_reply(replies, levelled):
    messy = _by_firm(levelled)["F-EL-03"]
    claimed = next(r.claimed_total for r in replies if r.firm_id == "F-EL-03")
    # the understated line is corrected upward, so the "cheap" bid is not cheap
    assert messy.corrected_total != claimed
    assert messy.corrected_total == 12272000.0
    assert claimed == 10272000.0


def test_arithmetic_error_is_caught_with_corrected_value(levelled):
    messy = _by_firm(levelled)["F-EL-03"]
    findings = messy.arithmetic_findings
    assert findings and any(f.location == "line E-03" for f in findings)
    e03 = next(f for f in findings if f.location == "line E-03")
    assert e03.corrected_value == 7740000.0
    assert e03.severity is Severity.WARNING


def test_missing_provisional_sum_is_a_scope_gap_not_zero(levelled):
    messy = _by_firm(levelled)["F-EL-03"]
    assert any("E-06" in gap and "provisional" in gap.lower() for gap in messy.scope_gaps)
    # the gap is surfaced in normalized_total (peer-priced), never silently filled
    assert messy.normalized_total > messy.corrected_total


def test_stated_exclusion_is_flagged_not_deducted(levelled):
    messy = _by_firm(levelled)["F-EL-03"]
    assert any("BWIC" in e or "Builder's work" in e for e in messy.exclusions)


def test_clean_arithmetic_bids_have_no_findings(levelled):
    for firm_id in ("F-EL-01", "F-EL-02", "F-EL-04"):
        assert _by_firm(levelled)[firm_id].arithmetic_findings == []


def test_leveling_changes_the_clean_firm_ranking(replies, levelled):
    clean = ["F-EL-02", "F-EL-03", "F-EL-04"]  # exclude the risk-flagged gotcha
    claimed = {r.firm_id: r.claimed_total for r in replies}
    corrected = {b.firm_id: b.corrected_total for b in levelled}
    cheapest_by_claimed = min(clean, key=lambda f: claimed[f])
    cheapest_by_corrected = min(clean, key=lambda f: corrected[f])
    assert cheapest_by_claimed == "F-EL-03"      # looks cheapest on paper
    assert cheapest_by_corrected == "F-EL-02"    # leveling reveals the real cheapest
    assert cheapest_by_claimed != cheapest_by_corrected


def test_excel_is_produced(replies, levelled):
    out = export_leveling_xlsx(levelled, replies, item_order=["E-01", "E-02", "E-03", "E-04", "E-05", "E-06"], path=OUT_PATH)
    assert out.is_file()
    wb = load_workbook(out)
    # the adjudication workbook: a Summary, a per-section sheet, and the analysis sheets
    assert {"Summary", "Electrical", "Arithmetic Corrections", "Scope Normalisation",
            "Qualifications & Exclusions"} <= set(wb.sheetnames)
    # the corrected totals tie to the on-screen leveling, across the workbook
    flat = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row]
    assert 12272000.0 in flat and 12033000.0 in flat
