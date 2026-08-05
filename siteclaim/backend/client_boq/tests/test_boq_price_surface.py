"""The Price HTTP surface: the working, the coverage checklist, and the gate.

The rule these defend: **silence is not neutral on this contract.**

    General Preambles ¶6 — "Items against which no rate is entered shall be deemed to be covered by
    the other rates in the bill of quantities."

So a cost nobody routed is not an open question. It is a promise to do that work for nothing, for the
life of a remeasured contract, and the sweep is the one place in this product that refuses to let you
past. Everything else warns.

The coverage tests defend the other half: the list is a rule's and the ticks are a person's. There is
no code path by which a model can settle a head, in the same way there is none by which it can write
a clause verdict.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.tests._bqfixture import build_bill_workbook

pytest.importorskip("openpyxl")

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


@pytest.fixture
def priced(client, tmp_path):
    """A set with the client's bill imported — the minimum for any of this to mean anything."""
    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as handle:
        response = client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": (path.name, handle.read(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    return response.json()


def _refs(client, bill_no: str = "") -> list[str]:
    body = client.get(f"{BASE}/boq/{SET}").json()
    return [i["full_ref"] for i in body["items"]
            if not i["is_parent"] and not i["pre_priced"]
            and (not bill_no or i["bill_no"] == bill_no)]


def _drilling_ref(client) -> str:
    """A Bill No.2 item — the only section whose item coverage is transcribed so far."""
    refs = _refs(client, "2")
    assert refs, "the fixture bill should carry Section 2 items"
    return refs[0]


class TestWhatARateMustCover:
    def test_the_list_arrives_with_nothing_ticked(self, client, priced):
        ref = _drilling_ref(client)
        body = client.get(f"{BASE}/price/{SET}/coverage/{ref}").json()
        assert body["entries"], "an item with no coverage list would be a rate with no obligations"
        assert all(not e["ticked"] for e in body["entries"])
        assert body["settled"] is False

    def test_every_head_names_the_clause_that_put_it_there(self, client, priced):
        body = client.get(f"{BASE}/price/{SET}/coverage/{_drilling_ref(client)}").json()
        assert all(e["clause_ref"] for e in body["entries"])

    def test_a_head_whose_clause_the_index_has_not_been_read_for_admits_it(self, client, priced):
        body = client.get(f"{BASE}/price/{SET}/coverage/{_drilling_ref(client)}").json()
        cited = [e for e in body["entries"] if e["key"].startswith("ps.")]
        assert cited and all("has not been read" in e["unresolved"] for e in cited)

    def test_ticking_puts_a_name_on_it(self, client, priced):
        ref = _drilling_ref(client)
        head = client.get(f"{BASE}/price/{SET}/coverage/{ref}").json()["entries"][0]["key"]
        saved = client.post(f"{BASE}/price/coverage/tick",
                            json={"set_id": SET, "full_ref": ref, "head_key": head, "ticked": True},
                            headers={"X-CBOQ-Actor": "SW"})
        assert saved.status_code == 200 and saved.json()["ticked_by"] == "SW"

        body = client.get(f"{BASE}/price/{SET}/coverage/{ref}").json()
        entry = next(e for e in body["entries"] if e["key"] == head)
        assert entry["ticked"] and entry["ticked_by"] == "SW" and entry["ticked_at"]

    def test_unticking_takes_the_name_off_again(self, client, priced):
        ref = _drilling_ref(client)
        head = client.get(f"{BASE}/price/{SET}/coverage/{ref}").json()["entries"][0]["key"]
        for ticked in (True, False):
            client.post(f"{BASE}/price/coverage/tick",
                        json={"set_id": SET, "full_ref": ref, "head_key": head, "ticked": ticked},
                        headers={"X-CBOQ-Actor": "SW"})
        entry = next(e for e in client.get(f"{BASE}/price/{SET}/coverage/{ref}").json()["entries"]
                     if e["key"] == head)
        assert not entry["ticked"] and entry["ticked_by"] == ""

    def test_the_thirty_one_deemed_included_heads_are_ticked_once_for_the_whole_bill(
            self, client, priced):
        refs = _refs(client, "2")
        client.post(f"{BASE}/price/coverage/tick",
                    json={"set_id": SET, "full_ref": "", "head_key": "preambles.deemed",
                          "ticked": True},
                    headers={"X-CBOQ-Actor": "SW"})
        # One tick, and it shows against every item — not twenty-seven separate decisions about the
        # same thirty-one clauses.
        for ref in refs[:3]:
            body = client.get(f"{BASE}/price/{SET}/coverage/{ref}").json()
            assert body["bill_level"]["ticked"] is True

    def test_the_summary_line_says_how_many_are_left(self, client, priced):
        body = client.get(f"{BASE}/price/{SET}/coverage/{_drilling_ref(client)}").json()
        assert "not covered" in body["summary"]

    def test_the_reason_it_matters_is_on_the_response(self, client, priced):
        body = client.get(f"{BASE}/price/{SET}/coverage/{_drilling_ref(client)}").json()
        assert "shall not be measured" in body["note"]

    def test_an_item_the_bill_does_not_have_is_a_404(self, client, priced):
        response = client.get(f"{BASE}/price/{SET}/coverage/99.99")
        assert response.status_code == 404

    def test_an_untranscribed_section_says_so_instead_of_showing_an_empty_checklist(
            self, client, priced):
        # Only Section 2's item coverage has been transcribed. An empty list on Section 1 must read
        # as "nobody has read this yet", never as "this rate carries no obligations" — the two look
        # identical on screen and mean opposite things to somebody about to price the item.
        other = next(r for r in _refs(client) if r not in _refs(client, "2"))
        body = client.get(f"{BASE}/price/{SET}/coverage/{other}").json()
        assert body["entries"] == []
        assert "has not been transcribed yet" in body["waiting_on"]
        assert "not because the rate carries no obligations" in body["waiting_on"]


