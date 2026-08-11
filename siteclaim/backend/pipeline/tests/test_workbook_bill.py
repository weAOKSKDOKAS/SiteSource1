"""The bill of quantities, read from the workbook it was written in.

The PDF path works — sorted extraction recovered the heading hierarchy and Bills 2 and 4 extract
exactly. The case for this is cost and fidelity: that path spent roughly one hundred model calls
over ten minutes on a 26-page bill, lost five items at chunk boundaries and invented one. This
needs zero model calls, cannot lose an item at a boundary because it never chunks, and cannot
scramble reading order because rows are rows.

**The real ND/2025/04 workbook is not in the repo**, so the fixture below is built to its measured
shape and to its established counts: 162 items across nine bills — 63 · 26 · 13 · 28 · 4 · 6 · 8 ·
3 · 11. That proves the reader counts what is actually there and invents nothing; it does not prove
it reads the real file, which only the real file can.
"""

import io

import pytest

from pipeline.stage_01_ingest import workbook as wb

openpyxl = pytest.importorskip("openpyxl")

# The established per-bill counts from the source. 162, not 136, and no invented rows.
REAL_COUNTS = [63, 26, 13, 28, 4, 6, 8, 3, 11]


def _book(build) -> bytes:
    book = openpyxl.Workbook()
    book.remove(book.active)
    build(book)
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


def _furniture(sheet, bill: int) -> None:
    """The page furniture that repeats roughly every 57 rows in the real file."""
    sheet.append([f"Bill No. {bill}"])
    sheet.append(["Item No.", "Item Description", None, None, "Quantity", "Unit", "Rate", "Amount"])


def _nd_shaped() -> bytes:
    """Nine bills at the established counts, with every shape the real file exhibits."""
    def build(book):
        book.create_sheet("Index").append(["Contents"])
        for bill, count in enumerate(REAL_COUNTS, start=1):
            sheet = book.create_sheet(f"Bill No.{bill}")
            _furniture(sheet, bill)
            sheet.append([None, "SECTION HEADING"])                 # column B — a parent
            for n in range(1, count + 1):
                row = sheet.max_row + 1
                if n % 20 == 0:                                     # furniture mid-bill
                    sheet.append(["", "Carried to Collection"])
                    _furniture(sheet, bill)
                    row = sheet.max_row + 1
                # Refs as TEXT. A workbook that stores them as numbers cannot distinguish item
                # `1.1` from `1.10` — they are the same number — and the reader reports that rather
                # than pretending otherwise (see the duplicate-reference test below).
                sheet.append([
                    f"{bill}.{n}", None, f"item {n}", None,
                    10, "nr", None, f"=E{row}*G{row}",
                ])
            sheet.append([None, None, "Carried to Collection"])
        book.create_sheet("Grand Summary").append(["Total"])
    return _book(build)


# -- the counts ---------------------------------------------------------------------------------
def test_the_established_counts_come_back_exactly():
    read = wb.read_workbook(_nd_shaped())
    assert len(read.items) == 162 == sum(REAL_COUNTS)
    assert [read.per_bill[str(b)] for b in range(1, 10)] == REAL_COUNTS


def test_no_row_is_invented():
    read = wb.read_workbook(_nd_shaped())
    assert len(set(i.item_ref for i in read.items)) == len(read.items)   # every ref distinct


def test_index_and_grand_summary_are_not_read():
    """They carry no priced rows; reading them would invent items out of a contents page."""
    read = wb.read_workbook(_nd_shaped())
    assert set(read.sheets_skipped) == {"Index", "Grand Summary"}
    assert len(read.sheets_read) == 9


def test_zero_model_calls(monkeypatch):
    """The whole point. Nothing here may reach the LLM seam."""
    from pipeline import llm_client

    def explode(*a, **k):
        raise AssertionError("the workbook reader made a model call")

    monkeypatch.setattr(llm_client.LLMClient, "complete_json", explode)
    assert len(wb.read_workbook(_nd_shaped()).items) == 162


# -- page furniture -----------------------------------------------------------------------------
def test_page_furniture_is_never_content():
    read = wb.read_workbook(_nd_shaped())
    text = " ".join((i.description or "") + " ".join(i.heading_path) for i in read.items)
    for phrase in ("Carried to Collection", "Item No.", "Bill No."):
        assert phrase not in text


