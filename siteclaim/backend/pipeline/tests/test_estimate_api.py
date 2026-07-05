"""Estimator project + item CRUD (Phase P3a), through the API, offline (DEMO).

Every write targets a temp LIVE profile DB via SITESOURCE_DB, so the committed DB is
never touched.
"""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed

client = TestClient(app)


@pytest.fixture
def est_db(tmp_path, monkeypatch):
    db = tmp_path / "est.db"
    seed.build_database(db, profile="live")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


_PACKAGE = {
    "trade": "ground_investigation",
    "scope_summary": "GI drilling and in-situ testing",
    "sor_items": [
        {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m", "qty": 100.0},
        {"item_ref": "G2", "description": "SPT", "unit": "no", "qty": 40.0},
    ],
    "source_refs": ["SR-01"],
}


def test_estimate_routes_are_registered():
    paths = {r.path for r in app.routes}
    assert {"/estimate/projects", "/estimate/from-package",
            "/estimate/{estimate_id}/items", "/estimate/{estimate_id}/items/{item_id}"} <= paths


def test_manual_project_crud(est_db):
    created = client.post("/estimate/projects", json={"name": "Fit-out estimate", "trade": "joinery_fitting_out"}).json()
    assert created["status"] == "draft" and created["provenance"] == "live" and created["item_count"] == 0
    eid = created["id"]
    assert any(p["id"] == eid for p in client.get("/estimate/projects").json())
    got = client.get(f"/estimate/projects/{eid}").json()
    assert got["trade"] == "joinery_fitting_out"
    patched = client.patch(f"/estimate/projects/{eid}", json={"scope_of_works": "Loose furniture and joinery", "status": "submitted"}).json()
    assert patched["scope_of_works"].startswith("Loose furniture") and patched["status"] == "submitted"
    assert client.get("/estimate/projects/999999").status_code == 404


def test_patch_rejects_unknown_status(est_db):
    eid = client.post("/estimate/projects", json={"name": "P"}).json()["id"]
    assert client.patch(f"/estimate/projects/{eid}", json={"status": "banana"}).status_code == 400


def test_from_package_seeds_unpriced_items_and_is_idempotent(est_db):
    body = client.post("/estimate/from-package", json={
        "package": _PACKAGE, "project_name": "GE/2026/14", "run_ref": "ge-2026-14",
    }).json()
    assert body["trade"] == "ground_investigation" and body["source"] == "routing"
    assert body["scope_of_works"].startswith("GI drilling") and body["item_count"] == 2
    assert body["priced_item_count"] == 0 and body["total"] is None  # unpriced — the human prices
    items = client.get(f"/estimate/{body['id']}/items").json()
    assert {i["item_ref"] for i in items} == {"G1", "G2"} and all(i["rate"] is None for i in items)
    # idempotent per (run_ref, package_key): the same routed package opens the same estimate
    again = client.post("/estimate/from-package", json={"package": _PACKAGE, "run_ref": "ge-2026-14"}).json()
    assert again["id"] == body["id"]


def test_item_add_price_and_delete(est_db):
    eid = client.post("/estimate/projects", json={"name": "P", "trade": "ground_investigation"}).json()["id"]
    added = client.post(f"/estimate/{eid}/items", json={"items": [
        {"item_ref": "G1", "description": "Drilling", "unit": "m", "qty": 100.0},
    ]}).json()
    item_id = added[0]["id"]
    assert added[0]["rate"] is None and added[0]["amount"] is None
    # the human prices the line -> amount recomputed
    priced = client.patch(f"/estimate/{eid}/items/{item_id}", json={"rate": 1200.0}).json()
    assert priced["rate"] == 1200.0 and priced["amount"] == 120000.0
    assert client.get(f"/estimate/projects/{eid}").json()["total"] == 120000.0
    # delete
    assert client.delete(f"/estimate/{eid}/items/{item_id}").status_code == 200
    assert client.get(f"/estimate/{eid}/items").json() == []
    assert client.patch(f"/estimate/{eid}/items/999999", json={"rate": 1.0}).status_code == 404


def test_draft_seeds_scope_and_adds_skeleton_items(est_db):
    seeded = client.post("/estimate/from-package", json={"package": _PACKAGE, "run_ref": "r1"}).json()
    eid = seeded["id"]
    result = client.post(f"/estimate/{eid}/draft").json()
    assert result["scope_of_works"] and result["trade_mapped"] is True
    # the demo fixture proposes GI skeleton items not already in the tender SoR
    assert set(result["added_item_refs"]) >= {"G-MOB", "G-STANDBY"}
    items = {i["item_ref"] for i in client.get(f"/estimate/{eid}/items").json()}
    assert {"G1", "G2", "G-MOB", "G-STANDBY"} <= items  # tender lines kept + skeleton added
    # the added skeleton lines are unpriced/unquantified (the human fills them)
    added = [i for i in client.get(f"/estimate/{eid}/items").json() if i["item_ref"] == "G-MOB"][0]
    assert added["qty"] is None and added["rate"] is None
    # re-drafting dedupes against the now-present refs (no duplicate G-MOB)
    again = client.post(f"/estimate/{eid}/draft").json()
    assert "G-MOB" not in again["added_item_refs"]
    assert client.post("/estimate/123456/draft").status_code == 404


def test_rate_suggestions_light_up_on_the_demo_corpus(tmp_path, monkeypatch):
    db = tmp_path / "demo.db"
    seed.build_database(db, profile="demo")   # carries the demo benchmark project (the corpus)
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    eid = client.post("/estimate/projects", json={"name": "GI est", "trade": "ground_investigation"}).json()["id"]
    client.post(f"/estimate/{eid}/items", json={"items": [
        {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m", "qty": 100.0},
    ]})
    body = client.get(f"/estimate/{eid}/rate-suggestions").json()
    assert body["corpus_empty"] is False and body["corpus_size"] >= 4
    g1 = body["suggestions"][0]
    assert g1["tier"] == 1 and g1["rate_median"] == 1200.0
    assert any(w["reason_code"] == "standing_time" for w in g1["rate_warnings"])


def test_rate_suggestions_empty_on_the_live_profile(est_db):
    eid = client.post("/estimate/projects", json={"name": "P", "trade": "ground_investigation"}).json()["id"]
    client.post(f"/estimate/{eid}/items", json={"items": [{"item_ref": "G1", "description": "Drilling", "unit": "m"}]})
    body = client.get(f"/estimate/{eid}/rate-suggestions").json()
    assert body["corpus_empty"] is True and body["suggestions"][0]["tier"] == 0


def test_check_flags_omissions_unpriced_and_scope_gaps(est_db):
    eid = client.post("/estimate/from-package", json={"package": _PACKAGE, "run_ref": "c1"}).json()["id"]
    result = client.post(f"/estimate/{eid}/check", json={"tender": [
        {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m"},
        {"item_ref": "G2", "description": "SPT", "unit": "no"},
        {"item_ref": "G9", "description": "Grouting", "unit": "no"},   # not in the estimate
    ]}).json()
    assert result["tender_checked"] is True and result["rubric_size"] == 0
    kinds = {f["kind"] for f in result["findings"]}
    assert "omission" in kinds and any(f["item_ref"] == "G9" for f in result["findings"])
    assert "unpriced" in kinds                       # the seeded lines are unpriced
    assert "scope_gap" in kinds                       # the DEMO fixture flags a reinstatement gap
    assert client.post("/estimate/123456/check", json={"tender": []}).status_code == 404


def test_endpoints_404_on_unknown_estimate(est_db):
    assert client.get("/estimate/projects/123456").status_code == 404
    assert client.post("/estimate/123456/items", json={"items": []}).status_code == 404
    assert client.get("/estimate/123456/items").status_code == 404
    assert client.get("/estimate/123456/rate-suggestions").status_code == 404
