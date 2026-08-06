"""The bill header carries no title, so the only line that matched was the collection footer.

Driven on the REAL `BQ/I-ND_2025_04_BQ-0.pdf` page shapes — 26 pages, title-less `Bill No. n`
headers, a `Bill No. n - Total Carried to Grand Summary` footer closing each bill, and a
`SECTION n : TITLE` line at the foot of the pages it governs.

`_BILL_SECTION_HEADER` required a title (`(.+?)\\s*$`). The real header has none:

    'Bill No. 2'                                    -> no match
    'Bill No. 2 - Total Carried to Grand Summary '  -> MATCH

So a bill "opened" at its own END, and the next `SECTION n` found belonged to the bill after it.
Bill 6 got SMM 24, Bill 7 got 29, Bill 8 got 28, and Bill 9 was dropped entirely — Builders Work
received no SMM 28. Bills 2 to 6 looked right only because they all name SMM 2.

**Why a fixture could not catch it, and why this file exists.** The sibling
`test_bill_measurement_rules.py` models a TITLED header (`Bill No. 1 - General and Preliminaries`),
which is a real shape for other issuers and matches the pattern either way. When that fixture was
first written title-less and the regex rejected it, the fixture was changed — the regex was telling
the truth about production and was overruled. Same class as `_FILENAME_SECTION` reading whole
archive paths while every unit test passed a basename. **When a fixture has to be bent to fit the
code, the code is the thing that is wrong.**

Fixtures, not the real pack: these are that bill's page SHAPE, written by hand from the per-page
evidence read out of it.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    _spans,
    _sor_section_markers,
    bill_header_number,
    bill_mm_sections,
)
from pipeline.stage_01_ingest.ingest import _section_titles

HEADER = "Bill No. {b}"
FOOTER = "Bill No. {b} - Total Carried to Grand Summary "


def _page(bill, sections=(), *, footer=False):
    """One BQ page: the running `Bill No. n`, items, the measurement section at the foot, and — on
    a bill's last page — the collection line."""
    lines = [HEADER.format(b=bill), "  1.1  Some item                            1  nr"]
    lines += [f"SECTION {s} : TITLE" for s in sections]
    if footer:
        lines.append(FOOTER.format(b=bill))
    return "\n".join(lines) + "\n"


def _bq(page_7_sections):
    """The 26-page bill. ``page_7_sections`` is the one open question — see the tests below."""
    pages = ["", ""]                                             # 1-2: cover, contents
    pages += [_page(1, ["1"])]                                   # 3
    pages += [_page(1) for _ in range(3)]                        # 4-6
    pages += [_page(1, page_7_sections)]                         # 7
    pages += [_page(1, footer=True)]                             # 8
    for bill, span in [(2, 4), (3, 2), (4, 2), (5, 2), (6, 2)]:  # 9-20, all naming SMM 2
        pages += [_page(bill, ["2"])] + [_page(bill) for _ in range(span - 2)]
        pages += [_page(bill, footer=True)]
    pages += [_page(7, ["24"]), _page(7, footer=True)]           # 21-22
    pages += [_page(8, ["29"]), _page(8, footer=True)]           # 23-24
    pages += [_page(9, ["28"]), _page(9, footer=True)]           # 25-26
    return pages


BQ = _bq(["3"])          # page 7 with the second measurement header only
assert len(BQ) == 26     # the real page count, so the shape is not quietly wrong


# -- the header is not the footer ------------------------------------------------------------------
@pytest.mark.parametrize("line,opens", [
    ("Bill No. 2", "2"),                                          # the real header
    ("Bill No. 9", "9"),
    ("BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS", "2"),        # another issuer's titled header
    ("Bill No. 1 - General and Preliminaries", "1"),
    ("Bill No. 2 - Total Carried to Grand Summary ", None),       # the footer, and it opens nothing
    ("Bill No. 9 - Total Carried to Grand Summary", None),
    ("Bill No. 3 - Collection", None),
    ("Bill No. 3 Carried to Summary", None),
    ("Bill No. 4 - Brought Forward", None),
])
def test_what_opens_a_bill_and_what_closes_one(line, opens):
    assert bill_header_number(line) == opens


# -- the mapping, bill by bill ----------------------------------------------------------------------
def test_bills_two_to_nine_resolve_exactly_against_the_real_page_shapes():
    got = bill_mm_sections(BQ)
    assert {b: got.get(b) for b in ("2", "3", "4", "5", "6", "7", "8", "9")} == {
        "2": ["2"], "3": ["2"], "4": ["2"], "5": ["2"],
        "6": ["2"], "7": ["24"], "8": ["29"], "9": ["28"]}


def test_bill_one_is_no_longer_absent_and_carries_both_of_its_sections():
    assert bill_mm_sections(BQ)["1"] == ["1", "3"]


def test_bill_nine_is_no_longer_dropped_so_builders_work_gets_smm_28():
    """The concrete harm: Bill 9 is Site Safety Management and it fell off the map entirely."""
    got = bill_mm_sections(BQ)
    assert "9" in got and got["9"] == ["28"]


