"""The completeness backstop, for the reference family a Bill of Quantities actually uses.

`recover_dropped_sor_items` puts back any row the extraction dropped that the document's own text
still carries. It has always worked for a Schedule of Rates, whose refs are `G7` / `BB12`, because
`_ocr_item_inventory` matches ONE OR TWO LETTERS then digits. A bill numbers its items `1.17`,
`2.24`, `7.2` — no letters — so the inventory came back empty, the function returned on its
`if not inv` line, and `report_sequence_gaps` was left NAMING rows nothing would put back.

The refs pinned below are the ones the split's own notes reported on CEDD ND/2025/04: bill 2
without 2.2, bill 7 without 7.2, and bill 1 opening at 1.12 with 1.1-1.11 and 1.19-1.31 absent.

**These are FIXTURES, not that pack.** The 232 MB tender is not in this repository. What is
modelled here is the shape of its text — bill headers, ruled item rows, indented headings, page
furniture — and the exact references it lost. That is enough to pin the mechanism and the fix; it
is not a reproduction of the document, and a green run here says nothing about the extraction's
behaviour on the real file beyond this class of loss.
"""

import pytest
from pipeline.stage_01_ingest.ingest import (
    _bq_item_inventory,
    attach_heading_chains,
    recover_dropped_sor_items,
    sequence_gaps,
)
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

# The bill as the extractor SEES it: [page n] markers, a bill banner, indented headings, ruled rows
# and the carried-forward footer. Every row below is in the document.
DOC_TEXT = """=== I-ND_2025_04_BQ-0.pdf ===
[page 1]
BILL NO. 1 : GENERAL AND PRELIMINARIES
  Contractual Requirements
    1.1     Provide performance bond                                    Sum
    1.2     Insurances of the Works                                     Sum
    1.11    Provide and maintain temporary access                       Sum
  Site Establishment
    1.12    Provide and maintain site office accommodation      mo    24
    1.18    Attendance on the Engineer's staff                  mo    24
    1.19    Remove site office on completion                    Sum
    1.31    Maintain the works after completion                 Sum
    1.12 to 1.18 carried to collection
[page 2]
BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS
  Drilling
    2.1     Mobilisation and demobilisation of drilling plant   Sum
    2.2     Rotary drilling in soil, depth not exceeding 10 m   m     420
    2.3     Rotary drilling in rock                             m     180
[page 3]
BILL NO. 7 : INSTRUMENTATION
  Instrument Installation
    7.1     Standpipe piezometer, install and commission        nr    12
    7.2     Vibrating wire piezometer, install and commission   nr    8
    7.3     Inclinometer casing                                 m     60
                                                     Collection      1,830.00
"""


def _scope(refs: list[str]) -> ScopePackages:
    """What the extraction returned — the rows that survived the chunk that carried them."""
    return ScopePackages(project_name="ND/2025/04", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref=r, description=f"extracted {r}", section=r.split(".")[0])
                   for r in refs],
    )])


def _refs(scope: ScopePackages) -> list[str]:
    return sorted((it.item_ref for p in scope.packages for it in p.sor_items),
                  key=lambda r: [int(n) for n in r.split(".")])


# -- the exact refs the live split reported missing -----------------------------------------------
def test_bill_2_gets_item_2_2_back():
    scope = _scope(["2.1", "2.3"])
    assert "2.2" in _refs(recover_dropped_sor_items(scope, DOC_TEXT))


def test_bill_7_gets_item_7_2_back():
    scope = _scope(["7.1", "7.3"])
    assert "7.2" in _refs(recover_dropped_sor_items(scope, DOC_TEXT))


def test_bill_1_recovers_both_ends_not_only_the_interior():
    """1.1-1.11 sit BELOW the extracted minimum and 1.19-1.31 above its maximum.

    `sequence_gaps` cannot see either — it reports the interior only, on purpose, because a bill
    may legitimately begin at 3. Recovery is not bound that way: the reference leads a line in the
    document, so it is not a guess about where the bill starts.
    """
    scope = _scope(["1.12", "1.18"])
    # The report sees 13-17, which sit between the two extracted rows, and NOTHING at either end.
    assert sequence_gaps(scope) == {"1": [13, 14, 15, 16, 17]}
    got = _refs(recover_dropped_sor_items(scope, DOC_TEXT))
    assert got == ["1.1", "1.2", "1.11", "1.12", "1.18", "1.19", "1.31"]
    # 1.13-1.17 are not in this fixture's text, and recovery does not invent what is not there —
    # class (a) loss (absent from source) stays reported and unrecovered, which is the honest answer.
    assert not {"1.13", "1.17"} & set(got)


