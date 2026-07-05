"""Benchmark matcher + confirm gate + variance table (Phase B1d), through the API.

The matcher is exercised directly (tiers) and end to end; the confirm gate is asserted as
the SOLE writer of variance_records. Temp live DB via SITESOURCE_DB; offline (deterministic
embedding, no model).
"""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from api import app
from db import seed
from pipeline.benchmark.actuals_xlsx import TEMPLATE_HEADERS
from pipeline.benchmark.matcher import match

client = TestClient(app)
_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def bench_db(tmp_path, monkeypatch):
    db = tmp_path / "bench.db"
    seed.build_database(db, profile="live")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


# -- matcher units --------------------------------------------------------------------
def _t(id, ref, desc="", qty=None, rate=None):
    return {"id": id, "item_ref": ref, "description": desc, "qty": qty, "rate": rate, "amount": None, "granularity": "item"}


def _a(id, ref, desc="", qty=None, rate=None, granularity="item"):
    return {"id": id, "item_ref": ref, "description": desc, "qty": qty, "rate": rate, "amount": None, "granularity": granularity}


def test_tier1_exact_ref_matches():
    pairs = match([_t(1, "A1a(a)", "Rotary drilling")], [_a(10, "A1a(a)", "Rotary drilling")])
    assert len(pairs) == 1 and pairs[0]["tier"] == 1 and pairs[0]["similarity"] == 1.0
    assert pairs[0]["tender"]["id"] == 1 and pairs[0]["actual"]["id"] == 10


def test_tier2_embedding_matches_when_refs_differ():
    # refs differ but descriptions are near-identical -> Tier 2
    pairs = match(
        [_t(1, "A1", "Rotary drilling in soil and rock strata")],
        [_a(10, "Z9", "Rotary drilling in soil and rock strata")],
    )
    assert len(pairs) == 1 and pairs[0]["tier"] == 2 and pairs[0]["similarity"] >= 0.72


def test_tier3_both_directions_and_coarse():
    pairs = match(
        [_t(1, "A1", "unique tender only description alpha")],
        [_a(10, "B2", "completely different actual only beta"), _a(20, "", "Section total", granularity="section")],
    )
    tiers = sorted(p["tier"] for p in pairs)
    assert tiers == [3, 3, 3]
    omission = next(p for p in pairs if p["tender"] and not p["actual"])
    arrived = next(p for p in pairs if p["actual"] and p["actual"]["id"] == 10 and not p["tender"])
    coarse = next(p for p in pairs if p["actual"] and p["actual"]["id"] == 20)
    assert omission["tender"]["id"] == 1 and arrived and coarse["actual"]["granularity"] == "section"


# -- confirm gate + variance table (API) ----------------------------------------------
def _sor_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(TEMPLATE_HEADERS[:6])  # Item..Amount (tender sheet has no Section here)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _actuals_xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(TEMPLATE_HEADERS)
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _setup_project(bench_db) -> int:
    pid = client.post("/benchmark/projects", json={"name": "P", "trade": "ground_investigation"}).json()["id"]
    # tender: A1 100@1200, M2 40@950
    client.post(f"/benchmark/{pid}/tender-upload",
                files={"files": ("t.xlsx", _sor_xlsx([["A1", "Drilling", "m", 100, 1200, 120000],
                                                      ["M2", "Standing time", "hr", 40, 950, 38000]]), _XLSX_CT)})
    # actuals: A1 120@1300 (over), M2 40@950 (same)
    client.post(f"/benchmark/{pid}/actuals-upload",
                files={"files": ("a.xlsx", _actuals_xlsx([["A1", "Drilling", "m", 120, 1300, 156000, "A"],
                                                          ["M2", "Standing time", "hr", 40, 950, 38000, "A"]]), _XLSX_CT)})
    return pid


def test_matches_endpoint_returns_tiers(bench_db):
    pid = _setup_project(bench_db)
    proposal = client.get(f"/benchmark/{pid}/matches").json()
    assert len(proposal["tier1"]) == 2 and proposal["tier2"] == [] and proposal["tier3"] == []
    refs = {p["tender"]["item_ref"] for p in proposal["tier1"]}
    assert refs == {"A1", "M2"}