class TestTheWorking:
    def test_an_unpriced_item_says_what_it_is_waiting_for(self, client, priced):
        body = client.get(f"{BASE}/price/{SET}/trace/{_drilling_ref(client)}").json()
        assert body["priced"] is False
        assert "no rate yet" in body["waiting_on"]

    def test_a_rate_comes_back_as_a_tree_rather_than_a_number(self, client, priced):
        ref = _drilling_ref(client)
        item = next(i for i in client.get(f"{BASE}/boq/{SET}").json()["items"]
                    if i["full_ref"] == ref)
        client.post(f"{BASE}/boq/rate", json={
            "set_id": SET, "full_ref": ref, "rate": 100.0, "basis": "built"})
        body = client.get(f"{BASE}/price/{SET}/trace/{ref}").json()
        root = body["trace"]["root"]
        assert root["label"] == "rate"
        assert root["children"], "a rate with no children is a bare number, which is the failure"
        assert item is not None

    def test_the_tree_reports_leaves_that_cannot_say_where_they_came_from(self, client, priced):
        ref = _drilling_ref(client)
        client.post(f"{BASE}/boq/rate", json={
            "set_id": SET, "full_ref": ref, "rate": 100.0, "basis": "built"})
        body = client.get(f"{BASE}/price/{SET}/trace/{ref}").json()
        # No groups and no resource sheet yet, so the build-up genuinely has nothing under it — and
        # saying so is the point. A tree that looked complete here would be lying.
        assert body["trace"]["problems"]


