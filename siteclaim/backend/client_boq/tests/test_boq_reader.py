"""The bill reader — that it survives a real workbook and never guesses.

The rule these defend: **a bill item's identity is what the client prints, and everything the reader
cannot do cleanly is said out loud.** Both halves matter. A reader that merges item 1.2 with item
1.20 prices two different pieces of work at one rate and nothing on screen looks wrong; a reader
that quietly repairs an oddity produces a number nobody can trace back to the document.

Every case here is measured from the real ND/2025/04 workbook and reproduced by ``_bqfixture``.
See ``docs/client_boq/prd_boq_costing.md`` section 2.10 for the source evidence.
"""

from __future__ import annotations

import pytest

from client_boq.boq.reader import format_ref, normalise_unit, read_workbook
from client_boq.tests._bqfixture import build_bill_workbook

pytest.importorskip("openpyxl")


@pytest.fixture(scope="module")
def bills(tmp_path_factory):
    root = tmp_path_factory.mktemp("boq")
    return {rev: read_workbook(build_bill_workbook(root / f"bq-{rev}.xlsx", rev), set_id="t", rev=rev)
            for rev in (0, 1, 2)}


class TestTheReferenceIsWhatIsPrinted:
    """Excel stores 1.20 as 1.2. The number format is the only thing that distinguishes item 1.20
    from item 1.2, and they are different items at different rates."""

    def test_the_same_stored_value_yields_two_items_under_two_formats(self, bills):
        index = bills[0].index()
        assert "1.2" in index and "1.20" in index
        assert index["1.2"].description.startswith("air-conditioned")
        assert index["1.20"].description.startswith("operation and maintenance")
        assert index["1.2"].qty == 1 and index["1.20"].qty == 122

    def test_every_collision_in_the_fixture_survives(self, bills):
        index = bills[0].index()
        for a, b in (("1.2", "1.20"), ("2.1", "2.10"), ("9.1", "9.10")):
            assert a in index and b in index, f"{a} and {b} must both exist"
            assert index[a].description != index[b].description

    def test_a_reference_stored_as_a_string_is_kept_verbatim(self, bills):
        assert "1.61A" in bills[2].index()

    def test_a_lossy_reference_is_used_as_printed_and_the_discrepancy_is_reported(self, bills):
        # The real bill holds 2.244 under '0.00' and prints "2.24". The printed form is the identity
        # the PDF, the Index and the addenda all cite, so it wins — and the estimator is told.
        item = bills[0].index()["2.24"]
        assert "2.244" in item.notes[0] and "2.24" in item.notes[0]

    def test_format_ref_directly(self):
        assert format_ref(1.2, "General") == ("1.2", "")
        assert format_ref(1.2, "0.00")[0] == "1.20"
        assert format_ref(2.1, "0.00")[0] == "2.10"
        assert format_ref("1.61A", "General") == ("1.61A", "")
        rendered, note = format_ref(2.244, "0.00")
        assert rendered == "2.24" and note


class TestAnItemsMeaningIsItsHeadingChain:
    """General Preambles 2: the "headings, sub-headings, item descriptions ... identify the work
    covered". An item's own cell is frequently meaningless on its own."""

    def test_the_chain_is_reconstructed(self, bills):
        item = bills[0].index()["2.9"]
        assert item.description == "maximum depth not exceeding 3.00m"          # meaningless alone
        assert "Extra over for excavation in rock" in item.heading_path
        assert "SECTION 2 - GROUND INVESTIGATION" in item.heading_path

    def test_the_section_banner_is_not_overwritten_by_the_captions_beneath_it(self, bills):
        # Both sit in column B, so a naive depth-by-column stack loses the section.
        assert bills[0].index()["1.5"].heading_path[0] == "SECTION 1 - PRELIMINARIES"
        assert bills[0].index()["1.62"].heading_path[0] == "SECTION 3 - SITE CLEARANCE"

    def test_a_caption_wrapped_over_two_rows_is_one_caption(self, bills):
        # "minor project signboard as CEDD Drawing" / "Nos. C1003/1I and C1003/2B" is one
        # sub-heading on two rows, as "SECTION 24 - LANDSCAPE SOFTWORKS AND " / "ESTABLISHMENT
        # WORKS" is in the real bill. Treated as two, the first would be silently replaced.
        assert "minor project signboard as CEDD Drawing Nos. C1003/1I and C1003/2B" in \
            bills[2].index()["1.61A"].heading_path

    def test_an_item_description_wrapped_over_two_rows_is_one_description(self, bills):
        assert bills[0].index()["9.10"].description == \
            "Arrange and hold Pre-work Activities of Site Safety Cycle"


