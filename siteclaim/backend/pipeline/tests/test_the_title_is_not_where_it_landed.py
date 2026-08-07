"""The document's kind was decided by which phrase pymupdf emitted first.

`_deterministic_doc_type` kept whichever `_TITLE_SIGNALS` match had the smallest `m.start()` — a
position in the extractor's LINEARISATION of page 1, which is not the page's printed order. Its own
docstring said "a document's own top-of-page title beats a later inline mention of another kind",
but `m.start()` does not measure "top of page".

The concrete failure: a Particular Specification whose page 1 both carries the title
"Particular Specification" and quotes, wrapped across two lines,

    1.01 Measurement shall be in accordance with the Standard
    Method of Measurement for Civil Engineering Works.

The wrap puts "Method of Measurement" at a line start, so the line-anchored pattern matched it, and
the DocType flipped with the extraction order. `doc_index._kind_for` reads that DocType, so this is
the delivery mechanism for PS 1 taking SMM 1's slot — the same defect through a third door.

Class 3, third occurrence: `_is_amendment_lead_in` and `_is_furniture_title` were both rewritten to
stop ranking by position, and this is the same rule applied here — **skip what is not a title;
never rank what is.** A title OPENS something, so the line above it has finished. Where two
candidates survive, precedence is the DECLARED order of `_TITLE_SIGNALS`, which is fixed and
reviewable, rather than whichever the extractor happened to emit first.
"""

import pytest

from pipeline.stage_01_ingest.classify import _deterministic_doc_type
from schemas.models import DocType

# No filename token, so the title is what decides — that is the path under test.
PS_FILE = "S/PS/PS1/particular-spec-part-one.pdf"

TITLE_FIRST = (
    "[page 1]\n"
    "Particular Specification\n"
    "SECTION 1\n"
    "GENERAL\n"
    "1.01 Measurement shall be in accordance with the Standard\n"
    "Method of Measurement for Civil Engineering Works.\n"
)
QUOTE_FIRST = (
    "[page 1]\n"
    "SECTION 1\n"
    "1.01 Measurement shall be in accordance with the Standard\n"
    "Method of Measurement for Civil Engineering Works.\n"
    "Particular Specification\n"
    "GENERAL\n"
)


# -- the same page, either order ---------------------------------------------------------------
@pytest.mark.parametrize("text", [TITLE_FIRST, QUOTE_FIRST], ids=["title-first", "quote-first"])
def test_the_kind_does_not_depend_on_the_extraction_order(text):
    assert _deterministic_doc_type(PS_FILE, text) == (DocType.PARTICULAR_SPECIFICATION, "title")


def test_a_wrapped_sentence_is_not_a_title():
    """The mechanism, isolated: `Method of Measurement…` continues `…with the Standard`, whatever
    order it was extracted in."""
    wrapped = ("[page 1]\n"
               "1.01 Measurement shall be in accordance with the Standard\n"
               "Method of Measurement for Civil Engineering Works.\n")
    assert _deterministic_doc_type("x.pdf", wrapped) == (None, "")


def test_a_line_after_a_finished_sentence_can_be_a_title():
    """The other half of the rule — otherwise nothing below prose would ever be a title, and a
    cover page with a paragraph above the title would classify as nothing."""
    text = ("[page 1]\n"
            "This document forms part of the tender.\n"
            "METHOD OF MEASUREMENT FOR CIVIL ENGINEERING WORKS\n")
    assert _deterministic_doc_type("x.pdf", text) == (DocType.METHOD_OF_MEASUREMENT, "title")


