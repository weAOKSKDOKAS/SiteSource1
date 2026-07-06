"""Section metadata at ingest (Prompt 2): each SoR item carries its section, each package
rolls up its sections (code, header title, item_count) — the routable unit made visible.
The demo scenarios stay single-section (they never auto-split)."""

from pathlib import Path

from fastapi.testclient import TestClient

from api import app
from pipeline.stage_01_ingest.ingest import annotate_sections, section_of
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

client = TestClient(app)
_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def test_section_of_reads_leading_letters_including_two_letter_codes():
    assert section_of("A1a(a)") == "A"
    assert section_of("E10(l)") == "E"
    assert section_of("BB7a") == "BB"
    assert section_of("M-01") == "M"
    assert section_of("") == "" and section_of("42") == ""


_DOC = """
SECTION A : PRELIMINARIES ITEMS
A1  Something
SECTION E : DRILLING
E10  Rotary drilling
SECTION BB : LABORATORY TESTING
BB7a  Triaxial test
SECTION K : (Not used)
"""


def test_annotate_sets_item_section_and_package_sections_with_titles():
    scope = ScopePackages(project_name="GE/2026/14", packages=[
        TradeWorkPackage(trade="ground_investigation", scope_summary="GI", sor_items=[
            SorItem(item_ref="A1a(a)", description="Prelim"),
            SorItem(item_ref="E10(l)", description="Drilling"),
            SorItem(item_ref="E11", description="More drilling"),
            SorItem(item_ref="BB7a", description="Lab"),
        ]),
    ])
    out = annotate_sections(scope, _DOC)
    pkg = out.packages[0]
    assert [i.section for i in pkg.sor_items] == ["A", "E", "E", "BB"]
    by_code = {s.code: s for s in pkg.sections}
    assert set(by_code) == {"A", "E", "BB"}  # order preserved, K (no items) absent
    assert by_code["A"].title == "PRELIMINARIES ITEMS" and by_code["A"].item_count == 1
    assert by_code["E"].title == "DRILLING" and by_code["E"].item_count == 2
    assert by_code["BB"].title == "LABORATORY TESTING" and by_code["BB"].item_count == 1


def test_missing_header_leaves_the_title_empty_but_still_counts():
    scope = ScopePackages(packages=[TradeWorkPackage(trade="electrical", scope_summary="LV", sor_items=[
        SorItem(item_ref="E-01"), SorItem(item_ref="E-02"),
    ])])
    pkg = annotate_sections(scope, "").packages[0]  # no doc text -> no titles
    assert len(pkg.sections) == 1 and pkg.sections[0].code == "E"
    assert pkg.sections[0].title == "" and pkg.sections[0].item_count == 2


def test_real_sr_header_fixture_captures_two_letter_and_bracketed_titles():
    # a sanitized slice of the real GE/2026/14 Schedule of Rates header structure
    text = (_FIXTURES / "cases/routing/sr_headers_sample.txt").read_text(encoding="utf-8")
    scope = ScopePackages(packages=[TradeWorkPackage(trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref=r) for r in ["A1a(a)", "E10(l)", "I1", "R1", "BB7a"]])])
    pkg = annotate_sections(scope, text).packages[0]
    by = {s.code: s for s in pkg.sections}
    assert set(by) == {"A", "E", "I", "R", "BB"}  # K (Not used, no items) absent
    assert by["A"].title == "PRELIMINARIES ITEMS"
    assert by["E"].title == "DRILLING"
    assert by["BB"].title == "LABORATORY TESTING"  # two-letter section header captured
    assert [i.section for i in pkg.sor_items] == ["A", "E", "I", "R", "BB"]


def test_demo_ingest_packages_are_single_section():
    case = client.get("/demo/golden").json()
    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    assert scope["packages"]
    for pkg in scope["packages"]:
        # every demo package is one section — so it never crosses the auto-split threshold
        assert len(pkg["sections"]) == 1
        assert all(it["section"] for it in pkg["sor_items"])
