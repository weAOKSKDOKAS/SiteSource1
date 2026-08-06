"""A page can name its section twice. The header block is not the heading.

`GP&PP/…-SMM_S01-0.pdf` page 1, verbatim from the pack:

    Contract No. ND/2025/04
    Ground Investigation Works for Development of San Tin
    Technopole (Phase 2)
    Particular Preambles
    Section 1                      <- the HEADER BLOCK, naming the section as metadata
     AECOM-AtkinsRealis JV
    - 1a -
    SECTION 1                      <- the document's OWN heading
    PRELIMINARIES
    Add the following after paragraph 1.01 :

The first declaration is followed by the consultant name and a page marker, so the reader took its
"title" from the running header — `AECOM-AtkinsRealis JV` in the printed order, `Technopole
(Phase 2)` in the order the pack actually linearised. Either way the gate showed the operator
"Method of Measurement Section 1 — Technopole (Phase 2)". S28 survived only because its page is laid
out differently, which is precisely why position is not a rule.

THE RULE, and it is not "the second one wins": **a declaration whose title is page furniture is not
a declaration**, and the scan moves on — the same shape as the amendment-lead-in skip beside it, and
order-independent for the same reason. Where two candidates both survive, the first still wins, but
neither is furniture so there is nothing to prefer between.

Furniture has two sources and both are needed:

* ``running_lines`` — what repeats on EVERY page. General, no list, and the same signal
  `ingest.running_furniture` uses on a bill: content cannot tell a running header from a heading,
  so repetition is the only evidence there is.
* ``_TITLE_FURNITURE`` / ``_TITLE_ORG_SUFFIX`` — the named forms, which still work on a one-page
  document where there is no repetition to observe.

Nothing was broken by this in dispatch — Bill→SMM matches on the number — but a wrong title is what
the operator reads, and it is the specification side of any future title match.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    _is_furniture_title,
    running_lines,
    section_declaration,
)

HEADER = ("Contract No. ND/2025/04\n"
          "Ground Investigation Works for Development of San Tin \n"
          "Technopole (Phase 2) \n"
          "Particular Preambles \n"
          "Section 1 \n"
          " AECOM-AtkinsRealis JV \n")
# Page 1, exactly as the pack prints it.
S01_PAGE1 = HEADER + ("- 1a - \n"
                      "SECTION 1 \n"
                      "PRELIMINARIES \n"
                      "Add the following after paragraph 1.01 :\n")
# The same page as the extractor actually linearised it — the project-title tail beside the
# declaration, which is what produced "Technopole (Phase 2)".
ALT_HEADER = ("Contract No. ND/2025/04\nParticular Preambles \nSection 1 \n"
              "Technopole (Phase 2) \nGround Investigation Works for Development of San Tin \n"
              " AECOM-AtkinsRealis JV \n")
S01_ALT = ALT_HEADER + "- 1a - \nSECTION 1 \nPRELIMINARIES \n"

S01_PAGES = [S01_PAGE1] + [HEADER + f"- {n} - \n1.0{n}  A preamble clause\n" for n in range(2, 8)]
ALT_PAGES = [S01_ALT] + [ALT_HEADER + f"- {n} - \n1.0{n}  A preamble clause\n" for n in range(2, 8)]

S28_HEADER = "Particular Preambles\nSection 28\n"
S28_PAGE1 = ("Add the following new section after Section 27 :\n\nSECTION 28\n\n"
             "SITE SAFETY MANAGEMENT\n\n") + S28_HEADER
S28_PAGES = [S28_PAGE1, S28_HEADER + "28.01  A clause\n"]


# -- the exact page ---------------------------------------------------------------------------------
def test_the_real_s01_page_yields_preliminaries():
    assert section_declaration(S01_PAGE1, running_lines(S01_PAGES)) == ("1", "PRELIMINARIES")


def test_the_other_linearisation_of_the_same_page_yields_the_same_thing():
    """Position cannot be the rule: the two orders put different furniture beside the declaration,
    and both used to win."""
    assert section_declaration(S01_ALT, running_lines(ALT_PAGES)) == ("1", "PRELIMINARIES")


def test_s28_still_reads_its_own_title():
    assert section_declaration(S28_PAGE1, running_lines(S28_PAGES)) == ("28", "SITE SAFETY MANAGEMENT")


def test_the_wrong_titles_are_the_ones_now_refused():
    """Named, so the fix cannot be mistaken for a coincidence."""
    _n, title = section_declaration(S01_PAGE1, running_lines(S01_PAGES))
    assert title not in ("Technopole (Phase 2)", "AECOM-AtkinsRealis JV", "Particular Preambles")


# -- what repeats is furniture ------------------------------------------------------------------------
def test_running_lines_finds_the_header_block_and_nothing_else():
    common = running_lines(S01_PAGES)

    assert {"Contract No. ND/2025/04", "Particular Preambles", "AECOM-AtkinsRealis JV",
            "Technopole (Phase 2)", "Section 1"} <= common
    assert "PRELIMINARIES" not in common, "the real title is on page 1 only"
    assert "- 1a -" not in common, "the page marker changes every page"


def test_a_line_on_only_some_pages_is_not_furniture():
    """The risk the rule must not take, the same one phase 1 pinned: a heading spans its own
    section's pages, not the whole document."""
    pages = ["HEAD\nSECTION 1\nPRELIMINARIES\n", "HEAD\nPRELIMINARIES\n", "HEAD\nOther\n"]
    assert "PRELIMINARIES" not in running_lines(pages)
    assert running_lines(pages) == frozenset({"HEAD"})


