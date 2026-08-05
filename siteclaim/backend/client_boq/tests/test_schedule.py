"""The pricing schedule — the INPUT a live estimate is run from — and the letterhead.

Why these exist: `/estimate/run` has always required `margin_pct` and a structured `schedule` in
LIVE, and DEMO supplied both from a fixture. So the workflow ran offline and could not run for
real — there was nowhere to put a bill of quantities. These tests pin the door that was added.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.models import EstimateSchedule

BASE = "/client-boq"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _schedule() -> dict:
    """A small but complete schedule: one direct activity with a book-rate line and an inline-rate
    line, and one indirect on each of the three bases."""
    return {
        "duration_weeks": 12,
        "items": [
            {
                "item_id": "A1",
                "description": "Curtain walling",
                "category": "direct",
                "unit": "m2",
                "lines": [
                    {"description": "Glazing labour", "resource_ref": "LAB-GEN",
                     "qty": 400, "unit": "hr"},
                    {"description": "Panels", "inline_rate": 950.0, "qty": 120, "unit": "m2"},
                ],
            },
            {"item_id": "I1", "description": "Site management", "category": "indirect",
             "basis": "per_week", "rate": 8000.0},
            {"item_id": "I2", "description": "Insurances", "category": "indirect",
             "basis": "pct_of_direct", "pct": 2.5},
            {"item_id": "I3", "description": "Mobilisation", "category": "indirect",
             "basis": "lump", "amount": 60000.0},
        ],
    }


# --- persistence -----------------------------------------------------------
def test_absent_schedule_is_a_state_not_an_error(client: TestClient) -> None:
    """A tender that has never been priced answers 200 with ``saved: false``. The editor opens on
    an empty schedule; a 404 would make "not started yet" look like a fault."""
    body = client.get(f"{BASE}/estimate/schedule/nothing-here").json()
    assert body["saved"] is False
    assert body["schedule"]["items"] == []
    assert body["margin_pct"] == 0.0


def test_schedule_round_trips(client: TestClient) -> None:
    payload = {"set_id": "sched-set", "schedule": _schedule(), "margin_pct": 12.5}
    saved = client.post(f"{BASE}/estimate/schedule", json=payload)
    assert saved.status_code == 200

    body = client.get(f"{BASE}/estimate/schedule/sched-set").json()
    assert body["saved"] is True
    assert body["margin_pct"] == 12.5
    assert body["schedule"]["duration_weeks"] == 12
    assert [i["item_id"] for i in body["schedule"]["items"]] == ["A1", "I1", "I2", "I3"]
    # The parts the estimate actually reads survive the trip, not just the ids.
    a1 = body["schedule"]["items"][0]
    assert a1["lines"][0]["resource_ref"] == "LAB-GEN"
    assert a1["lines"][1]["inline_rate"] == 950.0
    assert body["schedule"]["items"][2]["pct"] == 2.5


def test_saving_twice_replaces_rather_than_duplicates(client: TestClient) -> None:
    """One schedule per tender. A re-save is an edit of the same bill, not a second one."""
    first = {"set_id": "sched-twice", "schedule": _schedule(), "margin_pct": 10}
    client.post(f"{BASE}/estimate/schedule", json=first)

    trimmed = _schedule()
    trimmed["items"] = trimmed["items"][:1]
    client.post(f"{BASE}/estimate/schedule",
                json={"set_id": "sched-twice", "schedule": trimmed, "margin_pct": 20})

    body = client.get(f"{BASE}/estimate/schedule/sched-twice").json()
    assert len(body["schedule"]["items"]) == 1
    assert body["margin_pct"] == 20


def test_the_saver_is_recorded(client: TestClient) -> None:
    """A price rests on this bill, so the bill should be able to say whose work it is."""
    client.post(f"{BASE}/estimate/schedule",
                json={"set_id": "sched-who", "schedule": _schedule(), "margin_pct": 5},
                headers={"X-CBOQ-Actor": "r-lam"})
    body = client.get(f"{BASE}/estimate/schedule/sched-who").json()
    assert body["updated_by"] == "r-lam"
    assert body["updated_at"]


def test_a_saved_schedule_still_validates_as_the_run_contract(client: TestClient) -> None:
    """The stored payload must be exactly what ``/estimate/run`` accepts — the whole point is that
    the editor produces a runnable schedule, not a lookalike."""
    client.post(f"{BASE}/estimate/schedule",
                json={"set_id": "sched-valid", "schedule": _schedule(), "margin_pct": 15})
    body = client.get(f"{BASE}/estimate/schedule/sched-valid").json()
    parsed = EstimateSchedule.model_validate(body["schedule"])
    assert parsed.duration_weeks == 12
    assert parsed.items[0].lines[0].resource_ref == "LAB-GEN"


# --- the letterhead --------------------------------------------------------
def test_company_details_start_blank_and_round_trip(client: TestClient) -> None:
    """Blank is the honest starting state: the letter shows a visible placeholder rather than a
    company name nobody chose."""
    assert client.get(f"{BASE}/settings").json()["company"] == {
        "company_name": "", "company_address": "", "contact_name": "", "contact_number": "",
    }

    saved = client.post(f"{BASE}/company", json={
        "company_name": "Wing Tai Construction Ltd",
        "company_address": "12/F, Kwun Tong",
        "contact_name": "R. Lam",
        "contact_number": "+852 1234 5678",
    }, headers={"X-CBOQ-Actor": "r-lam"})
    assert saved.status_code == 200
    assert saved.json()["company"]["company_name"] == "Wing Tai Construction Ltd"

    again = client.get(f"{BASE}/settings").json()["company"]
    assert again["contact_name"] == "R. Lam"
    assert again["company_address"] == "12/F, Kwun Tong"


def test_company_details_do_not_disturb_the_model_setting(client: TestClient) -> None:
    """Two unrelated things share one settings table; saving one must not clear the other."""
    client.post(f"{BASE}/settings", json={"provider": "anthropic", "model_anthropic": "",
                                          "model_deepseek": ""})
    client.post(f"{BASE}/company", json={"company_name": "Acme", "company_address": "",
                                         "contact_name": "", "contact_number": ""})
    body = client.get(f"{BASE}/settings").json()
    assert body["provider"] == "anthropic"
    assert body["company"]["company_name"] == "Acme"


def test_the_client_name_is_not_a_company_setting(client: TestClient) -> None:
    """The client and the project belong to a TENDER, not to the app — they come from the desk
    card, so they are never typed twice. Guarding it because a 'client_name' field here would look
    natural and would immediately drift from the set metadata."""
    body = client.get(f"{BASE}/settings").json()
    assert "client_name" not in body["company"]
    assert "project" not in body["company"]