class TestTheSweep:
    def test_an_empty_sweep_settles(self, client, priced):
        assert client.post(f"{BASE}/price/{SET}/sweep/settle").status_code == 200

    def test_an_unrouted_cost_blocks_and_says_what_silence_costs(self, client, priced):
        client.post(f"{BASE}/price/sweep", json={
            "set_id": SET, "key": "traffic", "label": "Temporary traffic arrangements",
            "source": "SMM S02 ¶2.13(h)", "amount": 40000.0})
        response = client.post(f"{BASE}/price/{SET}/sweep/settle")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "Temporary traffic arrangements" in detail
        assert "General Preambles" in detail and "for free" in detail

    def test_each_of_the_four_routes_settles_it(self, client, priced):
        target = _refs(client)[0]
        for key, route, extra in (
            ("q", "query", {}),
            ("s", "spread", {}),
            ("l", "load", {"target_ref": target}),
            ("a", "accept", {"reason": "we think the PM will instruct it"}),
        ):
            client.post(f"{BASE}/price/sweep", json={
                "set_id": SET, "key": key, "label": key, "amount": 1000.0,
                "route": route, **extra})
        assert client.post(f"{BASE}/price/{SET}/sweep/settle").status_code == 200

    def test_loading_onto_an_item_that_is_not_in_the_bill_is_refused(self, client, priced):
        response = client.post(f"{BASE}/price/sweep", json={
            "set_id": SET, "key": "platform", "label": "Access platform", "amount": 210000.0,
            "route": "load", "target_ref": "99.99"})
        assert response.status_code == 422 and "no item" in response.json()["detail"]

    def test_a_risk_accepted_without_a_reason_is_refused(self, client, priced):
        # A risk somebody took deliberately and one nobody noticed look identical six months later.
        response = client.post(f"{BASE}/price/sweep", json={
            "set_id": SET, "key": "rock", "label": "Harder ground than billed", "amount": 50000.0,
            "route": "accept"})
        assert response.status_code == 422 and "reason" in response.json()["detail"]

    def test_an_invented_route_is_refused_and_the_real_ones_named(self, client, priced):
        response = client.post(f"{BASE}/price/sweep", json={
            "set_id": SET, "key": "x", "label": "x", "route": "ignore"})
        assert response.status_code == 422
        assert "not a route" in response.json()["detail"]
        assert "spread" in response.json()["detail"]

    def test_the_sweep_totals_what_each_route_carries(self, client, priced):
        target = _refs(client)[0]
        client.post(f"{BASE}/price/sweep", json={
            "set_id": SET, "key": "uniform", "label": "Site uniform", "amount": 12000.0,
            "route": "spread"})
        client.post(f"{BASE}/price/sweep", json={
            "set_id": SET, "key": "platform", "label": "Access platform", "amount": 210000.0,
            "route": "load", "target_ref": target})
        body = client.get(f"{BASE}/price/{SET}/sweep").json()
        assert body["spread_total"] == 12000.0
        assert body["loadings"] == {target: 210000.0}
        assert body["settled"] is True

    def test_a_queried_cost_needs_no_amount_yet(self, client, priced):
        # You raise the question before you know what the answer costs.
        response = client.post(f"{BASE}/price/sweep", json={
            "set_id": SET, "key": "heli", "label": "Helicopter access, ABH244", "route": "query"})
        assert response.status_code == 200
        assert client.post(f"{BASE}/price/{SET}/sweep/settle").status_code == 200

    def test_routing_stamps_who_decided_it(self, client, priced):
        client.post(f"{BASE}/price/sweep",
                    json={"set_id": SET, "key": "u", "label": "Uniform", "amount": 1.0,
                          "route": "spread"},
                    headers={"X-CBOQ-Actor": "SW"})
        cost = client.get(f"{BASE}/price/{SET}/sweep").json()["costs"][0]
        assert cost["decided_by"] == "SW"

    def test_an_unrouted_cost_has_nobody_on_it_because_nobody_has_decided_anything(
            self, client, priced):
        client.post(f"{BASE}/price/sweep",
                    json={"set_id": SET, "key": "u", "label": "Uniform", "amount": 1.0},
                    headers={"X-CBOQ-Actor": "SW"})
        assert client.get(f"{BASE}/price/{SET}/sweep").json()["costs"][0]["decided_by"] == ""

    def test_the_warning_travels_with_the_sweep(self, client, priced):
        body = client.get(f"{BASE}/price/{SET}/sweep").json()
        assert "General Preambles" in body["warning"]
        assert sorted(body["routes"]) == ["accept", "load", "query", "spread"]


class TestTheSweepIsWhereSitesMissingGateLands:
    def test_an_unclassed_hole_refuses_the_settle(self, client, priced):
        client.post(f"{BASE}/site/schedule", json={
            "set_id": SET,
            "schedule": {"set_id": SET, "stations": [
                {"station": "CE19-ABH01", "soil_m": 30.0, "length_m": 30.0}]},
        })
        response = client.post(f"{BASE}/price/{SET}/sweep/settle")
        assert response.status_code == 409
        assert "CE19-ABH01" in response.json()["detail"]
        assert "has not been priced" in response.json()["detail"]

    def test_classing_it_lets_the_settle_through(self, client, priced):
        client.post(f"{BASE}/site/schedule", json={
            "set_id": SET,
            "schedule": {"set_id": SET, "stations": [
                {"station": "CE19-ABH01", "soil_m": 30.0, "length_m": 30.0}]},
        })
        client.post(f"{BASE}/site/class",
                    json={"set_id": SET, "station": "CE19-ABH01", "access_class": "A"})
        assert client.post(f"{BASE}/price/{SET}/sweep/settle").status_code == 200