def test_a_single_readable_page_has_no_measurable_furniture():
    assert running_lines([S01_PAGE1]) == frozenset()
    assert running_lines([S01_PAGE1, "", "   \n"]) == frozenset(), "blank pages discriminate nothing"


def test_the_named_forms_are_the_backstop_where_repetition_cannot_be_observed():
    """A one-page document has no repetition, and the consultant line still must not be a title."""
    assert section_declaration(S01_PAGE1) == ("1", "PRELIMINARIES")


# -- which forms are rejected, and which are emphatically not -------------------------------------------
@pytest.mark.parametrize("title", [
    "Particular Preambles",          # the document-type banner, like `Particular Specification`
    "General Preambles",
    "Particular Specification",
    "Contract No. ND/2025/04",
    "AECOM-AtkinsRealis JV",         # the consultant, by company FORM not by name
    "Mott MacDonald Hong Kong Ltd",
    "Binnies & Partners",
    "Ove Arup Consulting Engineers",
    "Table of Contents",
])
def test_these_are_page_furniture(title):
    assert _is_furniture_title(title) is True


@pytest.mark.parametrize("title", [
    "PRELIMINARIES",
    "SITE SAFETY MANAGEMENT",
    "GEOTECHNICAL WORKS",
    "Environmental Ground Investigation",
    "Preservation and Protection of Trees",
    "Management of Subcontractors",
    "Site Clearance",
    "General",                       # PS 1's real title — a short one, and not furniture
])
def test_these_are_titles(title):
    assert _is_furniture_title(title) is False


def test_the_project_title_is_rejected_by_repetition_not_by_a_word_list():
    """"Technopole (Phase 2)" is prose with plenty of letters — indistinguishable from a heading by
    content, which is the whole argument for using repetition. No list would have caught it."""
    assert _is_furniture_title("Technopole (Phase 2)") is False
    assert _is_furniture_title("Technopole (Phase 2)", running_lines(ALT_PAGES)) is True


# -- the continuation reader stops at furniture too --------------------------------------------------------
def test_a_wrapped_title_is_not_continued_into_the_running_header():
    """`section_declaration` reads a title past a line break. It must not read it into the header
    block underneath."""
    pages = ["SECTION 26\nPreservation and\nAECOM-AtkinsRealis JV\n",
             "AECOM-AtkinsRealis JV\n26.01 clause\n"]
    assert section_declaration(pages[0], running_lines(pages)) == ("26", "Preservation and")


def test_a_genuine_wrapped_title_still_joins():
    pages = ["SECTION 26\nPreservation and\nProtection of Trees\nAECOM-AtkinsRealis JV\n",
             "AECOM-AtkinsRealis JV\n26.01 clause\n"]
    assert section_declaration(pages[0], running_lines(pages))[1] == \
        "Preservation and Protection of Trees"


# -- end to end -------------------------------------------------------------------------------------------
def test_through_build_doc_entry_on_real_pdf_bytes():
    """The furniture is measured across the WHOLE document, which only `build_doc_entry` can do."""
    fitz = pytest.importorskip("fitz")
    from pipeline.stage_01_ingest.doc_index import build_doc_entry
    from schemas.models import DocType

    doc = fitz.open()
    for text in S01_PAGES:
        page = doc.new_page()
        y = 60
        for line in text.splitlines():
            page.insert_text((40, y), line, fontname="cour", fontsize=8)
            y += 12
    data = doc.tobytes()
    doc.close()

    entry = build_doc_entry("GP&PP/I-ND_2025_04-SMM_S01-0.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert entry.kind == "method_of_measurement"
    assert entry.spec_section_number == "1"
    assert entry.spec_section_title == "PRELIMINARIES"
