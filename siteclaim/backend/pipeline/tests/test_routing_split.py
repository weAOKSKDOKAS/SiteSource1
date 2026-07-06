"""Section-level routing split (Prompt 2): a many-section package splits into per-section
sub-packages, each routable independently and (self-perform) seeding its own estimate; a
single-section (demo) package stays whole and never splits."""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed
from pipeline.routing.split import route_units
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

client = TestClient(app)

_TITLES = [("A", "PRELIMINARIES"), ("E", "DRILLING"), ("H", "FIELD INSTALLATIONS"),
           ("J", "SURVEY"), ("R", "LANDSCAPE")]


def _gi_scope() -> ScopePackages:
    """A GI package spanning 5 sections (> 3) — the GE/2026/14 shape; auto-splits."""
    items = [SorItem(item_ref=f"{c}{n}", description=f"{c} item {n}", unit="no", qty=1.0, section=c)
             for c, _ in _TITLES for n in (1, 2)]
    sections = [SectionMeta(code=c, title=t, item_count=2) for c, t in _TITLES]
    return ScopePackages(project_name="GE/2026/14", packages=[
        TradeWorkPackage(trade="ground_investigation", scope_summary="GI", sor_items=items, sections=sections),
    ])


def test_route_units_splits_a_many_section_package_by_section():
    units = route_units(_gi_scope())
    assert [u["package_key"] for u in units] == [f"ground_investigation:{c}" for c, _ in _TITLES]
    drilling = next(u for u in units if u["section"] == "E")
    assert drilling["trade"] == "ground_investigation" and drilling["section_title"] == "DRILLING"
    assert [i.item_ref for i in drilling["package"].sor_items] == ["E1", "E2"]  # section-scoped items only
    assert drilling["auto_split"] is True


def test_single_section_package_stays_whole():
    scope = ScopePackages(packages=[TradeWorkPackage(
        trade="electrical", scope_summary="LV",
        sor_items=[SorItem(item_ref="E-01", section="E"), SorItem(item_ref="E-02", section="E")],
        sections=[SectionMeta(code="E", title="", item_count=2)],
    )])
    units = route_units(scope)
    assert len(units) == 1 and units[0]["package_key"] == "electrical" and ":" not in units[0]["package_key"]


def test_demo_ingest_never_splits():
    case = client.get("/demo/golden").json()
    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    units = route_units(ScopePackages.model_validate(scope))
    assert units and all(":" not in u["package_key"] for u in units)  # bare-trade keys, unchanged


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    db = tmp_path / "d.db"
    seed.build_database(db, profile="demo")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


def test_analyze_splits_and_confirm_seeds_per_section_estimates(demo_db):
    scope = _gi_scope().model_dump()
    proposal = client.post("/route/analyze", json={"scope": scope, "run_ref": "ge-split"}).json()
    keys = {p["package_key"] for p in proposal["packages"]}
    assert {f"ground_investigation:{c}" for c, _ in _TITLES} == keys
    drilling = next(p for p in proposal["packages"] if p["package_key"] == "ground_investigation:E")
    assert drilling["section"] == "E" and drilling["section_title"] == "DRILLING"

    # self-perform two sections -> two DISTINCT estimates, each with only its section's items
    sp = {"ground_investigation:E", "ground_investigation:H"}
    decisions = [{"package_key": p["package_key"],
                  "chosen_route": "self_perform" if p["package_key"] in sp else "sublet"}
                 for p in proposal["packages"]]
    res = client.post("/route/confirm", json={"run_ref": "ge-split", "decisions": decisions, "scope": scope}).json()
    assert set(res["estimate_ids"]) == sp
    assert res["estimate_ids"]["ground_investigation:E"] != res["estimate_ids"]["ground_investigation:H"]
    items = client.get(f"/estimate/{res['estimate_ids']['ground_investigation:E']}/items").json()
    assert {i["item_ref"] for i in items} == {"E1", "E2"}  # section E only, not the whole trade
