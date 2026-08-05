"""Pointing one bill item at the thing that should price it.

``_costing`` has always READ these overrides out of the costing state and applied them. Nothing ever
wrote one — the read half of hand-mapping was built and the write half was not. So a proposal the
app got wrong could only be typed over with a flat number, which throws away the build-up behind it:
you got a figure instead of a model, and nothing downstream could explain where it came from.
"""

from __future__ import annotations

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
    response = client.post(
        f"{BASE}/boq/import", data={"set_id": SET},
        files={"file": (path.name, path.read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    return response.json()


def _rows(client) -> dict:
    return {r["full_ref"]: r for r in client.get(f"{BASE}/costing/{SET}").json()["priced"]["rows"]}


def _an_outstanding_ref(client) -> str:
    """A line the model could not price for itself.

    Both states count. A line the model cannot reach is either red or standing on a placeholder
    depending on whether stand-ins are switched on, and pointing it at the right basis is the same
    act either way — that is the whole reason this route exists.
    """
    outstanding = [ref for ref, row in _rows(client).items()
                   if row["source"] in ("unpriced", "placeholder")]
    assert outstanding, "the fixture bill needs at least one line the model cannot reach"
    return outstanding[0]


class TestSettingTheBasis:
    def test_the_route_is_mounted(self, client):
        assert "/client-boq/costing/item-basis" in set(client.app.openapi()["paths"])

    def test_pointing_an_item_at_a_laboratory_rate_prices_it(self, client, imported):
        ref = _an_outstanding_ref(client)
        response = client.post(f"{BASE}/costing/item-basis",
                               json={"set_id": SET, "full_ref": ref, "lab_key": "lab_moisture"})
        assert response.status_code == 200, response.text

        row = _rows(client)[ref]
        assert row["source"] == "lab"
        assert row["lab_key"] == "lab_moisture"
        assert row["rate_to_submit"] is not None

    def test_clearing_it_puts_the_app_s_own_proposal_back(self, client, imported):
        """The same rule the submitted rate follows: an empty value restores the proposal rather
        than meaning "priced at nothing"."""
        ref = _an_outstanding_ref(client)
        client.post(f"{BASE}/costing/item-basis",
                    json={"set_id": SET, "full_ref": ref, "lab_key": "lab_moisture"})
        response = client.post(f"{BASE}/costing/item-basis", json={"set_id": SET, "full_ref": ref})
        assert response.status_code == 200 and response.json()["cleared"] is True
        # Back to whatever the app itself would do with the line — which, with stand-ins on, is a
        # placeholder rather than a red row. Either way it is no longer pointed at the lab rate.
        assert _rows(client)[ref]["source"] in ("unpriced", "placeholder")
        assert _rows(client)[ref]["lab_key"] == ""

    def test_a_preliminaries_resource_can_be_chosen(self, client, imported):
        ref = _an_outstanding_ref(client)
        response = client.post(f"{BASE}/costing/item-basis",
                               json={"set_id": SET, "full_ref": ref, "prelim_key": "prelim_office"})
        assert response.status_code == 200, response.text
        assert _rows(client)[ref]["prelim_key"] == "prelim_office"


class TestWhatItRefuses:
    def test_two_bases_at_once(self, client, imported):
        response = client.post(f"{BASE}/costing/item-basis",
                               json={"set_id": SET, "full_ref": _an_outstanding_ref(client),
                                     "lab_key": "lab_moisture", "basis_key": "soil_drilling"})
        assert response.status_code == 422
        assert "one thing" in response.json()["detail"]

    def test_a_key_that_is_not_in_the_model(self, client, imported):
        response = client.post(f"{BASE}/costing/item-basis",
                               json={"set_id": SET, "full_ref": _an_outstanding_ref(client),
                                     "lab_key": "lab_unicorn"})
        assert response.status_code == 422
        # Name what IS available: a rejection that does not say what would have worked is a dead end.
        assert "Available" in response.json()["detail"]

    def test_an_item_that_is_not_in_the_bill(self, client, imported):
        response = client.post(f"{BASE}/costing/item-basis",
                               json={"set_id": SET, "full_ref": "99.99", "lab_key": "lab_moisture"})
        assert response.status_code == 404

    def test_a_set_with_no_bill(self, client):
        response = client.post(f"{BASE}/costing/item-basis",
                               json={"set_id": "nothing-here", "full_ref": "1.1",
                                     "lab_key": "lab_moisture"})
        assert response.status_code == 404
