"""The costing surface, end to end: a client's bill in, a working Excel model out.

This is the product's actual job, so this file walks it the way a person would — import the bill,
look at what the engine concluded, change something, and download the workbook.

Two rules it defends beyond the arithmetic:

**A change made on one tender stays on that tender.** Copy-on-write: a tender uses the library's
model until somebody edits it there, at which point it gets its own copy. The library is untouched
and no other tender moves.

**The last decision is the estimator's.** The rounded rate is a proposal, the register warns rather
than blocks, and nothing in the app refuses to produce a workbook because it disagrees with them.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from client_boq.tests._bqfixture import build_bill_workbook

openpyxl = pytest.importorskip("openpyxl")

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


@pytest.fixture
def imported(client, tmp_path):
    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as handle:
        response = client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": (path.name, handle.read(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    return response.json()


class TestTheLibraryModel:
    def test_it_is_seeded_so_a_new_company_can_still_price(self, client):
        body = client.get(f"{BASE}/costing/model").json()
        assert body["usable"] and body["problems"] == []
        assert len(body["model"]["bands"]["bands"]) == 4
        assert body["model"]["inputs"]["margin"] == 0.10

    def test_it_can_be_changed(self, client):
        model = client.get(f"{BASE}/costing/model").json()["model"]
        model["inputs"]["margin"] = 0.18
        saved = client.put(f"{BASE}/costing/model", json={"model": model},
                           headers={"X-CBOQ-Actor": "SW"})
        assert saved.status_code == 200
        assert client.get(f"{BASE}/costing/model").json()["model"]["inputs"]["margin"] == 0.18

    def test_a_model_edited_into_an_unusable_state_is_reported_not_repaired(self, client):
        model = client.get(f"{BASE}/costing/model").json()["model"]
        model["spread"] = []
        body = client.put(f"{BASE}/costing/model", json={"model": model}).json()
        assert any("a day on site costs nothing" in p for p in body["problems"])


class TestTheCostingRun:
    def test_the_bill_produces_a_programme_without_anybody_typing_a_quantity(self, client, imported):
        body = client.get(f"{BASE}/costing/{SET}").json()
        assert body["programme"]["band"] is not None
        assert body["programme"]["work_days"] > 0
        assert body["quantities"], "the quantities were read out of the bill"

    def test_every_quantity_match_says_what_made_it_think_so(self, client, imported):
        body = client.get(f"{BASE}/costing/{SET}").json()
        assert all(m["why"] for m in body["quantities"].values())
        assert all(not m["confirmed"] for m in body["quantities"].values())

    def test_the_checks_come_back_as_sentences(self, client, imported):
        body = client.get(f"{BASE}/costing/{SET}").json()
        keys = {c["key"] for c in body["checks"]}
        assert {"convergence", "depth", "band_confidence"} <= keys
        assert all(c["message"] for c in body["checks"])

    def test_the_bill_is_priced_and_the_rates_are_proposals(self, client, imported):
        body = client.get(f"{BASE}/costing/{SET}").json()
        rows = {r["full_ref"]: r for r in body["priced"]["rows"]}
        priced = [r for r in rows.values() if r["rate_to_submit"] is not None]
        assert priced, "something in the bill should have found a cost basis"
        assert all(r["rate_to_submit"] == r["rate_rounded"]
                   for r in priced if r["source"] == "built")

    def test_an_item_with_no_cost_basis_is_named_with_the_consequence(self, client, imported):
        body = client.get(f"{BASE}/costing/{SET}").json()
        unpriced = body["priced"]["unpriced"]
        if unpriced:
            row = next(r for r in body["priced"]["rows"] if r["full_ref"] == unpriced[0])
            assert "for the life of the contract" in row["note"]

    def test_the_register_arrives_unreviewed(self, client, imported):
        body = client.get(f"{BASE}/costing/{SET}").json()
        assert body["register"]["gate"] == "NOT CLEARED"
        assert body["register"]["outstanding"] == len(body["register"]["rows"])

    def test_six_of_the_register_rows_cannot_be_typed(self, client, imported):
        rows = client.get(f"{BASE}/costing/{SET}").json()["register"]["rows"]
        assert sum(1 for r in rows if r["derived"]) >= 6


class TestAChangeStaysOnTheTenderThatMadeIt:
    def test_a_tender_starts_on_the_librarys_model(self, client, imported):
        body = client.get(f"{BASE}/costing/{SET}").json()
        assert body["using_own_model"] is False
        assert body["marks"] == {}, "nothing has diverged, so nothing is marked"

    def test_editing_it_here_copies_it_here(self, client, imported):
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        model["inputs"]["residual_site_factor"] = 1.3
        saved = client.put(f"{BASE}/costing/{SET}/model", json={"model": model},
                           headers={"X-CBOQ-Actor": "SW"})
        assert saved.status_code == 200 and saved.json()["using_own_model"] is True
        assert saved.json()["marks"]["inputs.residual_site_factor"] == "yours"

    def test_the_library_is_untouched_by_it(self, client, imported):
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        model["inputs"]["residual_site_factor"] = 1.3
        client.put(f"{BASE}/costing/{SET}/model", json={"model": model})
        library = client.get(f"{BASE}/costing/model").json()["model"]
        assert library["inputs"]["residual_site_factor"] == 1.0

    def test_the_change_actually_moves_the_programme(self, client, imported):
        before = client.get(f"{BASE}/costing/{SET}").json()["programme"]["work_days"]
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        model["inputs"]["residual_site_factor"] = 1.3
        client.put(f"{BASE}/costing/{SET}/model", json={"model": model})
        after = client.get(f"{BASE}/costing/{SET}").json()["programme"]["work_days"]
        assert after == pytest.approx(before * 1.3)

    def test_structure_can_be_changed_too_not_only_numbers(self, client, imported):
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        model["bands"]["bands"].append({
            "label": "a band somebody added", "lower": 0.05, "rate": 9.9, "holes": 40,
            "calibration_depth_m": 33.0})
        client.put(f"{BASE}/costing/{SET}/model", json={"model": model})
        body = client.get(f"{BASE}/costing/{SET}").json()
        assert len(body["model"]["bands"]["bands"]) == 5
        assert body["marks"]["bands"] == "yours"

    def test_it_can_be_put_back_on_the_librarys_model(self, client, imported):
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        model["inputs"]["margin"] = 0.30
        client.put(f"{BASE}/costing/{SET}/model", json={"model": model})
        body = client.delete(f"{BASE}/costing/{SET}/model").json()
        assert body["using_own_model"] is False
        assert client.get(f"{BASE}/costing/{SET}").json()["model"]["inputs"]["margin"] == 0.10


class TestTheLastDecisionIsTheEstimators:
    def _a_priced_ref(self, client) -> str:
        body = client.get(f"{BASE}/costing/{SET}").json()
        return next(r["full_ref"] for r in body["priced"]["rows"]
                    if r["source"] == "built" and r["rate_to_submit"] is not None)

    def test_a_rate_can_be_typed_over_the_proposal(self, client, imported):
        ref = self._a_priced_ref(client)
        saved = client.post(f"{BASE}/costing/rate",
                            json={"set_id": SET, "full_ref": ref, "rate": 1234.0},
                            headers={"X-CBOQ-Actor": "SW"})
        assert saved.status_code == 200
        row = next(r for r in client.get(f"{BASE}/costing/{SET}").json()["priced"]["rows"]
                   if r["full_ref"] == ref)
        assert row["rate_to_submit"] == 1234.0 and row["overridden"]
        assert row["rate_rounded"] != 1234.0, "the proposal stays visible beside it"

    def test_the_amount_follows_the_typed_rate(self, client, imported):
        ref = self._a_priced_ref(client)
        client.post(f"{BASE}/costing/rate",
                    json={"set_id": SET, "full_ref": ref, "rate": 1000.0})
        row = next(r for r in client.get(f"{BASE}/costing/{SET}").json()["priced"]["rows"]
                   if r["full_ref"] == ref)
        expected = 1000.0 if row["lump"] else (row["qty"] or 0) * 1000.0
        assert row["amount"] == pytest.approx(expected)

    def test_the_proposal_can_be_put_back(self, client, imported):
        ref = self._a_priced_ref(client)
        client.post(f"{BASE}/costing/rate", json={"set_id": SET, "full_ref": ref, "rate": 5.0})
        client.post(f"{BASE}/costing/rate", json={"set_id": SET, "full_ref": ref, "rate": None})
        row = next(r for r in client.get(f"{BASE}/costing/{SET}").json()["priced"]["rows"]
                   if r["full_ref"] == ref)
        assert not row["overridden"]

    def test_an_item_the_bill_does_not_have_is_refused(self, client, imported):
        response = client.post(f"{BASE}/costing/rate",
                               json={"set_id": SET, "full_ref": "99.99", "rate": 1.0})
        assert response.status_code == 404


class TestTheRegisterIsTheHumanGate:
    def test_a_verdict_is_recorded_against_a_name(self, client, imported):
        body = client.post(f"{BASE}/costing/assumption",
                           json={"set_id": SET, "key": "rock_fraction", "status": "Accepted"},
                           headers={"X-CBOQ-Actor": "SW"}).json()
        assert body["reviewed_by"] == "SW"
        row = next(r for r in client.get(f"{BASE}/costing/{SET}").json()["register"]["rows"]
                   if r["key"] == "rock_fraction")
        assert row["status"] == "Accepted" and row["reviewed_by"] == "SW"

    def test_the_gate_clears_only_when_every_row_is_ruled_on(self, client, imported):
        rows = client.get(f"{BASE}/costing/{SET}").json()["register"]["rows"]
        for row in rows:
            body = client.post(f"{BASE}/costing/assumption",
                               json={"set_id": SET, "key": row["key"], "status": "Accepted"}).json()
        assert body["gate"] == "CLEARED" and body["outstanding"] == 0

    def test_an_invented_verdict_is_refused_and_the_real_ones_named(self, client, imported):
        response = client.post(f"{BASE}/costing/assumption",
                               json={"set_id": SET, "key": "margin", "status": "Probably"})
        assert response.status_code == 422 and "Accepted" in response.json()["detail"]

    def test_an_unreviewed_register_does_not_stop_the_workbook(self, client, imported):
        # It warns; the sweep is the app's only hard stop. But the sheet says NOT CLEARED.
        assert client.get(f"{BASE}/costing/{SET}/workbook.xlsx").status_code == 200


class TestTheDeliverable:
    def test_the_workbook_downloads_as_an_excel_file(self, client, imported):
        response = client.get(f"{BASE}/costing/{SET}/workbook.xlsx")
        assert response.status_code == 200
        assert "spreadsheetml" in response.headers["content-type"]
        assert f"costing_{SET}" in response.headers["content-disposition"]

    def test_it_has_the_eight_sheets(self, client, imported):
        raw = client.get(f"{BASE}/costing/{SET}/workbook.xlsx").content
        book = openpyxl.load_workbook(io.BytesIO(raw))
        assert book.sheetnames[0] == "00 README"
        assert book.sheetnames[-1] == "07 Empirical Basis"
        assert len(book.sheetnames) == 8

    def test_it_still_calculates(self, client, imported):
        raw = client.get(f"{BASE}/costing/{SET}/workbook.xlsx").content
        book = openpyxl.load_workbook(io.BytesIO(raw))
        formulas = [cell.value for row in book["02 Production"].iter_rows() for cell in row
                    if isinstance(cell.value, str) and cell.value.startswith("=")]
        assert any("MATCH(" in f for f in formulas), "the band is looked up, not pasted"

    def test_a_model_change_reaches_the_workbook(self, client, imported):
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        model["spread"].append({
            "key": "barge", "label": "A barge somebody added", "block": "PLANT",
            "multiplier": 1.0, "rate": 8000.0, "unit": "$/day", "charge": "rig_day", "note": ""})
        client.put(f"{BASE}/costing/{SET}/model", json={"model": model})
        raw = client.get(f"{BASE}/costing/{SET}/workbook.xlsx").content
        book = openpyxl.load_workbook(io.BytesIO(raw))
        labels = [cell.value for row in book["03 Resource Rates"].iter_rows() for cell in row]
        assert "A barge somebody added" in labels

    def test_a_set_with_no_bill_says_so_rather_than_producing_an_empty_workbook(self, client):
        response = client.get(f"{BASE}/costing/nothing-here/workbook.xlsx")
        assert response.status_code == 404
        assert "Import the client's workbook" in response.json()["detail"]
