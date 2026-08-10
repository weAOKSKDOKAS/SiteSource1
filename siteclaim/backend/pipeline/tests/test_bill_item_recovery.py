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


# ---------------------------------------------------------------------------
# The wrapped description whose quantity and unit land INSIDE it — BQ 1.53
# ---------------------------------------------------------------------------
# Read independently off the real bill (I-ND_2025_04_BQ-0.pdf, Bill 1, page 7): 1.53's
# description wraps across printed lines, and in EXTRACTION ORDER the quantity and unit sit
# between the two halves. The neighbouring 1.52, whose description fits one line, extracts
# cleanly — which is why 1.53 alone was the gap in 163 items. Same rule as the module docstring:
# this is the SHAPE of the real text, not the document.
WRAPPED_1_53 = """Bill No. 1
1.52
Complete Implementation Plan for Smart Site
-
item
-
1.53
Review, update and implement Implementation
20
mth
Plan for Smart Site Safety System
Site Communication Network
1.54
Provide site communication network
20
mth
"""


class TestTheWrappedDescriptionIsCollectedWhole:
    def test_the_interleaved_quantity_and_unit_do_not_split_the_description(self):
        """THE 1.53 DEFECT. A reader that stops at the first quantity-looking token keeps half
        the description — or, for a bare ref line, none: the old inventory skipped `1.53`
        outright for having no letters on its own line, so the deterministic backstop was blind
        to exactly the row the extraction mangles.

        The fixture now carries the NEXT section's heading ("Site Communication Network") right
        after the wrapped tail, because the real pack does — and the first cut of this collector
        appended it, shipping "…Smart Site Safety System Si…" at the 80-char cap. One fragment
        after the columns, then stop: the heading never enters the description."""
        inv = _bq_item_inventory(WRAPPED_1_53, {"1"})
        assert inv["1.53"] == (
            "Review, update and implement Implementation Plan for Smart Site Safety System")

    def test_the_fragment_never_becomes_a_row_of_its_own(self):
        """The 64-versus-63 half of the same defect: the bill prints 63 items and one count came
        back 64 — an over-count, so something was read twice, and the likeliest something is a
        wrapped fragment taken for a row. In this inventory the fragment cannot become one:
        `Plan for Smart Site Safety System` opens with no item number, and the three refs here
        stay exactly three."""
        inv = _bq_item_inventory(WRAPPED_1_53, {"1"})
        assert sorted(inv) == ["1.52", "1.53", "1.54"]

    def test_a_single_line_neighbour_still_reads_as_before(self):
        inv = _bq_item_inventory(WRAPPED_1_53, {"1"})
        assert inv["1.52"] == "Complete Implementation Plan for Smart Site"
        assert inv["1.54"] == "Provide site communication network"

    def test_an_amounts_only_row_still_collects_nothing(self):
        """The guard the collector must not loosen: a ref whose own line carries the AMOUNT
        columns (`2.4  250.00  1,830.00`) is a row whose text sits elsewhere on the page, and the
        lines after it belong to some other row. Only the BARE-ref shape collects."""
        text = "2.4    250.00    1,830.00\nSome other row's wandering text\n"
        assert _bq_item_inventory(text, {"2"}) == {}

    def test_the_collector_is_bounded_and_stops_at_the_next_row(self):
        """A bare ref at the end of a page must not swallow the page footer or the next bill's
        prose — the collection stops at page furniture and is capped."""
        text = "1.53\nReview, update and implement Implementation\n" + "=== next doc ===\n" \
               + "This prose belongs to another document entirely\n"
        inv = _bq_item_inventory(text, {"1"})
        assert inv["1.53"] == "Review, update and implement Implementation"


# ---------------------------------------------------------------------------
# The fully detached shape — BQ 1.45-1.50, where sequence CANNOT and position can
# ---------------------------------------------------------------------------
# Real page-6 extraction order, verbatim from the independent read of the pack: the six refs and
# their column tokens come early, every description sits at the page tail — and the tail is
# ITSELF scrambled ("…wastewater" at [65], its continuation "collection system" at [74];
# "…fuel samples by" at [77], its "laboratory" at [73]). Any order-based pairing of tail lines
# to refs mis-attaches, which is why this fixture must defeat a sequence-based "fix".
PAGE6_SEQUENCE = """Bill No. 1
1.45
-
item
-
1.46
-
item
-
1.47
-
item
-
1.48
-
item
-
1.49
20
nr.
1.50
20
mth
1.51
Digital Works Supervision System (DWSS)
20
mth
Provision, maintenance and removal of wastewater
Noise Pollution Abatement
Provision, maintenance and removal of acoustic screens
or enclosures
Adoption of other noise abatement practices
Arrange and conduct on-site sorting of C&D materials
laboratory
collection system
Arrange and conduct testing of fuel samples by
Provide environmental management measures
"""

