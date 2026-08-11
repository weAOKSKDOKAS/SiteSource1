"""The safety net has to fire when the artefact is missing, which is when it was written for.

THE DEFECT. `POST /price/{set_id}/sweep/settle` is the app's only hard stop, and its unclassed-hole
refusal read:

    if schedule is not None:
        unassigned = [s.station for s in schedule.stations if not classes.get(...)]

With no station schedule there are no holes, so no hole is unclassed, so nothing refused. And the
only screen in the whole application that assigns an access class — `HolesView` — sits behind the
take-off gate, so there was no path by which those classes could have been supplied. A tender could
be settled and priced with the net **silently absent rather than tripped**. `chrome.tsx` carried the
mirror of it, computing `⚠ N HOLES UNASSIGNED` over an empty list and reading 0, so the strip said
the same thing about a tender with every hole classified and one where nobody had looked.

WHAT MAKES THE REFUSAL POSSIBLE WITHOUT A TAKE-OFF. The client's own bill. Items 2.2a and 2.2b price
a rig move BY CLASS OF SITE, so if the client billed either, the holes exist and somebody has to say
which class each is — whether or not anybody has read the drawing. No schedule then means the classes
are UNKNOWN, and unknown is a refusal, not a pass.

A bill that prices no rig moves by class still settles, because there is genuinely nothing to
classify. That is the line: the refusal follows the client's document, not a guess.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq import models, store

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _bill(*items: models.BillItem) -> models.ClientBill:
    return models.ClientBill(set_id=SET, rev=0, items=list(items))


def _item(ref: str, *, qty=None, lump=False, unit="nr") -> models.BillItem:
    return models.BillItem(bill_no=ref.split(".")[0], item_ref=ref, full_ref=ref,
                           description=f"item {ref}", unit=unit, qty=qty, lump=lump)


def _save_bill(bill: models.ClientBill) -> None:
    conn = store.get_conn()
    try:
        store.save_bill_revision(conn, bill)
    finally:
        conn.close()


def _settle(client) -> "object":
    return client.post(f"{BASE}/price/{SET}/sweep/settle")


class TestNoTakeOffIsNotAPass:

    def test_a_bill_that_prices_rig_moves_by_class_refuses(self, client):
        """The reproduction. Every hole is unclassed because no hole has been read, and that is
        the state the net exists for."""
        _save_bill(_bill(_item("2.2a", qty=80.0), _item("2.2b", qty=11.0)))
        response = _settle(client)
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert "No station schedule has been read" in detail
        assert "An unknown class is not a cleared one" in detail

    def test_the_refusal_says_where_to_go(self, client):
        _save_bill(_bill(_item("2.2a", qty=80.0)))
        detail = _settle(client).json()["detail"]
        assert "Site step" in detail and "take-off" in detail

    def test_a_lump_rig_move_counts_too(self, client):
        """A rig move billed as an item rather than a quantity is still a rig move."""
        _save_bill(_bill(_item("2.2b", lump=True, unit="item")))
        assert _settle(client).status_code == 409

    def test_either_item_alone_is_enough(self, client):
        _save_bill(_bill(_item("2.2b", qty=11.0)))
        assert _settle(client).status_code == 409


class TestItFollowsTheClientsDocumentAndNotAGuess:

    def test_a_bill_with_no_rig_moves_by_class_still_settles(self, client):
        """There is genuinely nothing to classify, so refusing would be inventing a gate. This is
        the line the whole rule turns on."""
        _save_bill(_bill(_item("1.1", lump=True, unit="item"), _item("2.4", qty=1200.0, unit="m")))
        response = _settle(client)
        assert response.status_code == 200, response.text
        assert response.json()["settled"] is True

    def test_a_rig_move_item_with_no_quantity_and_no_lump_does_not_trigger_it(self, client):
        """An item printed with neither a quantity nor a dash prices nothing, so it establishes no
        holes. Reading it as "holes exist" would refuse on a row the client left blank."""
        _save_bill(_bill(_item("2.2a")))
        assert _settle(client).status_code == 200

    def test_the_refs_it_reads_are_named_in_one_place(self):
        """A second copy of the rig-move item numbers is how two of them come to disagree."""
        from client_boq.router import RIG_MOVE_REFS

        assert RIG_MOVE_REFS == ("2.2a", "2.2b")


class TestTheOriginalRefusalIsUnchanged:

    def test_a_read_schedule_with_unclassed_holes_still_refuses_by_name(self, client):
        client.post(f"{BASE}/site/schedule", json={
            "set_id": SET,
            "schedule": {"set_id": SET, "stations": [
                {"station": "CE19-ABH01", "soil_m": 30.0, "rock_m": 5.0, "length_m": 35.0},
                {"station": "CE19-ABH02", "soil_m": 30.0, "rock_m": 5.0, "length_m": 35.0},
            ]}})
        _save_bill(_bill(_item("2.2a", qty=80.0)))
        response = _settle(client)
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "2 hole(s) still have no class of site" in detail
        assert "CE19-ABH01" in detail
        assert "2.2a or 2.2b" in detail

    def test_a_fully_classified_schedule_settles(self, client):
        client.post(f"{BASE}/site/schedule", json={
            "set_id": SET,
            "schedule": {"set_id": SET, "stations": [
                {"station": "CE19-ABH01", "soil_m": 30.0, "rock_m": 5.0, "length_m": 35.0},
            ]}})
        client.post(f"{BASE}/site/class",
                    json={"set_id": SET, "station": "CE19-ABH01", "access_class": "A"})
        _save_bill(_bill(_item("2.2a", qty=80.0)))
        response = _settle(client)
        assert response.status_code == 200, response.text

    def test_a_read_schedule_takes_precedence_over_the_bill_check(self, client):
        """Once holes are known, they are what the refusal names — station by station. The bill
        check is the fallback for the state where nothing is known, not a second gate."""
        client.post(f"{BASE}/site/schedule", json={
            "set_id": SET,
            "schedule": {"set_id": SET, "stations": [
                {"station": "CE19-ABH01", "soil_m": 30.0, "rock_m": 5.0, "length_m": 35.0},
            ]}})
        client.post(f"{BASE}/site/class",
                    json={"set_id": SET, "station": "CE19-ABH01", "access_class": "B"})
        _save_bill(_bill(_item("2.2a", qty=80.0)))
        assert _settle(client).status_code == 200
