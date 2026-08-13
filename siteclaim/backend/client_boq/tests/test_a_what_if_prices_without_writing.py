"""Type the change, see the diff, then accept it — and the preview writes nothing.

THE SPLIT THIS KEEPS. You say what you want to assume in your own words; a model proposes WHICH
input of the costing model that moves and to what; the DETERMINISTIC engine recalculates what
that does to the money. No model writes a number here — it writes a proposed input, and the
engine everything else uses computes the consequence. That is the product's one rule, applied to
the one feature most likely to erode it.

Both figures come from `_costing`, the single path the real screens use, so the total you accept
is the total you get: a preview computed by a second, simpler routine would eventually disagree
with the real one, and then the number a person accepted would not be the number they got.

Applying stays the ordinary propose-and-confirm act — record the condition, confirm the mapping —
and the confirm is the only writer. These tests pin that the preview alone changes nothing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    pytest.importorskip("openpyxl")
    from api import app

    return TestClient(app)


@pytest.fixture
def priced(client, tmp_path):
    from client_boq.tests._bqfixture import build_bill_workbook

    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as fh:
        assert client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": (path.name, fh.read(), "application/vnd.ms-excel")},
        ).status_code == 200
    return client.get(f"{BASE}/costing/{SET}").json()


def _model_inputs(client):
    return client.get(f"{BASE}/costing/{SET}").json()["model"]["inputs"]


class TestItPricesTheHypothetical:
    def test_a_named_input_moves_the_money_and_says_by_how_much(self, client, priced):
        """The direct path: no model call at all, just the engine pricing a different number."""
        inputs = _model_inputs(client)
        key = "margin" if "margin" in inputs else sorted(inputs)[0]
        current = float(inputs[key])

        body = client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": f"inputs.{key}", "value": current * 1.5 + 1.0}).json()
        assert body["applies"] is True
        assert body["before"]["total"] == pytest.approx(priced["priced"]["total"])
        assert body["after"]["total"] != pytest.approx(body["before"]["total"])
        assert body["delta"]["total"] == pytest.approx(
            body["after"]["total"] - body["before"]["total"], abs=0.01)

    def test_the_before_figure_is_the_screens_own_figure(self, client, priced):
        """Same engine, same path — or the number somebody accepts is not the number they get."""
        inputs = _model_inputs(client)
        key = sorted(inputs)[0]
        body = client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": f"inputs.{key}", "value": float(inputs[key])}).json()
        assert body["before"] == pytest.approx(body["after"]), (
            "an unchanged input must price identically — the preview is the same engine")

    def test_it_names_which_rates_moved_not_only_the_total(self, client, priced):
        inputs = _model_inputs(client)
        key = "margin" if "margin" in inputs else sorted(inputs)[0]
        body = client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": f"inputs.{key}",
            "value": float(inputs[key]) * 2 + 1.0}).json()
        assert body["moved_count"] >= 1, "a total that changed by itself says nothing about where"
        first = body["moved"][0]
        assert {"full_ref", "description", "was", "now"} <= set(first)
        assert first["was"] != first["now"]


class TestItWritesNothing:
    def test_the_stored_model_is_untouched_afterwards(self, client, priced):
        inputs = _model_inputs(client)
        key = sorted(inputs)[0]
        before = dict(inputs)

        client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": f"inputs.{key}", "value": float(inputs[key]) * 3 + 7.0})

        assert _model_inputs(client) == before, "a preview that saved would be the worst misread"

    def test_the_priced_total_is_unchanged_afterwards(self, client, priced):
        inputs = _model_inputs(client)
        key = sorted(inputs)[0]
        client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": f"inputs.{key}", "value": float(inputs[key]) * 3 + 7.0})
        assert client.get(f"{BASE}/costing/{SET}").json()["priced"]["total"] == pytest.approx(
            priced["priced"]["total"])

    def test_it_says_so_on_the_response(self, client, priced):
        inputs = _model_inputs(client)
        key = sorted(inputs)[0]
        body = client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": f"inputs.{key}", "value": float(inputs[key]) + 1}).json()
        assert "Nothing has been changed" in body["note"]
        assert "confirm" in body["note"]


class TestItRefusesRatherThanGuessing:
    def test_an_input_this_model_does_not_have_is_refused_by_name(self, client, priced):
        body = client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": "inputs.unicorns", "value": 5.0}).json()
        assert body["applies"] is False
        assert "unicorns" in body["proposal"]["cannot_map"]
        assert any("REFUSED" in line for line in body["proposal"]["checked"])

    def test_nothing_to_price_says_what_it_needs(self, client, priced):
        body = client.post(f"{BASE}/costing/what-if", json={"set_id": SET}).json()
        assert body["applies"] is False and body["waiting_on"]

    def test_a_tender_with_no_bill_is_a_404_not_a_zero(self, client):
        assert client.post(f"{BASE}/costing/what-if", json={
            "set_id": "nothing-here", "path": "inputs.margin", "value": 1.0}).status_code == 404


class TestTheProposalCannotDecide:
    def test_the_proposal_type_has_no_field_for_a_verdict(self):
        """Same structural guard as DepartureProposal: a stage with no field for a decision
        cannot make one, whatever a prompt says."""
        from client_boq.boq.conditions import ConditionProposal, RawConditionMapping

        assert not {"status", "applied", "confirmed", "decided_by"} & set(
            ConditionProposal.model_fields)
        assert set(RawConditionMapping.model_fields) == {
            "path", "value", "basis", "confidence", "cannot_map"}
