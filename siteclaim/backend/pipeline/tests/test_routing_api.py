"""Routing gate endpoints (Phase P1d) — analyze + the confirm gate, offline (DEMO)."""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed

client = TestClient(app)


@pytest.fixture
def route_db(tmp_path, monkeypatch):
    # A demo-profile DB so the coverage signal sees the firm pool; writes go here, not the
    # committed DB.
    db = tmp_path / "route.db"
    seed.build_database(db, profile="demo")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


_SCOPE = {
    "project_name": "Kwun Tong Commercial Tower",
    "packages": [
        {"trade": "electrical", "scope_summary": "LV distribution and final circuits", "sor_items": [], "source_refs": []},
        {"trade": "demolition", "scope_summary": "Soft strip and structural demolition", "sor_items": [], "source_refs": []},
    ],
}


def test_route_routes_registered():
    paths = {r.path for r in app.routes}
    assert {"/route/analyze", "/route/confirm"} <= paths


def test_analyze_recommends_and_persists_with_no_decision(route_db):
    proposal = client.post("/route/analyze", json={"scope": _SCOPE}).json()
    assert proposal["run_ref"] == "kwun-tong-commercial-tower"
    by_key = {p["package_key"]: p for p in proposal["packages"]}
    # electrical is covered by the baked DEMO fixture -> sublet, source route-suggest
    assert by_key["electrical"]["recommended_route"] == "sublet"
    assert by_key["electrical"]["source"] == "route-suggest"
    assert by_key["electrical"]["signals"]["trade_firm_count"] >= 1  # the L1 signal is attached
    # demolition is not in the fixture -> deterministic fallback
    assert by_key["demolition"]["source"] == "fallback"
    # nothing decided yet
    assert all(p["chosen_route"] is None for p in proposal["packages"])


def test_confirm_is_the_sole_writer_of_chosen_route(route_db):
    client.post("/route/analyze", json={"scope": _SCOPE})
    result = client.post("/route/confirm", json={
        "run_ref": "kwun-tong-commercial-tower",
        "decisions": [
            {"package_key": "electrical", "chosen_route": "sublet"},
            {"package_key": "demolition", "chosen_route": "self_perform"},
        ],
        "decided_by": "ops",
    }).json()
    assert result["sublet_packages"] == ["electrical"]
    assert result["self_perform_packages"] == ["demolition"]
    elec = next(p for p in result["packages"] if p["package_key"] == "electrical")
    assert elec["chosen_route"] == "sublet" and elec["decided_by"] == "ops" and elec["decided_at"]


def test_confirm_rejects_an_unknown_route(route_db):
    client.post("/route/analyze", json={"scope": _SCOPE})
    resp = client.post("/route/confirm", json={
        "run_ref": "kwun-tong-commercial-tower",
        "decisions": [{"package_key": "electrical", "chosen_route": "banana"}],
    })
    assert resp.status_code == 400 and "unknown route" in resp.json()["detail"]


def test_reanalyze_replaces_the_proposal(route_db):
    client.post("/route/analyze", json={"scope": _SCOPE})
    smaller = {"project_name": "Kwun Tong Commercial Tower",
               "packages": [{"trade": "electrical", "scope_summary": "x", "sor_items": [], "source_refs": []}]}
    proposal = client.post("/route/analyze", json={"scope": smaller}).json()
    assert [p["package_key"] for p in proposal["packages"]] == ["electrical"]  # replaced, demolition gone