def test_confirm_gate_is_the_sole_writer_of_variance(bench_db):
    pid = _setup_project(bench_db)
    # nothing written until confirm
    assert client.get(f"/benchmark/{pid}/variance").json() == []

    proposal = client.get(f"/benchmark/{pid}/matches").json()
    confirm = [{"tender_item_id": p["tender"]["id"], "actual_item_id": p["actual"]["id"], "match_tier": 1}
               for p in proposal["tier1"]]
    written = client.post(f"/benchmark/{pid}/matches/confirm", json={"confirm": confirm}).json()
    assert len(written) == 2

    a1 = next(r for r in written if r["item_ref"] == "A1")
    assert a1["rate_delta"] == 100.0 and a1["amount_delta"] == 36000.0
    assert a1["amount_delta_qty"] == 24000.0 and a1["amount_delta_rate"] == 12000.0
    assert a1["match_tier"] == 1 and a1["confirmed_at"] and a1["source"] == "confirm-gate"
    assert a1["reason_code"] == ""  # not tagged yet

    # re-confirming the same pairs updates, never duplicates
    again = client.post(f"/benchmark/{pid}/matches/confirm", json={"confirm": confirm}).json()
    assert len(again) == 2


def test_confirm_rejects_an_id_not_in_the_project(bench_db):
    pid = _setup_project(bench_db)
    resp = client.post(f"/benchmark/{pid}/matches/confirm",
                       json={"confirm": [{"tender_item_id": 999999, "match_tier": 1}]})
    assert resp.status_code == 400 and "not in project" in resp.json()["detail"]


def test_reason_write_requires_a_valid_human_code(bench_db):
    pid = _setup_project(bench_db)
    proposal = client.get(f"/benchmark/{pid}/matches").json()
    confirm = [{"tender_item_id": p["tender"]["id"], "actual_item_id": p["actual"]["id"], "match_tier": 1}
               for p in proposal["tier1"]]
    written = client.post(f"/benchmark/{pid}/matches/confirm", json={"confirm": confirm}).json()
    rid = next(r["id"] for r in written if r["item_ref"] == "A1")

    # invalid code -> 400 (write requires a real vocabulary code)
    bad = client.post(f"/benchmark/{pid}/variance/{rid}/reason", json={"reason_code": "made_up"})
    assert bad.status_code == 400

    ok = client.post(f"/benchmark/{pid}/variance/{rid}/reason",
                     json={"reason_code": "standing_time", "note": "rig idle 3 days"}).json()
    assert ok["reason_code"] == "standing_time" and ok["reason_note"] == "rig idle 3 days"
    assert ok["tagged_by"] == "operator"

    # unknown record -> 404
    assert client.post(f"/benchmark/{pid}/variance/999999/reason",
                       json={"reason_code": "standing_time"}).status_code == 404


def test_variance_carries_a_deterministic_reason_suggestion(bench_db):
    pid = _setup_project(bench_db)
    proposal = client.get(f"/benchmark/{pid}/matches").json()
    confirm = [{"tender_item_id": p["tender"]["id"], "actual_item_id": p["actual"]["id"], "match_tier": 1}
               for p in proposal["tier1"]]
    client.post(f"/benchmark/{pid}/matches/confirm", json={"confirm": confirm})
    variance = client.get(f"/benchmark/{pid}/variance").json()
    # M2 has "Standing time" in its ref-less note space; A1 is qty-driven -> quantity_remeasure
    a1 = next(r for r in variance if r["item_ref"] == "A1")
    assert a1["suggested_reason"] in {"quantity_remeasure", "rate_reprice"}  # a hint, not a write
    assert a1["reason_code"] == ""


def test_summary_counts_live_project(bench_db):
    pid = _setup_project(bench_db)
    proposal = client.get(f"/benchmark/{pid}/matches").json()
    confirm = [{"tender_item_id": p["tender"]["id"], "actual_item_id": p["actual"]["id"], "match_tier": 1}
               for p in proposal["tier1"]]
    client.post(f"/benchmark/{pid}/matches/confirm", json={"confirm": confirm})
    summ = client.get("/benchmark/summary").json()
    assert summ["projects"] == 1 and summ["tender_items"] == 2 and summ["actual_items"] == 2
    assert summ["variance_records"] == 2
    assert summ["coverage_by_trade"].get("ground_investigation") == 1
    assert summ["coverage_by_granularity"].get("item") == 2


def test_reason_codes_endpoint_lists_ten(bench_db):
    codes = client.get("/benchmark/reason-codes").json()
    assert len(codes) == 10 and {"standing_time", "omission_at_tender"} <= {c["code"] for c in codes}


def test_benchmark_d_routes_registered():
    paths = {r.path for r in app.routes}
    assert {"/benchmark/{project_id}/matches", "/benchmark/{project_id}/matches/confirm",
            "/benchmark/{project_id}/variance", "/benchmark/{project_id}/variance/{record_id}/reason",
            "/benchmark/summary", "/benchmark/reason-codes"} <= paths