# The same page as pymupdf's words see it: refs at x=64.3, headings at x=93.2, descriptions
# between the ref and the column tokens, same-row words sharing a y. Continuation lines
# ("collection system", "laboratory", "or enclosures") sit on their own y directly under their
# rows, opening lowercase — the pack's headings always open upper-case.
def _row_words(y, tokens, x0=64.3, dx=38.0):
    return [(x0 + i * dx, y, x0 + i * dx + 30.0, y + 9.0, tok) for i, tok in enumerate(tokens)]


PAGE6_WORDS = [
    *_row_words(311.0, ["1.45", "Provision,", "maintenance", "and", "removal", "of",
                        "acoustic", "screens", "-", "item", "-"]),
    *_row_words(325.0, ["or", "enclosures"], x0=93.2),
    *_row_words(345.0, ["1.46", "Adoption", "of", "other", "noise", "abatement",
                        "practices", "-", "item", "-"]),
    *_row_words(362.0, ["Wastewater", "Pollution", "Abatement"], x0=93.2),   # a heading row
    *_row_words(390.0, ["1.47", "Provision,", "maintenance", "and", "removal", "of",
                        "wastewater", "-", "item", "-"]),
    *_row_words(404.0, ["collection", "system"], x0=93.2),
    *_row_words(420.0, ["Waste", "Management"], x0=93.2),                    # a heading row
    *_row_words(445.0, ["1.48", "Arrange", "and", "conduct", "on-site", "sorting",
                        "of", "C&D", "materials", "-", "item", "-"]),
    *_row_words(488.0, ["1.49", "Arrange", "and", "conduct", "testing", "of", "fuel",
                        "samples", "by", "20", "nr."]),
    *_row_words(502.0, ["laboratory"], x0=93.2),
    *_row_words(543.0, ["1.50", "Provide", "environmental", "management", "measures",
                        "20", "mth"]),
]


class TestTheDetachedDescriptionsNeedThePage:
    def test_sequence_reading_cannot_see_these_six_and_says_nothing_false(self):
        """THE FIXTURE'S JOB: prove a sequence-based fix cannot pass. The forward collector sees
        only column tokens between each bare ref and the next ref, finds no description, and the
        rows honestly never inventory — absent, not mis-attached from the scrambled tail."""
        from pipeline.stage_01_ingest.ingest import _bq_item_inventory

        inv = _bq_item_inventory(PAGE6_SEQUENCE, {"1"})
        for ref in ("1.45", "1.46", "1.47", "1.48", "1.49", "1.50"):
            assert ref not in inv, f"{ref} paired from a scrambled tail — mis-attachment"
        assert inv["1.51"].startswith("Digital Works Supervision System"), "adjacent still works"

    def test_position_reconstructs_all_six_rows_perfectly(self):
        from pipeline.stage_01_ingest.ingest import positional_bill_rows

        inv = positional_bill_rows([PAGE6_WORDS], {"1"})
        assert inv == {
            "1.45": "Provision, maintenance and removal of acoustic screens or enclosures",
            "1.46": "Adoption of other noise abatement practices",
            "1.47": "Provision, maintenance and removal of wastewater collection system",
            "1.48": "Arrange and conduct on-site sorting of C&D materials",
            "1.49": "Arrange and conduct testing of fuel samples by laboratory",
            "1.50": "Provide environmental management measures",
        }

    def test_a_heading_row_is_neither_an_item_nor_a_continuation(self):
        """"Wastewater Pollution Abatement" sits between 1.46 and 1.47 as its own row. It opens
        upper-case, so it is not appended to 1.46; it opens with a word, not a ref, so it is
        never an item. Both failure modes are the mis-attachment the y/x reading exists to end."""
        from pipeline.stage_01_ingest.ingest import positional_bill_rows

        inv = positional_bill_rows([PAGE6_WORDS], {"1"})
        assert "Wastewater" not in inv["1.46"] and "Waste Management" not in inv["1.47"]
        assert len(inv) == 6, "exactly the six items — nothing promoted from a heading"

    def test_recovery_fills_the_holes_from_position_and_sequence_still_wins_where_it_reads(self):
        """The merge discipline: the positional read fills only the holes. 1.51 arrives from the
        SEQUENCE text (adjacent description); the six arrive from the page's geometry; all seven
        land in the package that owns Bill 1."""
        from pipeline.stage_01_ingest.ingest import recover_dropped_sor_items

        scope = ScopePackages(project_name="ND/2025/04", packages=[
            TradeWorkPackage(trade="builders_work", scope_summary="Preliminaries", sor_items=[
                SorItem(item_ref="1.44", description="Screens for smoky activities",
                        unit="item", section="1"),
            ]),
        ])
        out = recover_dropped_sor_items(scope, PAGE6_SEQUENCE, page_words=[PAGE6_WORDS])
        by_ref = {it.item_ref: it for it in out.packages[0].sor_items}
        assert set(by_ref) == {"1.44", "1.45", "1.46", "1.47", "1.48", "1.49", "1.50", "1.51"}
        assert by_ref["1.47"].description == (
            "Provision, maintenance and removal of wastewater collection system")
        assert by_ref["1.51"].description.startswith("Digital Works Supervision System")

    def test_without_page_words_behaviour_is_exactly_the_pre_fallback_one(self):
        """The fallback is additive: no words, no change — the sequence path is byte-for-byte
        what it was, so every caller that cannot supply positions (the procurement upload path)
        is untouched."""
        from pipeline.stage_01_ingest.ingest import recover_dropped_sor_items

        scope = ScopePackages(project_name="x", packages=[
            TradeWorkPackage(trade="builders_work", scope_summary="s", sor_items=[
                SorItem(item_ref="1.44", description="d", unit="item", section="1"),
            ]),
        ])
        out = recover_dropped_sor_items(scope, PAGE6_SEQUENCE)
        refs = {it.item_ref for it in out.packages[0].sor_items}
        assert not ({"1.45", "1.46", "1.47", "1.48", "1.49", "1.50"} & refs)
        assert "1.51" in refs