@pytest.mark.parametrize("bill,wrong", [("6", "24"), ("7", "29"), ("8", "28")])
def test_no_bill_carries_the_next_bills_section(bill, wrong):
    """The off-by-one, per bill. Each of these previously took its successor's SMM section."""
    assert wrong not in bill_mm_sections(BQ)[bill]


def test_the_collection_footer_does_not_open_a_bill_mid_document():
    """The mechanism, isolated: with the footer opening Bill 2, the `SECTION 2` line on the NEXT
    page would have been attributed to it a page too early — and so on down the document."""
    pages = [_page(1, ["1"], footer=True), _page(2, ["2"])]
    assert bill_mm_sections(pages) == {"1": ["1"], "2": ["2"]}


# -- page 7: the one thing that cannot be settled from here -------------------------------------------
def test_a_second_measurement_header_on_a_page_is_carried():
    """`SECTION 24` at line start is a header like any other, and Bill 1 carries it."""
    assert bill_mm_sections(_bq(["3", "24"]))["1"] == ["1", "3", "24"]


def test_a_cross_reference_inside_prose_is_not_carried():
    """`_BILL_MM_REFERENCE` is line-anchored, so a reference in a sentence never was a candidate."""
    pages = _bq(["3"])
    pages[6] += "Trees are measured under SECTION 24 : LANDSCAPE SOFTWORKS of the SMM.\n"
    assert bill_mm_sections(pages)["1"] == ["1", "3"]


def test_the_two_readings_of_page_seven_are_pinned_so_either_can_be_checked():
    """UNRESOLVED, and deliberately not guessed.

    The real page 7 carries both `3` and `24`. Which is a measurement header and which is a
    cross-reference cannot be decided from outside the pack — it turns on whether the `24` line
    STARTS with `SECTION`, and the per-page evidence available records the numbers, not their
    position. Both readings are pinned here so that whichever it is, the behaviour is known:

    * at line start  -> Bill 1 carries 1, 3, 24 (one extra measurement rulebook, flagged on the gate)
    * inside prose   -> Bill 1 carries 1, 3     (the stated truth)

    No rule is invented to force the second. Over-inclusion sends a firm one rulebook it did not
    need and says why on the gate; omission has a firm pricing against rules nobody enclosed. Under
    genuine uncertainty that is the direction to fail in.
    """
    assert bill_mm_sections(_bq(["3", "24"]))["1"] == ["1", "3", "24"]
    assert bill_mm_sections(_bq(["3"]))["1"] == ["1", "3"]


# -- the same regex, the other two things it broke ------------------------------------------------------
def test_a_bill_is_never_titled_total_carried_to_grand_summary():
    """`_section_titles` fed that string to `spec_match` as the bill's heading — the thing a
    specification is matched against."""
    titles = _section_titles("\n".join(BQ))
    assert not any("Carried" in t for t in titles.values()), titles


def test_a_bill_never_takes_the_title_of_the_smm_section_it_happens_to_share_a_number_with():
    """Bill 3 is *Laboratory Testing* and names SMM 3, *Site Clearance*. With a title-less bill
    header there was nothing to override the cross-reference, so bill 3 was titled "Site Clearance"
    — and `spec_match` would have proposed a site-clearance specification for a testing package.
    """
    text = ("Bill No. 1\nSECTION 1 : PRELIMINARIES\n"
            "Bill No. 3\nSECTION 3 : SITE CLEARANCE\n"
            "Bill No. 24\nSECTION 24 : LANDSCAPE SOFTWORKS\n")
    titles = _section_titles(text)

    assert titles.get("1") in (None, "") and titles.get("3") in (None, "")
    assert titles.get("24") in (None, ""), "a number a bill has claimed is the bill's"


def test_a_titled_header_still_gives_its_title():
    """The optional group must not cost the issuers who do title their bills."""
    titles = _section_titles("Bill No. 1 - General and Preliminaries\n"
                             "BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS\n"
                             "Bill No. 2 - Total Carried to Grand Summary\n")
    assert titles["1"] == "General and Preliminaries"
    assert titles["2"] == "GROUND INVESTIGATION FIELDWORKS", "the header wins, not the footer"


def test_a_bills_page_span_starts_at_its_header_not_at_its_collection_line():
    """The third consequence: `sor_section_pages` drives the priced-return slice, so a span that
    began at the summary page sliced the wrong pages for the firm to price."""
    spans = _spans(_sor_section_markers(BQ), len(BQ))

    assert spans["1"][0] == 2, "Bill 1 opens on page 3 (0-based 2)"
    assert spans["2"][0] == 8, "Bill 2 opens on page 9 (0-based 8)"
    assert spans["9"][0] == 24, "Bill 9 opens on page 25 (0-based 24)"
    assert all(spans[b] for b in "123456789"), "every bill has a span"
