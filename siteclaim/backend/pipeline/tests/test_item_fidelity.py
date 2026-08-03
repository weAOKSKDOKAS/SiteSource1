"""An item's real description is the chain of headings above it — and a missing item says so.

CEDD ND/2025/04 extracted 136 priced lines across 9 bills. Two things were wrong with them.

Bill 6 came out as six items and three descriptions:

    6.1  Standpipe          6.4  Standpipe
    6.2  Piezometer         6.5  Piezometer
    6.3  Automatic ...      6.6  Automatic ...

In the workbook, 6.1-6.3 sit under a column-B heading "Instrument Installation" and 6.4-6.6 under
"Recording". 6.1 is INSTALLING a standpipe; 6.4 is RECORDING from one — different work, different
rate, identical string. Bill 5 goes three deep: REPORT WORK -> Draft final report -> "laboratory
tests", twice. The chain is encoded as which column the text sits in, which in the PDF render is
leading whitespace — and whitespace only means anything once the page is read in reading order.

And 136 of 162 items came back with no mention that 26 were missing.
"""

from pipeline.stage_01_ingest.ingest import (
    attach_heading_chains,
    heading_chains,
    report_sequence_gaps,
    sequence_gaps,
)
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

# The ND/2025/04 shape as `sort=True` renders it: headings in the shallower column, items in the
# deeper one. Reproduced by hand because the real bill is not in the repo.
BILL_6 = """[page 18]
LABORATORY TESTING
    Instrument Installation
        6.1     Standpipe        47    nr
        6.2     Piezometer       68    nr
        6.3     Automatic groundwater monitoring device   115   nr
    Recording
        6.4     Standpipe        1128   nr-wk
        6.5     Piezometer       1623   nr-wk
        6.6     Automatic groundwater monitoring device   2760  nr-wk
Carried to Collection
"""

BILL_5 = """[page 15]
REPORT WORK
    Draft final report
        5.3     laboratory tests
    Final report
        5.4     laboratory tests
"""


def _pkg(refs, descriptions=None, trade="ground_investigation"):
    descriptions = descriptions or {}
    return ScopePackages(project_name="ND/2025/04", packages=[
        TradeWorkPackage(trade=trade, scope_summary="GI", sor_items=[
            SorItem(item_ref=r, description=descriptions.get(r)) for r in refs
        ]),
    ])


# -- the serious one: two items that read identically must become distinguishable ---------------
def test_6_1_and_6_4_are_distinguishable():
    chains = heading_chains(BILL_6)
    assert chains["6.1"] == ["LABORATORY TESTING", "Instrument Installation"]
    assert chains["6.4"] == ["LABORATORY TESTING", "Recording"]
    assert chains["6.1"] != chains["6.4"]


def test_the_chain_goes_three_levels_deep():
    chains = heading_chains(BILL_5)
    assert chains["5.3"] == ["REPORT WORK", "Draft final report"]
    assert chains["5.4"] == ["REPORT WORK", "Final report"]


def test_an_item_with_no_description_of_its_own_still_acquires_one():
    """1.45 through 1.50 came out of the live run with no description at all. The heading above
    them is the only thing that says what they are."""
    text = """[page 4]
    Site Supervision Staff
        1.45
        1.46
        1.50
"""
    chains = heading_chains(text)
    assert chains["1.45"] == ["Site Supervision Staff"]
    assert chains["1.50"] == ["Site Supervision Staff"]


def test_a_heading_closes_when_one_at_its_own_column_follows():
    """`Recording` is a sibling of `Instrument Installation`, not a child: 6.4 must not inherit
    both. This is the whole of the stack discipline."""
    assert "Instrument Installation" not in heading_chains(BILL_6)["6.4"]


def test_an_item_level_with_the_text_above_it_inherits_nothing():
    """No chain is the honest answer when the indentation establishes none — never a guess at the
    nearest line above."""
    flat = "Some prose at the left margin\n1.1  A priced item\n"
    assert heading_chains(flat)["1.1"] == []


def test_page_markers_and_block_headers_are_never_headings():
    assert "[page 18]" not in heading_chains(BILL_6)["6.1"]
    text = "=== Bills of Quantities ===\n    Preliminaries\n        1.1  Bond\n"
    assert heading_chains(text)["1.1"] == ["Preliminaries"]


def test_numbers_units_and_footers_are_never_headings():
    assert "Carried to Collection" not in heading_chains(BILL_6)["6.6"]
    text = "    Instrument Installation\n      1,250.00\n      nr\n        6.1  Standpipe\n"
    assert heading_chains(text)["6.1"] == ["Instrument Installation"]