class TestDescriptionsWrappedByHand:
    def test_a_continuation_needing_a_space_gets_one(self, bills):
        # "...test for" + "soil and ground water " must not become "...test forsoil...".
        assert bills[0].index()["4.18"].description == \
            "Determination of carbonate content test for soil and ground water"

    def test_a_continuation_carrying_its_own_space_does_not_get_two(self, bills):
        assert bills[0].index()["1.2"].description == (
            "air-conditioned environmentally-friendly petrol private car vehicle with seating "
            "capacity of not less than 7 seats excluding driver")


class TestQuantitiesAndUnits:
    def test_a_lump_item_has_no_quantity_and_is_not_zero(self, bills):
        item = bills[0].index()["1.5"]
        assert item.lump is True and item.qty is None

    def test_a_genuine_zero_is_not_a_lump_and_still_needs_a_rate(self, bills):
        item = bills[0].index()["2.5"]
        assert item.lump is False and item.qty == 0.0

    def test_unit_spellings_fold_but_the_raw_string_is_kept(self, bills):
        index = bills[0].index()
        assert index["1.6"].unit == "item" and index["1.6"].unit_raw == "item "
        assert index["1.63"].unit == "item" and index["1.63"].unit_raw == "Item"
        assert index["1.2"].unit == "nr" and index["1.2"].unit_raw == "nr."

    def test_normalise_unit_directly(self):
        assert {normalise_unit(u) for u in ("item", "item ", "Item")} == {"item"}
        assert {normalise_unit(u) for u in ("nr", "nr.", "nr. ")} == {"nr"}

    def test_a_quantity_stranded_on_the_caption_row_is_adopted_and_declared(self, bills):
        item = bills[0].index()["1.16"]
        assert item.qty == 1 and item.unit == "nr"
        assert any("caption row above" in note for note in item.notes)


class TestStructure:
    def test_page_references_come_from_the_page_breaks(self, bills):
        # BQ/1/2 appears in no cell of the workbook; it exists only as break geometry.
        assert bills[0].index()["1.2"].page_ref == "BQ/1/1"
        assert bills[0].index()["1.62"].page_ref == "BQ/1/2"

    def test_the_repeated_page_header_is_not_an_item(self, bills):
        refs = set(bills[0].index())
        assert not any(ref.lower().startswith(("item no", "bill no")) for ref in refs)
        assert "Item Description" not in {h for i in bills[0].items for h in i.heading_path}

    def test_pre_priced_items_are_marked_with_the_clients_own_figures(self, bills):
        item = bills[0].index()["9.1"]
        assert item.pre_priced and item.client_rate == 4860 and item.client_amount == 77760

    def test_the_client_inserted_sums_are_read_off_the_grand_summary(self, bills):
        codes = {line.code: line.amount for line in bills[0].summary if line.client_inserted}
        assert codes["B"] == 4342620 and codes["D"] == 1550000 and codes["E"] == 609370

    def test_the_computed_summary_lines_are_read_but_left_empty(self, bills):
        codes = {line.code for line in bills[0].summary}
        assert {"A", "C", "F", "G"} <= codes
        assert all(line.amount is None for line in bills[0].summary if line.code in {"A", "C", "F", "G"})


class TestTheDamagedSheet:
    """Bill No.4 of the real workbook reports 16,384 columns with ~76,500 stray cells and 9,963
    merged ranges, from a fill-right nobody noticed. It printed fine for years."""

    def test_it_reads_without_dying_and_says_it_was_clamped(self, bills):
        assert "4.18" in bills[0].index() and "4.19" in bills[0].index()
        assert any("past column H was ignored" in note for note in bills[0].notes)

    def test_the_stray_cells_did_not_become_items_or_headings(self, bills):
        bill_4 = [item for item in bills[0].items if item.bill_no == "4"]
        assert len(bill_4) == 2
        assert not any("General and Preliminaries" in h for item in bill_4 for h in item.heading_path)


class TestLetteredVariants:
    def test_a_bare_letter_is_qualified_by_the_reference_above_it(self, bills):
        # The spreadsheet stores "a"; the addendum calls it "item no. 2.2a". Unqualified, Bill 2's
        # "a" and Bill 3's "a" would collide.
        index = bills[1].index()
        assert index["2.2a"].qty == 80 and index["2.2b"].qty == 11
        assert index["2.2a"].sub_ref == "a" and index["2.2a"].item_ref == "2.2"

    def test_the_parent_keeps_its_number_and_stops_being_priced(self, bills):
        parent = bills[1].index()["2.2"]
        assert parent.is_parent is True and parent.qty is None
