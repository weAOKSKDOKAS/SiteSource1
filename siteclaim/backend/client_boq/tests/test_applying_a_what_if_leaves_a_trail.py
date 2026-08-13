"""Apply a previewed change in one act — and it is still a person's decision, still auditable.

THE DECISION THE OWNER TOOK. The preview used to require a second click on the register to
confirm the mapping. That is now one act: you read the diff — the total, the programme, every
rate that moved — and press the button.

WHY PROPOSE-AND-CONFIRM STILL HOLDS, exactly. No model reaches the apply endpoint: it takes a
path and a number that a person has just looked at, and the press IS the confirmation. What was
removed is a second click on the same decision, not the decision. The proof is structural and
pinned below — the endpoint refuses a path the model does not have, and it writes through the
register's own three writers rather than around them, so a change made this way is
indistinguishable in the audit from one confirmed line by line.

AND IT IS REVERSIBLE, which is what makes it safe to be fast: the previous value comes back on
the response and is recorded on the condition, so putting it back is the same call with the old
number.
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


def _an_input(client) -> tuple[str, float]:
    inputs = client.get(f"{BASE}/costing/{SET}").json()["model"]["inputs"]
    key = "margin" if "margin" in inputs else sorted(inputs)[0]
    return key, float(inputs[key])


class TestItAppliesWhatWasPreviewed:
    def test_the_applied_total_is_the_previewed_total(self, client, priced):
        """The point of one engine: the number you accepted is the number you got."""
        key, current = _an_input(client)
        target = current * 2 + 1.0

        preview = client.post(f"{BASE}/costing/what-if", json={
            "set_id": SET, "path": f"inputs.{key}", "value": target}).json()
        assert preview["applies"] is True

        applied = client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                              json={"set_id": SET, "path": f"inputs.{key}", "value": target,
                                    "instruction": "assume it doubles"}).json()
        assert applied["applied"] is True
        assert applied["after"]["total"] == pytest.approx(preview["after"]["total"])
        assert client.get(f"{BASE}/costing/{SET}").json()["priced"]["total"] == pytest.approx(
            preview["after"]["total"])

    def test_the_input_actually_moved_on_this_tender(self, client, priced):
        key, current = _an_input(client)
        client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "path": f"inputs.{key}", "value": current + 3.0})
        body = client.get(f"{BASE}/costing/{SET}").json()
        assert float(body["model"]["inputs"][key]) == pytest.approx(current + 3.0)
        assert body["using_own_model"] is True, "copy-on-write: the library is never touched"


class TestTheTrailIsTheRegistersOwn:
    def test_it_lands_on_the_register_confirmed_with_a_name_on_it(self, client, priced):
        key, current = _an_input(client)
        applied = client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                              json={"set_id": SET, "path": f"inputs.{key}",
                                    "value": current + 5.0,
                                    "instruction": "assume three rigs"}).json()

        rows = client.get(f"{BASE}/costing/{SET}/conditions").json()["conditions"]
        row = next(r for r in rows if r["condition_id"] == applied["condition_id"])
        assert row["text"] == "assume three rigs", "your sentence, verbatim"
        assert row["status"] == "confirmed" and row["decided_by"] == "SW"
        assert row["applied_value"] == pytest.approx(current + 5.0)
        assert row["proposed_path"] == f"inputs.{key}"
        assert row["proposal_source"] == "what-if"

    def test_the_previous_value_is_recorded_so_it_can_be_put_back(self, client, priced):
        key, current = _an_input(client)
        applied = client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                              json={"set_id": SET, "path": f"inputs.{key}",
                                    "value": current + 9.0}).json()
        assert applied["was"], "returned, so undo is the same call with the old number"
        rows = client.get(f"{BASE}/costing/{SET}/conditions").json()["conditions"]
        row = next(r for r in rows if r["condition_id"] == applied["condition_id"])
        assert applied["was"] in row["note"]

    def test_undo_is_the_same_call_with_the_old_number(self, client, priced):
        key, current = _an_input(client)
        before_total = priced["priced"]["total"]

        client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "path": f"inputs.{key}", "value": current * 3 + 2.0})
        assert client.get(f"{BASE}/costing/{SET}").json()["priced"]["total"] != pytest.approx(
            before_total)

        client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "path": f"inputs.{key}", "value": current})
        assert client.get(f"{BASE}/costing/{SET}").json()["priced"]["total"] == pytest.approx(
            before_total)


class TestItStillRefuses:
    def test_an_input_this_model_does_not_have_writes_nothing(self, client, priced):
        before = client.get(f"{BASE}/costing/{SET}").json()["model"]["inputs"]
        reply = client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                            json={"set_id": SET, "path": "inputs.unicorns", "value": 5.0})
        assert reply.status_code == 422
        assert "Nothing was written" in reply.json()["detail"]
        assert client.get(f"{BASE}/costing/{SET}").json()["model"]["inputs"] == before

    def test_a_tender_with_no_bill_is_a_404(self, client):
        assert client.post(f"{BASE}/costing/what-if/apply", json={
            "set_id": "nothing-here", "path": "inputs.margin", "value": 1.0}).status_code == 404

    def test_no_model_call_is_involved_in_applying(self, client, priced, monkeypatch):
        """The structural half of "the click is the confirmation": if a model could reach this,
        the press would be confirming something a machine chose after you looked."""
        from client_boq import llm as llm_mod

        def refuse(*_a, **_kw):
            raise AssertionError("apply must not construct an LLM client")

        monkeypatch.setattr(llm_mod, "make_client", refuse)
        key, current = _an_input(client)
        assert client.post(f"{BASE}/costing/what-if/apply", headers={"X-CBOQ-Actor": "SW"},
                           json={"set_id": SET, "path": f"inputs.{key}",
                                 "value": current + 1.0}).status_code == 200
