"""Bills of Quantities alongside Schedules of Rates.

The extractor was built for a Hong Kong Schedule of Rates, where an item reference carries a
LETTER section code (``A1a(a)``, ``E10(l)``, ``BB7a``). CEDD contract ND/2025/04 is a Bill of
Quantities: its references are ``<bill>.<item>`` — ``1.17``, ``2.24``, ``3.1`` — with no letters
anywhere, and its headers read ``Bill No. 1 - General and Preliminaries`` rather than
``SECTION A : PRELIMINARIES``. 136 items extracted correctly and every one was quarantined.

The bill is the section: ND/2025/04 has nine, ``1`` through ``9``. Not bill-plus-subsection —
you do not sublet item 2.4 and self-perform item 2.5 of the same drilling operation.
``route_units()`` already splits a large package further by section when the thresholds are met,
so finer grain stays available without redefining what a section is.

These tests are the BQ family only. The SoR family's own behaviour is asserted, unedited, by
``test_ingest_sections.py`` — the two files together are the "additive, not altered" proof.
"""

from pathlib import Path

from pipeline.stage_01_ingest.ingest import annotate_sections
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
_BQ_DOC = (_FIXTURES / "cases/routing/bq_headers_sample.txt").read_text(encoding="utf-8")


def _bq_package(refs: list[str], trade: str = "ground_investigation") -> ScopePackages:
    return ScopePackages(project_name="ND/2025/04", packages=[
        TradeWorkPackage(trade=trade, scope_summary="GI", sor_items=[SorItem(item_ref=r) for r in refs]),
    ])


# -- the failure of the night: a bill's items must place, not vanish ------------------------
def test_bill_item_refs_place_into_their_bill_number():
    """``1.17`` belongs to bill 1, ``2.24`` to bill 2, ``3.1`` to bill 3 — the leading integer
    before the first separator, never an empty section."""
    pkg = annotate_sections(_bq_package(["1.17", "1.18", "2.1", "2.24", "3.1"]), _BQ_DOC).packages[0]
    assert [i.section for i in pkg.sor_items] == ["1", "1", "2", "2", "3"]


def test_section_titles_come_off_the_bill_headers():
    """Three punctuation shapes, all real: ``Bill No. 1 - Title``, ``BILL NO. 2 : TITLE``,
    ``Bill No.3 Title`` (no separator at all)."""
    pkg = annotate_sections(_bq_package(["1.17", "2.4", "3.1"]), _BQ_DOC).packages[0]
    by_code = {s.code: s for s in pkg.sections}
    assert set(by_code) == {"1", "2", "3"}
    assert by_code["1"].title == "General and Preliminaries"
    assert by_code["2"].title == "GROUND INVESTIGATION FIELDWORKS"
    assert by_code["3"].title == "Laboratory Testing"


def test_package_sections_roll_up_in_document_order_with_counts():
    pkg = annotate_sections(_bq_package(["1.1", "1.2", "1.17", "2.1", "2.4", "3.1"]), _BQ_DOC).packages[0]
    assert [(s.code, s.item_count) for s in pkg.sections] == [("1", 3), ("2", 2), ("3", 1)]


def test_a_bill_number_is_never_snapped_to_a_prefix():
    """A bill number has no prefix structure. Snapping ``24`` to its longest valid prefix would
    move bill 24's items into bill 2 — silently, and then fill-forward would spread the error.
    Prefix-snapping is a Schedule-of-Rates repair; it does not apply here."""
    pkg = annotate_sections(_bq_package(["24.1", "24.2", "2.1"]), "").packages[0]
    assert [i.section for i in pkg.sor_items] == ["24", "24", "2"]


def test_an_unreadable_ref_inherits_the_running_bill():
    """Fill-forward is family-independent: a ref the extractor could not read keeps the bill it
    sits inside rather than opening a phantom section."""
    pkg = annotate_sections(_bq_package(["1.1", "", "1.3", "2.1", "?", "2.3"]), "").packages[0]
    assert [i.section for i in pkg.sor_items] == ["1", "1", "1", "2", "2", "2"]


def test_a_year_shaped_leading_token_is_not_a_bill():
    """A bill number is a small positive integer. ``2025.1`` is a date that reached the ref
    column, not bill two-thousand-and-twenty-five; it must not open a section of its own."""
    pkg = annotate_sections(_bq_package(["1.1", "2025.1", "1.3"]), "").packages[0]
    assert [i.section for i in pkg.sor_items] == ["1", "1", "1"]


# -- the family boundary: the SoR path must be reachable and unchanged ----------------------
def test_a_schedule_of_rates_package_is_still_read_as_letters():
    """The same entry point, the other family — leading letters, two-letter sections, and the
    OCR prefix-snap all still apply. This is the guard rail: if teaching the extractor bills
    changed this, it changed the live path."""
    pkg = annotate_sections(
        ScopePackages(packages=[TradeWorkPackage(trade="ground_investigation", scope_summary="GI",
            sor_items=[SorItem(item_ref=r) for r in ["A1a(a)", "E10(l)", "BB7a", "HS"]])]),
        "SECTION A : PRELIMINARIES\nSECTION E : DRILLING\nSECTION BB : LABORATORY TESTING\n",
    ).packages[0]
    assert [i.section for i in pkg.sor_items] == ["A", "E", "BB", "H"]


def test_a_damaged_sor_ref_is_not_mistaken_for_a_bill():
    """``1(a)`` and ``2`` are Schedule-of-Rates refs that LOST their leading letter — the exact
    case ``_normalise_sections`` fill-forward exists for. They are bare integers, not
    ``<bill>.<item>``, so they must not tip a package into the bill family."""
    pkg = annotate_sections(
        ScopePackages(packages=[TradeWorkPackage(trade="field_installations", scope_summary="FI",
            sor_items=[SorItem(item_ref=r) for r in ["1(a)", "1(b)", "H4", "HS", "H6", "H17"]])]),
        "SECTION H : FIELD INSTALLATIONS",
    ).packages[0]
    assert [i.section for i in pkg.sor_items] == ["H"] * 6