def test_a_banner_repeating_mid_bill_does_not_break_the_heading_stack():
    read = wb.read_workbook(_nd_shaped())
    bill_one = [i for i in read.items if i.section == "1"]
    assert all(i.heading_path == ["SECTION HEADING"] for i in bill_one)


# -- the heading chain IS the column ------------------------------------------------------------
def test_three_indent_levels_become_a_three_level_chain():
    """`5.3` in column D under `Draft final report` in C under `REPORT WORK` in B."""
    def build(book):
        s = book.create_sheet("Bill No.5")
        _furniture(s, 5)
        s.append([None, "REPORT WORK"])
        s.append([None, None, "Draft final report"])
        s.append([5.3, None, None, "laboratory tests", 1, "sum", None, "=E4*G4"])
        s.append([None, None, "Final report"])
        s.append([5.4, None, None, "laboratory tests", 1, "sum", None, "=E6*G6"])

    items = {i.item_ref: i for i in wb.read_workbook(_book(build)).items}
    assert items["5.3"].heading_path == ["REPORT WORK", "Draft final report"]
    assert items["5.4"].heading_path == ["REPORT WORK", "Final report"]
    assert items["5.3"].description == items["5.4"].description == "laboratory tests"


def test_a_sibling_heading_closes_the_one_beside_it():
    """`Recording` is a sibling of `Instrument Installation`, not a child — 6.4 must not inherit
    both. This is the whole of the stack discipline, and in the workbook it is a FACT about which
    column the text sits in rather than a reading of how many spaces were padded."""
    def build(book):
        s = book.create_sheet("Bill No.6")
        _furniture(s, 6)
        s.append([None, "Instrument Installation"])
        s.append([6.1, None, "Standpipe", None, 47, "nr", None, "=E4*G4"])
        s.append([None, "Recording"])
        s.append([6.4, None, "Standpipe", None, 1128, "nr-wk", None, "=E6*G6"])

    items = {i.item_ref: i for i in wb.read_workbook(_book(build)).items}
    assert items["6.1"].heading_path == ["Instrument Installation"]
    assert items["6.4"].heading_path == ["Recording"]
    assert items["6.1"].description == items["6.4"].description == "Standpipe"


# -- lump sum versus quantity × rate ------------------------------------------------------------
def test_a_lump_sum_is_distinguished_from_quantity_times_rate():
    """Bill 9 row 8 is `=E8*G8`; row 38 is `=G38`. In the render both are blank cells."""
    def build(book):
        s = book.create_sheet("Bill No.9")
        _furniture(s, 9)
        s.append([9.1, "Safety officer", None, None, 16, "nr-mth", 4860, "=E3*G3"])
        s.append([9.2, "Safety plan", None, None, None, "sum", 25000, "=G4"])

    items = {i.item_ref: i for i in wb.read_workbook(_book(build)).items}
    assert items["9.1"].is_lump_sum is False
    assert items["9.2"].is_lump_sum is True


def test_a_cached_value_could_never_have_told_us():
    """Both are numbers once evaluated, which is why the workbook must be read with formulas
    intact and why no render can establish this."""
    assert wb._is_lump_sum("=G38") is True
    assert wb._is_lump_sum("=E8*G8") is False
    assert wb._is_lump_sum("25000") is False        # a plain value says nothing


# -- Employer-fixed rates -----------------------------------------------------------------------
def test_an_employer_fixed_rate_is_recorded():
    """Every Bill 9 rate is pre-filled by CEDD under the Pay for Safety Scheme. An engine that
    generates a rate for one of those is wrong by definition, and no current validation flag would
    catch it."""
    def build(book):
        s = book.create_sheet("Bill No.9")
        _furniture(s, 9)
        s.append([9.1, "Safety officer", None, None, 16, "nr-mth", 4860, "=E3*G3"])
        s.append([9.5, "Ours to price", None, None, 4, "nr", None, "=E4*G4"])

    items = {i.item_ref: i for i in wb.read_workbook(_book(build)).items}
    assert items["9.1"].employer_rate == 4860.0
    assert items["9.5"].employer_rate is None        # the tender left this one for us


def test_a_literal_dash_is_not_rated_rather_than_unrated():
    """A semantic marker, not a missing value — "not rated" and "no rate yet" are different
    statements and only one of them invites us to fill it in."""
    def build(book):
        s = book.create_sheet("Bill No.1")
        _furniture(s, 1)
        s.append([1.1, "Non-rated item", None, None, None, "item", "-", "=G3"])

    item = wb.read_workbook(_book(build)).items[0]
    assert item.employer_rate is None