def test_a_schedule_of_rates_ref_gets_a_chain_too():
    """The chain is family-independent — it reads indentation, not reference shape."""
    text = "SECTION H : FIELD INSTALLATIONS\n    Standpipes\n        H1  Install standpipe\n"
    assert heading_chains(text)["H1"] == ["SECTION H : FIELD INSTALLATIONS", "Standpipes"]


def test_the_first_occurrence_of_a_ref_wins():
    """A ref repeated in a collection page must not overwrite the chain from where it was priced."""
    text = BILL_6 + "\n[page 19]\nCollection\n        6.1     Standpipe\n"
    assert heading_chains(text)["6.1"] == ["LABORATORY TESTING", "Instrument Installation"]


# -- the chain is ADDITIONAL, never a replacement -----------------------------------------------
def test_attach_keeps_the_leaf_text_and_adds_the_chain():
    scope = _pkg(["6.1", "6.4"], {"6.1": "Standpipe", "6.4": "Standpipe"})
    out = attach_heading_chains(scope, BILL_6).packages[0]
    assert [i.description for i in out.sor_items] == ["Standpipe", "Standpipe"]  # untouched
    assert out.sor_items[0].heading_path == ["LABORATORY TESTING", "Instrument Installation"]
    assert out.sor_items[1].heading_path == ["LABORATORY TESTING", "Recording"]


def test_an_item_the_document_says_nothing_about_keeps_an_empty_chain():
    out = attach_heading_chains(_pkg(["6.1", "9.9"]), BILL_6).packages[0]
    assert out.sor_items[1].heading_path == []


def test_a_package_that_found_no_chain_at_all_is_reported():
    notes: list[str] = []
    attach_heading_chains(_pkg(["7.1", "7.2"]), BILL_6, on_note=notes.append)
    assert notes and "no heading chain was found" in notes[0]
    assert "read identically" in notes[0]


def test_no_doc_text_is_a_no_op_not_an_erasure():
    scope = _pkg(["6.1"], {"6.1": "Standpipe"})
    out = attach_heading_chains(scope, "")
    assert out.packages[0].sor_items[0].description == "Standpipe"


# -- count fidelity: a hole in the numbering is a dropped item ----------------------------------
def test_an_interior_hole_in_a_bill_is_found():
    scope = _pkg(["2.1", "2.2", "2.24", "2.25", "2.26"])
    assert sequence_gaps(scope) == {"2": list(range(3, 24))}


def test_a_complete_bill_reports_nothing():
    assert sequence_gaps(_pkg(["6.1", "6.2", "6.3", "6.4", "6.5", "6.6"])) == {}


def test_gaps_are_found_per_bill_not_across_the_whole_scope():
    scope = _pkg(["1.1", "1.3", "2.1", "2.2"])
    assert sequence_gaps(scope) == {"1": [2]}


def test_neither_end_of_a_bill_is_guessed():
    """A bill may legitimately start at 3, and its last item is unknowable from the inside.
    Inventing either end produces a warning nobody can act on, which is how a real one gets
    ignored."""
    assert sequence_gaps(_pkg(["3.3", "3.4", "3.5"])) == {}


def test_a_schedule_of_rates_package_produces_no_sequence_report():
    """`A1a(a)`, `E10(l)`, `BB7a` are not a numeric run and must not be treated as one."""
    assert sequence_gaps(_pkg(["A1a(a)", "E10(l)", "BB7a"])) == {}


def test_the_report_names_the_bill_the_count_and_the_refs():
    notes: list[str] = []
    report_sequence_gaps(_pkg(["2.1", "2.4"]), on_note=notes.append)
    assert len(notes) == 1
    assert "bill 2" in notes[0] and "2 item(s) are missing" in notes[0]
    assert "2.2, 2.3" in notes[0] and "INCOMPLETE" in notes[0]


def test_a_long_run_of_missing_items_is_summarised_not_dumped():
    notes: list[str] = []
    report_sequence_gaps(_pkg(["1.1", "1.30"]), on_note=notes.append)
    assert "and 16 more" in notes[0]


def test_an_implausibly_wide_span_is_not_reported_as_one_bill_of_holes():
    """A span far wider than any real bill is a different document's numbering leaking in, not
    forty dropped rows."""
    assert sequence_gaps(_pkg(["1.1", "1.400"])) == {}