def test_all_three_bills_recover_in_one_pass():
    scope = _scope(["1.12", "1.18", "2.1", "2.3", "7.1", "7.3"])
    got = _refs(recover_dropped_sor_items(scope, DOC_TEXT))
    assert {"1.1", "1.2", "1.11", "1.19", "1.31", "2.2", "7.2"} <= set(got)


# -- a recovered row is a usable row --------------------------------------------------------------
def test_a_recovered_row_carries_the_document_s_description():
    scope = _scope(["2.1", "2.3"])
    out = recover_dropped_sor_items(scope, DOC_TEXT)
    item = next(it for p in out.packages for it in p.sor_items if it.item_ref == "2.2")
    assert item.description.startswith("Rotary drilling in soil")
    assert item.section == "2"                              # THE BILL IS THE SECTION


def test_a_recovered_row_gets_its_heading_chain():
    """A BQ item's full description is the chain above it — `2.2` alone means nothing.

    `attach_heading_chains` runs after recovery in `ingest_tender`, so this is the order the
    pipeline uses, not an order invented for the test.
    """
    scope = recover_dropped_sor_items(_scope(["2.1", "2.3"]), DOC_TEXT)
    out = attach_heading_chains(scope, DOC_TEXT)
    item = next(it for p in out.packages for it in p.sor_items if it.item_ref == "2.2")
    assert "Drilling" in item.heading_path


def test_an_extracted_row_is_never_overwritten():
    # Additive only: the extraction's own description survives, chain and all.
    out = recover_dropped_sor_items(_scope(["2.1", "2.2", "2.3"]), DOC_TEXT)
    item = next(it for p in out.packages for it in p.sor_items if it.item_ref == "2.2")
    assert item.description == "extracted 2.2"


# -- and nothing is invented ----------------------------------------------------------------------
def test_a_bill_the_extraction_never_saw_is_not_opened():
    """The precision guard. Bill 7 rows are in the text; an extraction that produced no bill-7
    item is not told that bill 7 exists — a stray `7.2` elsewhere would be a clause reference."""
    got = _refs(recover_dropped_sor_items(_scope(["2.1", "2.3"]), DOC_TEXT))
    assert not any(r.startswith("7.") for r in got)


def test_the_carried_forward_footer_is_not_an_item():
    inv = _bq_item_inventory(DOC_TEXT, {"1"})
    # `1.12 to 1.18 carried to collection` opens with a real reference and is not a priced row.
    assert inv["1.12"].startswith("Provide and maintain site office")


def test_furniture_and_collection_lines_yield_nothing():
    text = "\n".join([
        "BILL NO. 2 : GROUND INVESTIGATION",
        "Item No.  Description  Unit  Qty",
        "2.1  Mobilisation  Sum",
        "Total carried to Collection    1,830.00",
        "Page BQ/2/3",
    ])
    assert set(_bq_item_inventory(text, {"2"})) == {"2.1"}


def test_an_amount_row_with_no_words_is_not_an_item():
    assert _bq_item_inventory("2.4    250.00    1,830.00", {"2"}) == {}


def test_a_contents_line_with_dotted_leaders_is_not_recovered_as_a_priced_row():
    # A leader row carries the ref and a title; it is the same item, so recovering it is honest —
    # what must not happen is recovering the PAGE NUMBER as the description.
    inv = _bq_item_inventory("2.4 .......................... 14", {"2"})
    assert inv == {}


def test_no_bill_in_the_scope_means_no_scan_at_all():
    # A Schedule of Rates has no bill refs, so the bill reader never runs over its text.
    assert _bq_item_inventory(DOC_TEXT, set()) == {}


def test_a_schedule_of_rates_is_untouched_by_the_new_reader():
    """The other family's path must be byte-for-byte what it was."""
    sor_text = "SECTION G : DRILLING\nG7  Cable percussion boring   m   120\nG8  Rotary core   m   80\n"
    scope = ScopePackages(project_name="GI", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref="G7", description="Cable percussion boring", section="G")],
    )])
    out = recover_dropped_sor_items(scope, sor_text)
    assert sorted(it.item_ref for p in out.packages for it in p.sor_items) == ["G7", "G8"]


def test_a_date_that_reached_the_reference_column_opens_no_bill():
    # `_BILL_REF_RE` bounds a bill number at two digits, and the guard is restated here: a document
    # whose scope carries bills 1 and 2 must not gain an item from `2025.1`.
    assert _bq_item_inventory("2025.1  Signed this day", {"1", "2"}) == {}


@pytest.mark.parametrize("ref", ["2.2", "7.2", "1.19"])
def test_every_reported_ref_is_recoverable_individually(ref):
    bill = ref.split(".")[0]
    others = {"1": ["1.12", "1.18"], "2": ["2.1", "2.3"], "7": ["7.1", "7.3"]}[bill]
    assert ref in _refs(recover_dropped_sor_items(_scope(others), DOC_TEXT))
