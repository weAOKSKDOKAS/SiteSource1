"""Unified project dashboard (Phase P4a) — analyze records the run; the dashboard assembles
the tracks and links the left-track estimates. Offline (DEMO)."""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed

client = TestClient(app)


@pytest.fixture
def route_db(tmp_path, monkeypatch):
    db = tmp_path / "route.db"
    seed.build_database(db, profile="demo")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


_SCOPE = {
    "project_name": "Kwun Tong Commercial Tower",
    "packages": [
        {"trade": "electrical", "scope_summary": "LV distribution", "sor_items": [], "source_refs": []},
        {"trade": "ground_investigation", "scope_summary": "GI drilling", "sor_items": [], "source_refs": []},
    ],
}
_RUN = "kwun-tong-commercial-tower"


def test_project_routes_registered():
    paths = {r.path for r in app.routes}
    assert {"/project", "/project/{run_ref}"} <= paths


def test_analyze_records_a_unified_project(route_db):
    client.post("/route/analyze", json={"scope": _SCOPE})
    projects = client.get("/project").json()
    p = next(p for p in projects if p["run_ref"] == _RUN)
    assert p["name"] == "Kwun Tong Commercial Tower" and p["package_count"] == 2
    assert p["provenance"] == "demo"   # analysed under DEMO


def test_dashboard_shows_tracks_and_links_estimates(route_db):
    client.post("/route/analyze", json={"scope": _SCOPE})
    client.post("/route/confirm", json={"run_ref": _RUN, "decisions": [
        {"package_key": "electrical", "chosen_route": "sublet"},
        {"package_key": "ground_investigation", "chosen_route": "self_perform"},
    ]})
    # a left-track estimate seeded for the run (P4b automates this at confirm)
    client.post("/estimate/from-package", json={
        "package": {"trade": "ground_investigation", "scope_summary": "GI drilling",
                    "sor_items": [{"item_ref": "G1", "unit": "m", "qty": 100.0}], "source_refs": []},
        "run_ref": _RUN,
    })
    dash = client.get(f"/project/{_RUN}").json()
    by_key = {p["package_key"]: p for p in dash["packages"]}
    assert by_key["electrical"]["track"] == "right" and by_key["electrical"]["chosen_route"] == "sublet"
    assert by_key["ground_investigation"]["track"] == "left" and by_key["ground_investigation"]["estimate_id"] is not None
    assert len(dash["estimates"]) == 1 and dash["estimates"][0]["trade"] == "ground_investigation"


def test_dashboard_of_unanalysed_run_is_empty_not_404(route_db):
    dash = client.get("/project/never-analysed").json()
    assert dash["run_ref"] == "never-analysed" and dash["packages"] == [] and dash["estimates"] == []
