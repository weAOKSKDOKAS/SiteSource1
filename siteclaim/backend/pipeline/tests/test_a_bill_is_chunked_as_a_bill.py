"""The model was handed a bill of quantities cut up along its specification cross-references.

`_split_into_blocks` tried the Section boundary unconditionally first, on a stated belief its own
docstring spelled out: *"a Bill of Quantities has no Section headers to find and falls through to
the Bill form"*. It has dozens. This issuer prints a `SECTION n : …` line on EVERY bill page,
naming the Standard Method of Measurement section the bill is measured under — the same line
`doc_index.bill_mm_sections` reads as a cross-reference, ten for ten on the real pack.

So the Bill branch never ran. Bill 1's rows landed in a block headed `SECTION 3 : SITE CLEARANCE`,
`_row_batches` repeated that line as the header on every 30-row batch — handing the model a
specification reference as each batch's context instead of `Bill No. 1` — and a batch the extractor
gave up on was reported to the operator as *"section 3 (SITE CLEARANCE): the extractor's JSON was
truncated … this batch was skipped"*, naming a document that contains none of the lost rows.

Two rules, both already in the repo, applied here:

**Decide the family before choosing the boundary.** `annotate_sections` and `section_family`
already do this — a `SECTION n` line inside a document that has said `Bill No. n` is pointing
somewhere else. A Schedule of Rates declares no bills, so its path is untouched.

**One rule tells a header from a footer.** The split is on `doc_index.bill_header_number`, not on
`_BILL_RE`, because the regex cannot tell `Bill No. 9` from `Bill No. 9 - Total Carried to Grand
Summary`. Splitting on the regex started a new block at every collection footer, so each bill grew
a phantom trailing block named after the line that CLOSES it.
"""

import pytest

from pipeline.stage_01_ingest.ingest import (
    _chunk_label,
    _row_batches,
    _split_into_blocks,
    declares_bills,
)

# The real shape: a bare bill header, a `SECTION n` measurement reference on each page, and the
# collection footer that closes the bill.
BILL = """=== I-ND_2025_04_BQ-0.pdf ===
[page 1]
Bill No. 1 : GENERAL AND PRELIMINARIES
SECTION 1 : GENERAL
1.1  Provide site office                                    item        1
1.2  Insurances                                             item        1
[page 2]
SECTION 3 : SITE CLEARANCE
1.12 Clear site vegetation                                  m2        400
1.18 Remove obstructions                                    m3         20
Bill No. 1 - Total Carried to Grand Summary
[page 3]
Bill No. 2 : GROUND INVESTIGATION FIELDWORKS
SECTION 2 : GROUND INVESTIGATION
2.1  Rotary drilling                                        m         500
2.2  Standard penetration test                              nr        120
Bill No. 2 - Total Carried to Grand Summary
"""

SOR = """=== SoR_ground_investigation.xlsx ===
SECTION A : PRELIMINARIES ITEMS
A1  Site setup                                              item        1
A2  Site clearance                                          item        1
SECTION B : DRILLING
B1  Rotary core drilling                                    m         500
B2  Casing                                                  m         120
"""


def _blocks(text: str) -> list[str]:
    return _split_into_blocks(text)


def _block_with(text: str, needle: str) -> str:
    return next(b for b in _blocks(text) if needle in b)


def _first_line(block: str) -> str:
    return next((ln for ln in block.splitlines() if ln.strip()), "")


def _rows(block: str) -> list[str]:
    return [ln.split()[0] for ln in block.splitlines()
            if ln.strip() and ln.split()[0][0].isdigit()]


# -- the family is decided first --------------------------------------------------------------
def test_a_bill_of_quantities_declares_bills():
    assert declares_bills(BILL) is True


def test_a_schedule_of_rates_declares_none():
    """The whole mechanism stays out of the SoR path — that path is live and must not move."""
    assert declares_bills(SOR) is False


def test_one_bill_reference_in_prose_is_not_a_declaration():
    """A single `Bill No. 3` mention is a cross-reference. Two openings is a bill document."""
    assert declares_bills("See Bill No. 3 for the measured rates.\n") is False


