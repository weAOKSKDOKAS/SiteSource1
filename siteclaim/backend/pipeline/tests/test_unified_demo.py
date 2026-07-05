"""Unified-engine demo scenario (Phase P5b) — the whole loop, seeded offline (demo only)."""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed

client = TestClient(app)
_RUN = "demo-gi-fitout-tender"


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    db = tmp_path / "demo.db"
    seed.build_database(db, profile="demo")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


def test_unified_demo_run_spans_both_tracks(demo_db):
    run = next(p for p in client.get("/project").json() if p["run_ref"] == _RUN)
    assert run["provenance"] == "demo" and run["package_count"] == 2
    assert run["self_perform_count"] == 1 and run["sublet_count"] == 1 and run["benchmark_project_id"] is not None
    dash = client.get(f"/project/{_RUN}").json()
    by_key = {p["package_key"]: p for p in dash["packages"]}
    assert by_key["ground_investigation"]["track"] == "left" and by_key["electrical"]["track"] == "right"
    # the GI recommendation was sublet but the human chose self-perform — the decision is the record of truth
    assert by_key["ground_investigation"]["recommended_route"] == "sublet"
    assert by_key["ground_investigation"]["chosen_route"] == "self_perform"
    assert len(dash["estimates"]) == 1 and dash["estimates"][0]["trade"] == "ground_investigation"
    assert dash["estimates"][0]["total"] and dash["estimates"][0]["total"] > 0   # priced


def test_demo_estimate_rate_precedent_lights_up(demo_db):
    eid = client.get(f"/project/{_RUN}").json()["estimates"][0]["id"]
    body = client.get(f"/estimate/{eid}/rate-suggestions").json()
    assert body["corpus_empty"] is False
    g1 = next(s for s in body["suggestions"] if s["item_ref"] == "G1")
    assert g1["tier"] == 1 and g1["rate_median"] == 1200.0   # the corpus rate, not the estimate's price
    assert any(w["reason_code"] == "standing_time" for w in g1["rate_warnings"])


def test_demo_run_links_to_the_benchmark_with_its_eos(demo_db):
    bpid = client.get(f"/project/{_RUN}").json()["benchmark_project_id"]
    eos = client.get(f"/benchmark/{bpid}/eos").json()
    assert eos and "not priced in the tender" in eos["narrative"]   # the EOS explains the variance


def test_live_profile_has_no_unified_demo(tmp_path, monkeypatch):
    db = tmp_path / "live.db"
    seed.build_database(db, profile="live")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    assert client.get("/project").json() == []