# -- item numbers, recovered and reported but never repaired -------------------------------------
def test_a_trailing_zero_excel_discarded_is_recovered_from_the_number_format():
    """Stored as numbers, `1.20` reads back as `1.2`. The cell's own format is the evidence.

    RE-ANCHORED 2026-08-11, disclosed. The second row was `1.3`, which asserted that a
    General-format reference following `1.20` stays `1.3` — and a bill cannot contain that, because
    a bill numbers its items in ascending order. `restore_dropped_zero` now reads exactly that
    ordering as evidence, so the old fixture pinned a sequence the document it models cannot
    produce. The subject of this test is unchanged and its load-bearing assertion is unchanged:
    a `0.00`-formatted `1.20` still comes back `1.20`, and the second row is still General-format
    and still taken verbatim. Only the impossible ordering is gone. See
    `test_workbook_ref_sequence.py` for the rule the fixture collided with.
    """
    def build(book):
        s = book.create_sheet("Bill No.1")
        _furniture(s, 1)
        s.append([1.20, "Twenty", None, None, 1, "nr", None, "=E3*G3"])
        s.cell(row=s.max_row, column=1).number_format = "0.00"
        s.append([1.21, "Twenty-one", None, None, 1, "nr", None, "=E4*G4"])

    refs = [i.item_ref for i in wb.read_workbook(_book(build)).items]
    assert refs == ["1.20", "1.21"]


def test_a_reference_stored_as_text_is_taken_verbatim():
    def build(book):
        s = book.create_sheet("Bill No.2")
        _furniture(s, 2)
        s.append(["2.10", "As printed", None, None, 1, "nr", None, "=E3*G3"])

    assert wb.read_workbook(_book(build)).items[0].item_ref == "2.10"


def test_two_rows_that_excel_made_indistinguishable_are_reported_and_both_kept():
    """The trailing-zero problem at its irreducible worst: `1.1` and `1.10` stored as NUMBERS are
    the same number, and no format string recovers a difference that is not in the file. Dropping
    one loses a priced item; renaming one invents a reference the tender does not contain."""
    notes: list[str] = []

    def build(book):
        s = book.create_sheet("Bill No.1")
        _furniture(s, 1)
        s.append([1.1, "First", None, None, 1, "nr", None, "=E3*G3"])
        s.append([1.10, "Tenth", None, None, 1, "nr", None, "=E4*G4"])

    read = wb.read_workbook(_book(build), on_note=notes.append)
    assert len(read.items) == 2                                  # both kept
    assert any("appear more than once" in n for n in notes)
    assert any("needs a human eye" in n for n in notes)


def test_a_reference_that_does_not_belong_is_reported_not_repaired():
    """The real file carries a live typo — `2.244` where `2.24` was meant. Repairing a reference
    silently is how a priced row ends up under the wrong bill."""
    notes: list[str] = []

    def build(book):
        s = book.create_sheet("Bill No.2")
        _furniture(s, 2)
        s.append([9.9, "Wrong bill", None, None, 1, "nr", None, "=E3*G3"])

    read = wb.read_workbook(_book(build), on_note=notes.append)
    assert read.items[0].item_ref == "9.9"                     # kept exactly as printed
    assert any("does not belong to this bill" in n for n in notes)


# -- the shape is the SAME shape ----------------------------------------------------------------
def test_it_emits_the_shape_ingest_tender_emits():
    """A second producer of one shape, not a second pipeline — so routing, packages and the split
    report are unchanged."""
    from schemas.models import SorItem

    read = wb.read_workbook(_nd_shaped())
    assert all(isinstance(i, SorItem) for i in read.items)
    assert read.items[0].section == "1"                         # the bill IS the section
    assert read.items[0].qty == 10 and read.items[0].unit == "nr"


def test_the_bill_number_reaches_the_routing_split():
    """`route_units` divides by section exactly as it does for an extracted bill."""
    from pipeline.routing.split import route_units
    from schemas.models import ScopePackages, TradeWorkPackage

    read = wb.read_workbook(_nd_shaped())
    from pipeline.stage_01_ingest.ingest import annotate_sections

    scope = annotate_sections(ScopePackages(project_name="ND", packages=[TradeWorkPackage(
        trade="general_building", scope_summary="bill", sor_items=read.items)]), "")
    units = route_units(scope, split_keys={"general_building"})
    assert [u["section"] for u in units] == [str(n) for n in range(1, 10)]