def test_a_collection_footer_does_not_declare_a_bill():
    """`Bill No. 9 - Total Carried to Grand Summary` CLOSES bill 9 and opens nothing — the one
    rule `doc_index.bill_header_number` exists to state."""
    footers = ("Bill No. 1 - Total Carried to Grand Summary\n"
               "Bill No. 2 - Total Carried to Grand Summary\n")
    assert declares_bills(footers) is False


# -- every bill row is in its own bill ------------------------------------------------------------
def test_a_bills_rows_are_in_that_bills_block():
    """The defect in one assertion: 1.12 and 1.18 sat under `SECTION 3 : SITE CLEARANCE`."""
    assert _rows(_block_with(BILL, "1.12")) == ["1.1", "1.2", "1.12", "1.18"]


def test_the_block_is_headed_by_the_bill_not_by_a_measurement_reference():
    assert _first_line(_block_with(BILL, "1.12")) == "Bill No. 1 : GENERAL AND PRELIMINARIES"


def test_no_block_is_headed_by_a_section_line():
    for block in _blocks(BILL):
        assert not _first_line(block).upper().startswith("SECTION "), block[:80]


def test_the_second_bill_gets_its_own_block():
    assert _rows(_block_with(BILL, "2.1")) == ["2.1", "2.2"]
    assert _first_line(_block_with(BILL, "2.1")).startswith("Bill No. 2")


def test_the_collection_footer_stays_inside_its_own_bill():
    """Splitting on `_BILL_RE` started a block at every footer, so each bill grew a phantom
    trailing block named after the line that closes it."""
    blocks = _blocks(BILL)

    assert "Total Carried to Grand Summary" in _block_with(BILL, "1.12")
    assert not any(_first_line(b).endswith("Total Carried to Grand Summary") for b in blocks)
    assert len(blocks) == 3, [_first_line(b) for b in blocks]


def test_every_row_survives_the_split():
    """A chunker that loses a row loses a priced line. The count is the guard."""
    assert sorted(r for b in _blocks(BILL) for r in _rows(b)) == \
        ["1.1", "1.12", "1.18", "1.2", "2.1", "2.2"]


# -- the batch context handed to the model ---------------------------------------------------------
def test_every_batch_of_a_bill_repeats_its_bill_header():
    """`_row_batches` repeats the block's leading header on each batch — that repeated line is
    literally the context the model reads the rows under."""
    batches = _row_batches(_block_with(BILL, "1.12"), 2)

    assert len(batches) > 1, "the fixture must actually batch for this to mean anything"
    for batch in batches:
        assert _first_line(batch) == "Bill No. 1 : GENERAL AND PRELIMINARIES"


# -- what a failed batch is called ------------------------------------------------------------------
def test_a_failed_bill_batch_is_named_after_its_bill():
    """The operator sentence. "section 3 (SITE CLEARANCE)" sent them to a specification holding
    none of the rows that went missing."""
    assert _chunk_label(_block_with(BILL, "1.12")) == "bill 1 (GENERAL AND PRELIMINARIES)"


def test_a_label_is_never_the_collection_footer():
    footer_block = "Bill No. 4 - Total Carried to Grand Summary\n   sub-total   1,234.00\n"
    assert "Total Carried" not in _chunk_label(footer_block)


def test_only_a_batchs_own_leading_header_names_it():
    """A `Bill No. 7` line lower down is a cross-reference, not this batch's identity."""
    block = ("SECTION B : DRILLING\n"
             "B1  Rotary core drilling per Bill No. 7                      m    500\n")
    assert _chunk_label(block) == "section B (DRILLING)"


# -- the Schedule-of-Rates path is byte-for-byte what it was -------------------------------------------
def test_a_schedule_of_rates_still_chunks_on_its_sections():
    assert [_first_line(b) for b in _blocks(SOR)] == [
        "=== SoR_ground_investigation.xlsx ===",
        "SECTION A : PRELIMINARIES ITEMS",
        "SECTION B : DRILLING",
    ]


def test_a_schedule_of_rates_batch_is_still_named_by_its_section():
    assert _chunk_label(_block_with(SOR, "B1")) == "section B (DRILLING)"


def test_a_document_with_neither_still_falls_through_to_pages():
    text = "[page 1]\nsome prose\n[page 2]\nmore prose\n"
    assert len(_blocks(text)) == 2


def test_a_document_with_nothing_to_split_on_is_one_block():
    assert _blocks("just some text\n") == ["just some text\n"]