# -- the titles that must keep working ----------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("[page 1]\nMETHOD OF MEASUREMENT FOR CIVIL ENGINEERING WORKS\nSECTION 2\n",
     DocType.METHOD_OF_MEASUREMENT),
    ("[page 1]\nSCHEDULE OF RATES\nSECTION A : PRELIMINARIES\n", DocType.SCHEDULE_OF_RATES),
    ("[page 1]\nTHE SCHEDULE OF RATES\n", DocType.SCHEDULE_OF_RATES),
    ("[page 1]\nGENERAL SPECIFICATION\nSECTION 7\n", DocType.PARTICULAR_SPECIFICATION),
    ("[page 1]\nAPPENDIX 1.12\n", DocType.GENERAL),
    ("[page 1]\nTENDER ADDENDUM NO. 1\n", DocType.TENDER_ADDENDUM),
])
def test_a_real_title_page_still_classifies(text, expected):
    assert _deterministic_doc_type("no-token.pdf", text) == (expected, "title")


def test_a_title_opening_the_document_with_no_page_marker_still_counts():
    assert _deterministic_doc_type("x.pdf", "SCHEDULE OF RATES\nSECTION A\n") == (
        DocType.SCHEDULE_OF_RATES, "title")


def test_a_title_under_a_file_marker_still_counts():
    """`=== file.pdf ===` is an extractor boundary, exactly like `[page 1]` — not context."""
    text = "=== I-ND_2025_04_BQ-0.pdf ===\n[page 1]\nSCHEDULE OF RATES\n"
    assert _deterministic_doc_type("x.pdf", text) == (DocType.SCHEDULE_OF_RATES, "title")


def test_a_title_under_a_blank_line_still_counts():
    assert _deterministic_doc_type("x.pdf", "some heading\n\nSCHEDULE OF RATES\n") == (
        DocType.SCHEDULE_OF_RATES, "title")


@pytest.mark.parametrize("above", [
    "CONTRACT NO. ND/2025/04",
    "SECTION 1",
    "Particular Specification",
    "GROUND INVESTIGATION WORKS",
])
def test_a_heading_above_a_title_does_not_block_it(above):
    """The near-miss this rule has to survive: a real cover page is written in HEADINGS, none of
    which ends in a full stop. Requiring terminal punctuation alone would reject every one of
    them — so the test is whether the line above is prose, not whether it is punctuated."""
    assert _deterministic_doc_type("x.pdf", f"[page 1]\n{above}\nSCHEDULE OF RATES\n") == (
        DocType.SCHEDULE_OF_RATES, "title")


# -- the filename still outranks the title ---------------------------------------------------------
def test_a_filename_token_still_decides_before_any_title_is_read():
    """An MM's page 1 mentions "Schedule of Rates" repeatedly; its `-MM-` token must win. That
    ordering is the existing doctrine and this change does not touch it."""
    assert _deterministic_doc_type("GP&PP/I-ND_2025_04-MM-S02-0.pdf", TITLE_FIRST) == (
        DocType.METHOD_OF_MEASUREMENT, "filename")


def test_a_page_with_no_title_at_all_answers_none():
    """`(None, "")` hands the question on rather than guessing — the AI classifier runs next."""
    assert _deterministic_doc_type("x.pdf", "just some prose about rates and measurement\n") == (None, "")


def test_an_inline_mention_is_still_not_a_title():
    """The line-start anchor's original job, unchanged: a phrase mid-sentence is not a title."""
    assert _deterministic_doc_type("x.pdf", "[page 1]\nWe refer to the Schedule of Rates herein.\n") == (
        None, "")


# -- precedence is declared, not positional ----------------------------------------------------------
def test_two_surviving_titles_resolve_by_the_declared_order():
    """When a page genuinely opens with two title-shaped lines, the answer must be the same every
    time. `_TITLE_SIGNALS` order is the rule — a list a reviewer can read — and Schedule of Rates
    is first in it."""
    both = "[page 1]\nSCHEDULE OF RATES\n\nPARTICULAR SPECIFICATION\n"
    reversed_ = "[page 1]\nPARTICULAR SPECIFICATION\n\nSCHEDULE OF RATES\n"

    assert _deterministic_doc_type("x.pdf", both) == _deterministic_doc_type("x.pdf", reversed_)
    assert _deterministic_doc_type("x.pdf", both)[0] == DocType.SCHEDULE_OF_RATES
