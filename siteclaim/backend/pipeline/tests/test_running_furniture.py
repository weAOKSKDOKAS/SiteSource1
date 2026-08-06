"""The bill's section heading survives the page break.

`heading_chains` lost it for every item after a section's first page. The mechanism is its own
rule — *"a heading closes every open heading at or right of its own column"* — fired by the running
page title, which a CEDD bill repeats at the LEFT MARGIN, shallower than the section header. So on
every new page the title closed `SECTION 2 - GROUND INVESTIGATION` and its subheading, and only
page-one items kept them:

    2.1 -> ['…San Tin Technopole (Phase 2)', 'SECTION 2 - GROUND INVESTIGATION', 'Ground Investigation Fieldworks']
    2.2 -> ['…San Tin Technopole (Phase 2)']
    2.3 -> ['…San Tin Technopole (Phase 2)']

This harms the product on its own terms, before any specification-matching work: in a bill an item's
full description IS its ancestor path, so every item past a section's first page carried page
furniture where its scope should be.

**Why repetition and not content.** Verified: the project title passes `_SKIP_LINE` (which catches
`[page N]`) and `_NOT_HEADING` (which catches bare numbers, units, `page N…`, carried-forward
footers) because it is prose with plenty of letters — indistinguishable from a real heading by
content. Repetition is the only signal available.

**Why "every page" and not "more than one".** The obvious rule would wrongly drop a genuine heading
continued over a page break. "Every page" cannot: a heading spans its own section's pages, not the
whole document. And a line that IS on every page discriminates nothing — every item would carry it —
so dropping it loses no information that separates one item from another.

Fixtures, not the real pack: this is that bill's page SHAPE, written by hand.
"""

import pytest

from pipeline.stage_01_ingest.ingest import heading_chains, running_furniture

TITLE = "Ground Investigation Works for Development of San Tin Technopole (Phase 2)"
COLS = "Item No.  Item Description  Quantity  Unit"


def _bill(pages: list[tuple[list[str], list[tuple[str, str]]]], *, title: str = TITLE) -> str:
    """The real pack's shape: a repeated LEFT-MARGIN title, a deeper section header, a deeper
    subheading, and items across page breaks."""
    out = ""
    for n, (headings, items) in enumerate(pages, start=1):
        out += f"[page {n}]\n{title}\n"
        for depth, text in enumerate(headings):
            out += " " * (5 + depth * 2) + text + "\n"
        out += "       " + COLS + "\n"
        for ref, desc in items:
            out += f"         {ref}    {desc}\n"
    return out


THREE_BREAKS = _bill([
    (["SECTION 2 - GROUND INVESTIGATION", "Ground Investigation Fieldworks"],
     [("2.1", "Mobilisation of drilling plant")]),
    ([], [("2.2", "Rotary drilling in soil")]),
    ([], [("2.3", "Rotary drilling in rock")]),
    ([], [("2.4", "Standpipe piezometer")]),
])


# -- the reproduction, now fixed --------------------------------------------------------------------
def test_every_item_carries_the_section_heading_across_three_page_breaks():
    chains = heading_chains(THREE_BREAKS)
    expected = ["SECTION 2 - GROUND INVESTIGATION", "Ground Investigation Fieldworks"]
    assert [chains[r] for r in ("2.1", "2.2", "2.3", "2.4")] == [expected] * 4


def test_the_page_furniture_is_out_of_the_chain_entirely():
    chains = heading_chains(THREE_BREAKS)
    for chain in chains.values():
        assert TITLE not in chain and COLS not in chain


def test_the_furniture_is_identified_by_repetition_not_by_content():
    assert running_furniture(THREE_BREAKS) == {TITLE, COLS}


# -- the risk the rule must not take ------------------------------------------------------------------
def test_a_heading_continued_over_a_page_break_is_kept():
    """The one thing "repeats across pages" would have got wrong.

    `Ground Investigation Fieldworks` runs across pages 1 and 2 of a four-page bill and must
    survive. It is not on every page, so it is not furniture.
    """
    text = _bill([
        (["SECTION 2 - GROUND INVESTIGATION", "Ground Investigation Fieldworks"],
         [("2.1", "Mobilisation")]),
        (["Ground Investigation Fieldworks"], [("2.2", "Rotary drilling in soil")]),
        (["Laboratory Testing"], [("2.3", "Triaxial test")]),
        ([], [("2.4", "Consolidation test")]),
    ])
    assert "Ground Investigation Fieldworks" not in running_furniture(text)
    assert heading_chains(text)["2.2"][-1] == "Ground Investigation Fieldworks"
    assert heading_chains(text)["2.3"][-1] == "Laboratory Testing"


def test_a_heading_on_literally_every_page_discriminates_nothing_so_dropping_it_is_safe():
    """The argument the rule rests on, made checkable.

    If a real heading were on every page, every item would carry it — so removing it separates no
    item from any other. The chains stay pairwise identical either way.
    """
    text = _bill([
        (["SECTION 2 - GROUND INVESTIGATION"], [("2.1", "Mobilisation")]),
        (["SECTION 2 - GROUND INVESTIGATION"], [("2.2", "Rotary drilling")]),
    ], title=TITLE)
    chains = heading_chains(text)
    assert chains["2.1"] == chains["2.2"], "no item is distinguished by a heading on every page"


def test_a_single_page_document_has_no_furniture():
    """Every line is on "every page" when there is one — and there is no break to lose a heading
    across, so the rule must not fire at all."""
    text = _bill([(["SECTION 2 - GROUND INVESTIGATION"], [("2.1", "Mobilisation")])])
    assert running_furniture(text) == set()
    # The title therefore stays in the chain, exactly as before this change — and, crucially,
    # nothing has closed the section heading, because there was no page break to close it at.
    assert heading_chains(text)["2.1"] == [TITLE, "SECTION 2 - GROUND INVESTIGATION", COLS]


def test_text_with_no_page_markers_is_untouched():
    """`doc_text` from a source that emits no `[page N]` markers must behave exactly as before."""
    text = ("LABORATORY TESTING\n"
            "    Instrument Installation\n"
            "        6.1     Standpipe        47    nr\n")
    assert running_furniture(text) == set()
    assert heading_chains(text)["6.1"] == ["LABORATORY TESTING", "Instrument Installation"]


# -- what the fix is FOR ------------------------------------------------------------------------------
def test_two_sections_of_one_bill_stay_distinguishable_after_the_break():
    """The whole point: the section heading is what tells one package's items from another's, and
    it is the title side of any specification match that follows."""
    text = _bill([
        (["SECTION 2 - GROUND INVESTIGATION"], [("2.1", "Mobilisation")]),
        ([], [("2.2", "Rotary drilling")]),
        (["SECTION 9 - BUILDERS WORK"], [("9.1", "Builders work in connection")]),
        ([], [("9.2", "Making good")]),
    ])
    chains = heading_chains(text)
    assert chains["2.2"] == ["SECTION 2 - GROUND INVESTIGATION"]
    assert chains["9.2"] == ["SECTION 9 - BUILDERS WORK"]
    assert chains["2.2"] != chains["9.2"]


@pytest.mark.parametrize("ref", ["2.1", "2.2", "2.3", "2.4"])
def test_no_item_is_left_with_furniture_as_its_only_context(ref):
    """The live symptom, per item: a chain of page furniture is a description that says nothing."""
    chain = heading_chains(THREE_BREAKS)[ref]
    assert chain and chain[0].startswith("SECTION 2")
