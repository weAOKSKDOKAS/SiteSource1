"""The BOQ HTTP surface: import, diff, carry, price, check, and the re-price gate.

The rule these defend: **a revision reopens the rates that depended on it.** The review side already
tears up a clause verdict when an addendum rewrites the wording it was given on. This is the same
rule applied to money, and it is the only thing in this package that blocks.

Why it has to block: GCT Appendix C 2.2(v) carries your rate onto a changed quantity without
comment, which is a correction rule, not a decision anybody made. The reference addendum multiplied
three groundwater-monitoring quantities by 2.17 under exactly that rule — a rate built for six
months of monitoring silently inherited by twelve.
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
def workbooks(tmp_path):
    return {rev: build_bill_workbook(tmp_path / f"bq-{rev}.xlsx", rev) for rev in (0, 1, 2)}


def _import(client: TestClient, path, rev: int | None = None) -> dict:
    data = {"set_id": SET}
    if rev is not None:
        data["rev"] = str(rev)
    with open(path, "rb") as handle:
        response = client.post(
            f"{BASE}/boq/import", data=data,
            files={"file": (path.name, handle.read(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    return response.json()


class TestImport:
    def test_a_workbook_becomes_a_revision_and_reports_what_it_could_not_do_cleanly(
            self, client, workbooks):
        body = _import(client, workbooks[0])
        assert body["rev"] == 0 and body["items"] == 23
        assert body["pre_priced"] == 3                     # Bill 9 arrives priced by the client
        assert any("past column H" in note for note in body["notes"])
        stranded = next(e for e in body["item_notes"] if e["full_ref"] == "1.16")
        assert "caption row above" in stranded["notes"][0]

    def test_revisions_append_and_the_operative_one_is_the_highest(self, client, workbooks):
        _import(client, workbooks[0])
        _import(client, workbooks[1])
        _import(client, workbooks[2])
        body = client.get(f"{BASE}/boq/{SET}").json()
        assert body["rev"] == 2
        assert [entry["rev"] for entry in body["revisions"]] == [0, 1, 2]

    def test_a_superseded_revision_stays_readable(self, client, workbooks):
        _import(client, workbooks[0])
        _import(client, workbooks[1])
        older = client.get(f"{BASE}/boq/{SET}", params={"rev": 0}).json()
        # Nothing is ever destroyed: Rev 0 survives Rev 1, which is the only reason a diff exists.
        assert older["rev"] == 0
        assert next(i for i in older["items"] if i["full_ref"] == "6.4")["qty"] == 1128

    def test_a_non_workbook_is_refused_with_the_reason(self, client, tmp_path):
        response = client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": ("bill.pdf", b"%PDF-1.4", "application/pdf")})
        assert response.status_code == 422
        assert "Microsoft Excel" in response.json()["detail"] or ".xlsx" in response.json()["detail"]

    def test_an_unreadable_workbook_reports_rather_than_500s(self, client):
        response = client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": ("bill.xlsx", b"not a workbook at all",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert response.status_code == 422
        assert "Could not read" in response.json()["detail"]

    def test_a_missing_bill_404s_with_what_to_do_about_it(self, client):
        response = client.get(f"{BASE}/boq/nobody")
        # RE-ANCHORED: pinned the endpoint name; the message now names the Price tab instead.
        assert response.status_code == 404
        assert "Import the client's workbook on the Price tab" in response.json()["detail"]


class TestDiff:
    def test_the_unannounced_quantity_change_is_the_headline(self, client, workbooks):
        _import(client, workbooks[0])
        _import(client, workbooks[1])
        body = client.get(f"{BASE}/boq/{SET}/diff/0/1").json()
        quantities = {c["full_ref"] for c in body["changes"] if c["kind"] == "qty"}
        assert {"6.4", "6.5", "6.6"} <= quantities
        assert body["moved_only"], "items pushed down by the split must be seen and dismissed"

    def test_the_worklist_is_what_a_person_has_to_look_at(self, client, workbooks):
        _import(client, workbooks[0])
        _import(client, workbooks[1])
        body = client.get(f"{BASE}/boq/{SET}/diff/0/1").json()
        assert {e["full_ref"] for e in body["worklist"]} >= {"6.4", "6.5", "6.6", "2.2a", "2.2b"}


class TestTheRepriceGate:
    def _priced_rev0(self, client, workbooks) -> None:
        _import(client, workbooks[0])
        for ref, rate in (("6.4", 42.0), ("6.5", 38.0), ("6.6", 55.0)):
            assert client.post(f"{BASE}/boq/rate",
                               json={"set_id": SET, "full_ref": ref, "rate": rate}).status_code == 200

    def test_sign_off_is_refused_while_a_carried_rate_is_unlooked_at(self, client, workbooks):
        self._priced_rev0(client, workbooks)
        _import(client, workbooks[1])
        client.post(f"{BASE}/boq/carry",
                    json={"set_id": SET, "from_rev": 0, "to_rev": 1, "apply": True})

        response = client.post(f"{BASE}/boq/{SET}/revision/1/sign-off")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "6.4" in detail and "not a decision anyone made" in detail

    def test_confirming_each_one_opens_the_gate(self, client, workbooks):
        self._priced_rev0(client, workbooks)
        _import(client, workbooks[1])
        body = client.post(f"{BASE}/boq/carry",
                           json={"set_id": SET, "from_rev": 0, "to_rev": 1, "apply": True}).json()
        for entry in body["needs_review"]:
            client.post(f"{BASE}/boq/rate", json={
                "set_id": SET, "rev": 1, "full_ref": entry["full_ref"],
                "rate": entry["rate"] if entry["rate"] is not None else 1.0,
                "needs_review": False,
            })
        assert client.post(f"{BASE}/boq/{SET}/revision/1/sign-off").status_code == 200

    def test_the_rate_is_carried_even_though_it_is_flagged(self, client, workbooks):
        self._priced_rev0(client, workbooks)
        _import(client, workbooks[1])
        body = client.post(f"{BASE}/boq/carry",
                           json={"set_id": SET, "from_rev": 0, "to_rev": 1, "apply": True}).json()
        carried = {e["full_ref"]: e for e in body["carried"]}
        # App C 2.2(v) says use the same rate. It does. And it says so, and flags it.
        assert carried["6.4"]["rate"] == 42.0 and carried["6.4"]["needs_review"] is True
        assert "same rate shall be used" in carried["6.4"]["rule"]

    def test_carry_without_apply_writes_nothing(self, client, workbooks):
        self._priced_rev0(client, workbooks)
        _import(client, workbooks[1])
        client.post(f"{BASE}/boq/carry", json={"set_id": SET, "from_rev": 0, "to_rev": 1})
        assert client.post(f"{BASE}/boq/{SET}/revision/1/sign-off").status_code == 200


class TestRatesAndAssumptions:
    def test_a_client_priced_item_refuses_a_rate(self, client, workbooks):
        _import(client, workbooks[0])
        response = client.post(f"{BASE}/boq/rate",
                               json={"set_id": SET, "full_ref": "9.1", "rate": 1.0})
        assert response.status_code == 409
        assert "reinstates the client's figure" in response.json()["detail"]

    def test_an_unknown_item_404s(self, client, workbooks):
        _import(client, workbooks[0])
        response = client.post(f"{BASE}/boq/rate",
                               json={"set_id": SET, "full_ref": "99.9", "rate": 1.0})
        assert response.status_code == 404

    def test_saving_a_rate_extends_it_against_the_clients_quantity(self, client, workbooks):
        _import(client, workbooks[0])
        body = client.post(f"{BASE}/boq/rate",
                           json={"set_id": SET, "full_ref": "6.4", "rate": 42.0}).json()
        assert body["amount"] == round(1128 * 42.0, 2) and body["badge"] == "user"

    def test_a_mix_that_does_not_reconcile_is_refused_with_both_figures(self, client, workbooks):
        _import(client, workbooks[0])
        response = client.post(f"{BASE}/boq/assumption", json={
            "set_id": SET,
            "assumption": {"full_ref": "2.4", "basis": "guessed",
                           "conditions": [{"label": "soil", "qty": 1800, "output": 12,
                                           "crew_ref": "LAB-GEN"}]},
        })
        assert response.status_code == 422
        assert "1,800" in response.json()["detail"] and "2,300" in response.json()["detail"]

    def test_a_mix_that_reconciles_is_expanded_into_shifts(self, client, workbooks):
        _import(client, workbooks[0])
        body = client.post(f"{BASE}/boq/assumption", json={
            "set_id": SET,
            "assumption": {
                "full_ref": "2.4",
                "basis": "hole schedule from GI/201-205; rock share from the historical logs",
                "source_part_id": "12-drg", "source_page": 4,
                "conditions": [
                    {"label": "soil, 0-20m, Class A", "qty": 1800, "output": 12,
                     "crew_ref": "LAB-GEN", "plant_ref": "PLT-EXC"},
                    {"label": "soil, 0-20m, Class B", "qty": 500, "output": 8,
                     "crew_ref": "LAB-GEN", "plant_ref": "PLT-EXC"},
                ],
            },
        }).json()
        assert [entry["shifts"] for entry in body["shifts"]] == [150.0, 62.5]
        assert body["weighted_output"] == 10.82                   # 2,300 / 212.5
        assert body["build_up"]["item_id"] == "2.4"


class TestPricedAndChecks:
    def test_the_bill_prices_from_what_is_stored(self, client, workbooks):
        _import(client, workbooks[0])
        client.post(f"{BASE}/boq/rate", json={"set_id": SET, "full_ref": "6.4", "rate": 42.0})
        body = client.get(f"{BASE}/boq/{SET}/priced").json()
        entry = next(i for i in body["items"] if i["full_ref"] == "6.4")
        assert entry["unit_rate"] == 42.0 and entry["amount"] == round(1128 * 42.0, 2)
        assert entry["rate_source"] == "carried"

    def test_the_checks_name_the_clause_each_enforces(self, client, workbooks):
        _import(client, workbooks[0])
        body = client.get(f"{BASE}/boq/{SET}/checks", params={"fee_pct": 45}).json()
        assert body["counts"]["unpriced_item"] > 0
        unpriced = next(f for f in body["flags"] if f["kind"] == "unpriced_item")
        assert "General Preambles 6" in unpriced["message"]
        fee = next(f for f in body["flags"] if f["kind"] == "fee_percentage_out_of_range")
        assert "SCT 19" in fee["message"]

    def test_the_client_inserted_sums_are_checked_against_the_workbook(self, client, workbooks):
        _import(client, workbooks[0])
        body = client.get(f"{BASE}/boq/{SET}/checks").json()
        assert "provisional_sum_altered" not in body["counts"]


class TestTheRouteSurface:
    def test_every_boq_route_is_mounted(self, client):
        paths = set(client.app.openapi()["paths"])       # CLAUDE.md trap 1: never app.routes
        assert {
            f"{BASE}/boq/import",
            f"{BASE}/boq/{{set_id}}",
            f"{BASE}/boq/{{set_id}}/diff/{{from_rev}}/{{to_rev}}",
            f"{BASE}/boq/carry",
            f"{BASE}/boq/rate",
            f"{BASE}/boq/assumption",
            f"{BASE}/boq/{{set_id}}/priced",
            f"{BASE}/boq/{{set_id}}/checks",
            f"{BASE}/boq/{{set_id}}/revision/{{rev}}/sign-off",
        } <= paths
