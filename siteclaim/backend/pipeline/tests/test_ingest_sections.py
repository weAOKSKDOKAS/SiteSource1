"""Section metadata at ingest (Prompt 2): each SoR item carries its section, each package
rolls up its sections (code, header title, item_count) — the routable unit made visible.
The demo scenarios stay single-section (they never auto-split)."""

from pathlib import Path

from fastapi.testclient import TestClient

from api import app
from pipeline.stage_01_ingest.ingest import annotate_sections, section_of
from rules_engine.taxonomy import section_specialty
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


# -- per-section specialty (roadmap #5): title -> specialty pool, deterministically ----------
def test_section_specialty_reads_the_header_title():
    assert section_specialty("SECTION J : GEOPHYSICAL SURVEY (BOREHOLE TELEVIEWER)") == "geophysical_survey"
    assert section_specialty("FIELD INSTALLATIONS — PIEZOMETERS & STANDPIPES") == "field_installations"
    assert section_specialty("FIELD TESTING / IN-SITU TESTS") == "field_testing"
    assert section_specialty("DRILLING") is None  # names no specialty -> caller keeps the parent


_GI_DOC = """
SECTION G : FIELD TESTING
G1  In-situ vane shear
SECTION H : FIELD INSTALLATIONS
H1  Install standpipe piezometer
SECTION J : GEOPHYSICAL SURVEY
J1  Borehole televiewer logging
SECTION K : DRILLING
K1  Rotary drilling
"""


def test_annotate_tags_each_gi_section_with_its_specialty_else_the_parent():
    scope = ScopePackages(project_name="GE/2026/14", packages=[
        TradeWorkPackage(trade="ground_investigation", scope_summary="GI", sor_items=[
            SorItem(item_ref="G1"), SorItem(item_ref="H1"), SorItem(item_ref="J1"), SorItem(item_ref="K1"),
        ]),
    ])
    by = {s.code: s for s in annotate_sections(scope, _GI_DOC).packages[0].sections}
    assert by["G"].section_trade == "field_testing"
    assert by["H"].section_trade == "field_installations"
    assert by["J"].section_trade == "geophysical_survey"
    assert by["K"].section_trade == "ground_investigation"  # unmatched title -> the parent trade


def test_non_gi_package_sections_keep_the_parent_trade():
    scope = ScopePackages(packages=[TradeWorkPackage(trade="electrical", scope_summary="LV", sor_items=[
        SorItem(item_ref="E-01"), SorItem(item_ref="E-02"),
    ])])
    pkg = annotate_sections(scope, "").packages[0]
    assert pkg.sections[0].section_trade == "electrical"  # no title, no GI keyword -> parent trade


# -- section-code repair (kill phantom sections): snap OCR corruptions onto valid codes ------
def test_corrupted_h5_snaps_to_section_h_not_a_phantom_hs():
    # The live bug: H5 read as "HS" (digit 5 -> letter S) and H1(a)/(b) lost their leading H.
    scope = ScopePackages(packages=[TradeWorkPackage(trade="field_installations", scope_summary="FI",
        sor_items=[SorItem(item_ref=r) for r in ["1(a)", "1(b)", "H4", "HS", "H6", "H17"]])])
    pkg = annotate_sections(scope, "SECTION H : FIELD INSTALLATIONS").packages[0]
    assert [i.section for i in pkg.sor_items] == ["H", "H", "H", "H", "H", "H"]  # one section
    assert [s.code for s in pkg.sections] == ["H"] and pkg.sections[0].item_count == 6
    assert pkg.sections[0].section_trade == "field_installations"  # specialty routing preserved


def test_dropped_leading_letter_inherits_the_running_section():
    # A ref that lost its letter mid-section fills forward from the previous valid item.
    scope = ScopePackages(packages=[TradeWorkPackage(trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref=r) for r in ["G1", "2", "G3", "H1", "2(a)", "H3"]])])
    pkg = annotate_sections(scope, "").packages[0]
    assert [i.section for i in pkg.sor_items] == ["G", "G", "G", "H", "H", "H"]  # G2 and H2 inherited


def test_genuine_two_letter_section_is_kept():
    scope = ScopePackages(packages=[TradeWorkPackage(trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref="BA1"), SorItem(item_ref="BB7a"), SorItem(item_ref="BAX2")])])
    pkg = annotate_sections(scope, "").packages[0]
    # BA and BB are valid two-letter sections; BAX snaps to its longest valid prefix BA.
    assert [i.section for i in pkg.sor_items] == ["BA", "BB", "BA"]


def test_a_real_two_letter_header_legitimises_that_code():
    # A genuine SECTION HS header makes HS a valid section — it is NOT snapped to H.
    scope = ScopePackages(packages=[TradeWorkPackage(trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref="HS1"), SorItem(item_ref="HS2")])])
    pkg = annotate_sections(scope, "SECTION HS : SPECIAL BOREHOLES").packages[0]
    assert [i.section for i in pkg.sor_items] == ["HS", "HS"]
    assert [s.code for s in pkg.sections] == ["HS"]


def test_a_single_section_g_stays_one_section():
    scope = ScopePackages(packages=[TradeWorkPackage(trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref=f"G{n}") for n in range(1, 11)])])
    pkg = annotate_sections(scope, "").packages[0]
    assert {i.section for i in pkg.sor_items} == {"G"} and [s.code for s in pkg.sections] == ["G"]


def test_demo_ingest_packages_are_single_section():
    case = client.get("/demo/golden").json()
    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    assert scope["packages"]
    for pkg in scope["packages"]:
        # every demo package is one section — so it never crosses the auto-split threshold
        assert len(pkg["sections"]) == 1
        assert all(it["section"] for it in pkg["sor_items"])