# ---------------------------------------------------------------------------
# One ref, two rows — the 64-from-63 instrument
# ---------------------------------------------------------------------------
class TestADuplicateRefIsNamedNeverDropped:
    """The routing card counted 64 Bill 1 items where the bill prints 63 (1.1-1.63, verified, no
    gaps, no letter suffixes) — an over-count, so something is counted twice. The demonstrated
    path: the chunk merge dedups by ref within one trade only, and consolidation reunites strays
    with no dedup on arrival. Whether that is what happened on the live run needs the live
    artifacts; what the deterministic layer can do NOW is make the next run diagnose itself."""

    def _dup_scope(self) -> ScopePackages:
        return ScopePackages(project_name="ND/2025/04", packages=[
            TradeWorkPackage(trade="builders_work", scope_summary="prelims", sor_items=[
                SorItem(item_ref="1.53", description="Review, update and implement Implementation",
                        unit="mth", section="1"),
            ]),
            TradeWorkPackage(trade="ground_investigation", scope_summary="gi", sor_items=[
                SorItem(item_ref="1.53", description="Plan for Smart Site Safety System",
                        unit="mth", section="1"),
                SorItem(item_ref="2.1", description="Establishment of rigs", unit="nr",
                        section="2"),
            ]),
        ])

    def test_the_note_names_the_ref_the_count_and_both_homes(self):
        from pipeline.stage_01_ingest.ingest import report_duplicate_refs

        notes: list[str] = []
        report_duplicate_refs(self._dup_scope(), on_note=notes.append)
        assert len(notes) == 1
        assert "item 1.53 appears on 2 rows" in notes[0]
        assert "builders_work" in notes[0] and "ground_investigation" in notes[0]
        assert "counted 2 times" in notes[0]
        assert "Nothing was dropped" in notes[0]

    def test_nothing_is_dropped_or_moved_by_the_report(self):
        """Deliberate: the two rows carry different halves of the description, and which to keep
        is a reconciliation, not a coin toss. A silent dedup would make the count look right for
        the wrong reason."""
        from pipeline.stage_01_ingest.ingest import report_duplicate_refs

        scope = self._dup_scope()
        report_duplicate_refs(scope, on_note=lambda _n: None)
        assert sum(len(p.sor_items) for p in scope.packages) == 3

    def test_a_duplicate_inside_one_package_is_caught_too(self):
        """Consolidation reunites the two copies into ONE package — the report must not depend on
        them still sitting apart."""
        from pipeline.stage_01_ingest.ingest import report_duplicate_refs

        scope = ScopePackages(project_name="x", packages=[
            TradeWorkPackage(trade="builders_work", scope_summary="s", sor_items=[
                SorItem(item_ref="1.53", description="half one", unit="mth", section="1"),
                SorItem(item_ref="1.53", description="half two", unit="mth", section="1"),
            ]),
        ])
        notes: list[str] = []
        report_duplicate_refs(scope, on_note=notes.append)
        assert len(notes) == 1 and "appears on 2 rows" in notes[0]

    def test_a_letter_variant_is_a_distinct_row_not_a_duplicate(self):
        """TA2 inserted 1.61A beside 1.61 — two real rows. Identity is the full reference."""
        from pipeline.stage_01_ingest.ingest import report_duplicate_refs

        scope = ScopePackages(project_name="x", packages=[
            TradeWorkPackage(trade="builders_work", scope_summary="s", sor_items=[
                SorItem(item_ref="1.61", description="VR safety training", unit="item",
                        section="1"),
                SorItem(item_ref="1.61A", description="Signboard, size A", unit="nr",
                        section="1"),
            ]),
        ])
        assert report_duplicate_refs(scope, on_note=None) == []

    def test_a_clean_scope_reports_nothing(self):
        from pipeline.stage_01_ingest.ingest import report_duplicate_refs

        scope = ScopePackages(project_name="x", packages=[
            TradeWorkPackage(trade="builders_work", scope_summary="s", sor_items=[
                SorItem(item_ref="1.1", description="a", unit="item", section="1"),
                SorItem(item_ref="1.2", description="b", unit="item", section="1"),
            ]),
        ])
        assert report_duplicate_refs(scope, on_note=None) == []
