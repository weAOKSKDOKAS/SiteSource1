"""Section-level routing split (Prompt 2): a many-section package splits into per-section
sub-packages, each routable independently and (self-perform) seeding its own estimate; a
single-section (demo) package stays whole and never splits."""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed
from pipeline.routing.split import route_units
from pipeline.stage_04_level.export_xlsx import sheet_title
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


def test_corrupted_section_refs_yield_one_unit_not_h_plus_hs_plus_empty():
    # The live fragmentation: H1(a) lost its letter -> "1(a)", H5 read as "HS". After the section
    # repair (Commit 1) the package is one section H, so route_units yields ONE :H unit carrying
    # every H item — no :HS, no empty-section unit, nothing dropped.
    from pipeline.stage_01_ingest.ingest import annotate_sections

    raw = ScopePackages(packages=[TradeWorkPackage(
        trade="field_installations", scope_summary="Field Installations",
        sor_items=[SorItem(item_ref=r) for r in ["1(a)", "H4", "HS", "H6", "H17"]])])
    scope = annotate_sections(raw, "SECTION H : FIELD INSTALLATIONS")
    units = route_units(scope, split_keys={"field_installations"})  # force the per-section split
    assert [u["package_key"] for u in units] == ["field_installations:H"]  # not :H + :HS + bare
    assert all(u["section"] for u in units)  # no empty-section unit
    assert [i.item_ref for i in units[0]["package"].sor_items] == ["1(a)", "H4", "HS", "H6", "H17"]


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


def test_workbook_sheet_title_is_excel_safe_for_a_section_sub_package():
    t = sheet_title("ground_investigation:H")
    assert ":" not in t and len(t) <= 31 and t.endswith(" H")  # ':' stripped, section kept
    assert sheet_title("electrical") == "Electrical"  # a bare trade is unchanged


def _bid(firm_id, trade, total):
    return {"firm_id": firm_id, "firm_name": firm_id, "trade": trade, "normalized_total": total,
            "corrected_total": total, "arithmetic_findings": [], "exclusions": [], "scope_gaps": []}


def test_sublet_sub_packages_source_and_recommend_distinctly_by_package_key(demo_db):
    # two GI sections sublet as distinct sourcing units (package_key), each drawn from the
    # parent trade's real firms — never merged into one ground_investigation package.
    scope = {"project_name": "GE/2026/14", "packages": [
        {"trade": "ground_investigation:H", "scope_summary": "field installations",
         "sor_items": [{"item_ref": "H1", "description": "x", "unit": "no", "qty": 1.0, "section": "H"}], "source_refs": []},
        {"trade": "ground_investigation:J", "scope_summary": "survey",
         "sor_items": [{"item_ref": "J1", "description": "y", "unit": "no", "qty": 1.0, "section": "J"}], "source_refs": []},
    ]}
    sl = client.post("/shortlist", json={"scope": scope, "include_public": True, "k": 5}).json()
    assert set(sl["per_trade"]) == {"ground_investigation:H", "ground_investigation:J"}  # distinct, not merged

    # recommend groups by package_key too — one section, one award apiece
    recs = client.post("/recommend-all", json={"levelled": [
        _bid("X1", "ground_investigation:H", 100.0), _bid("Y1", "ground_investigation:J", 200.0),
    ]}).json()["sections"]
    by_key = {s["trade"]: s["recommendation"] for s in recs}
    assert set(by_key) == {"ground_investigation:H", "ground_investigation:J"}
    assert by_key["ground_investigation:H"]["recommended_firm_id"] == "X1"
    assert by_key["ground_investigation:J"]["recommended_firm_id"] == "Y1"
