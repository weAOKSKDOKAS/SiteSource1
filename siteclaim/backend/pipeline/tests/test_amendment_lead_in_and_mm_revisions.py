"""An amendment lead-in is not a declaration, and the Method of Measurement has revisions too.

DEFECT 1, from the live `doc_index.json` — one record contradicting itself:

    "filename": "GP&PP/I-ND_2025_04-SMM_S28-0.pdf"
    "spec_section_number": "27"          <- wrong
    "spec_section_title": "SECTION 28"

Page 1 of that document, verbatim:

    Particular Preambles
    Section 28

    Add the following new section after Section 27 :

    SECTION 28

    SITE SAFETY MANAGEMENT

`_SECTION_DECL` matched the LEAD-IN — "…after Section 27 :" — whose trailing colon and following
line made it look like a declaration with a title. Bill 9 then correctly asked for measurement
section 28, found none, and the gate reported it missing while the document sat in the pack under
the wrong number: a true statement about a false index.

**Extraction order decides which match is leftmost**, and extraction order is not the document's
order — pymupdf sorts by position. Printed order yields 28 with a nonsense title; the order the pack
actually produced yields 27. Both are reproduced below, and both must now give 28.

DEFECT 2: the pack ships `TA #1/GP&PP/…-SMM_S02-1.pdf` beside the `-0` and both were enclosed with
identical reasons. `_ps_revisions` held the whole precedence rule and only the PS branch consulted
it — the same "one contest, two doors" already fixed once for a PS reissue entering through the
clarification branch. The rule is now `_revision_contest`, called for both populations, so there is
no second copy to drift.

Fixtures, not the real pack, except the S28 page-1 text, which is verbatim.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    section_declaration,
    section_number_disagreements,
)
from pipeline.stage_03_dispatch.relevant_docs import (
    SUPERSEDED_BY_ADDENDUM,
    _revision_contest,
    resolve_section_plan,
)
from schemas.models import SorItem

# The real page 1, as printed.
S28_PRINTED = ("Particular Preambles\nSection 28\n\n"
               "Add the following new section after Section 27 :\n\n"
               "SECTION 28\n\nSITE SAFETY MANAGEMENT\n")
# The same page as the extractor actually linearised it — which is what the live index recorded.
S28_EXTRACTED = ("Add the following new section after Section 27 :\n\n"
                 "SECTION 28\n\nSITE SAFETY MANAGEMENT\n\n"
                 "Particular Preambles\nSection 28\n")


# -- DEFECT 1: a lead-in names a position, a declaration names the document -------------------------
@pytest.mark.parametrize("page1", [S28_PRINTED, S28_EXTRACTED])
def test_the_real_s28_page_resolves_to_28_whatever_order_it_extracts_in(page1):
    assert section_declaration(page1) == ("28", "SITE SAFETY MANAGEMENT")


def test_the_live_index_recorded_27_and_that_is_the_shape_now_refused():
    """The exact wrong record, named so the fix cannot be mistaken for a coincidence."""
    number, title = section_declaration(S28_EXTRACTED)
    assert (number, title) != ("27", "SECTION 28")
    assert number == "28"


@pytest.mark.parametrize("page1,expected", [
    ("Add the following new section after Section 27 :\n\nSECTION 28\n\nSITE SAFETY MANAGEMENT\n",
     ("28", "SITE SAFETY MANAGEMENT")),
    ("Delete Section 12 and substitute in lieu of it the following :\n\nSECTION 12\n\nPILING\n",
     ("12", "PILING")),
    ("Section 7 is deleted and replaced by the following :\n\nSECTION 7\n\nGEOTECHNICAL WORKS\n",
     ("7", "GEOTECHNICAL WORKS")),
    ("Add the following clauses following Section 30 :\n\nSECTION 31\n\nLABORATORY TESTING\n",
     ("31", "LABORATORY TESTING")),
    ("Insert after Section 3 the following :\n\nSECTION 4\n\nSITE CLEARANCE\n",
     ("4", "SITE CLEARANCE")),
])
def test_every_lead_in_form_this_issuer_uses_is_skipped(page1, expected):
    assert section_declaration(page1) == expected


def test_skipping_a_lead_in_does_not_swallow_the_declaration_inside_it():
    """The subtle half. A lead-in match CONSUMES the next line as its "title" — `…after Section 27
    :\\n\\nSECTION 28` — so resuming after the whole match would skip past the very declaration
    being looked for. The scan resumes just past the NUMBER instead."""
    assert section_declaration("Add the following new section after Section 27 :\n\nSECTION 28\n"
                               "\nSITE SAFETY MANAGEMENT\n")[0] == "28"


@pytest.mark.parametrize("page1,expected", [
    ("SECTION 7 – GEOTECHNICAL WORKS\n7.01  General\n", ("7", "GEOTECHNICAL WORKS")),
    ("SECTION 28\nEnvironmental Ground\nInvestigation\n", ("28", "Environmental Ground Investigation")),
    ("PARTICULAR SPECIFICATION\nSECTION 27\nConstruction Site Safety\n", ("27", "Construction Site Safety")),
])
def test_an_ordinary_declaration_reads_exactly_as_before(page1, expected):
    assert section_declaration(page1) == expected


def test_a_page_that_is_ONLY_a_lead_in_declares_nothing_rather_than_claiming_another_section():
    """The failure this prevents, in its purest form: a document whose page 1 says only "add this
    after Section 27" must not come back claiming to BE section 27."""
    assert section_declaration("Add the following new section after Section 27 :\n") == ("", "")


# -- the index-wide cross-check ----------------------------------------------------------------------
def _e(fn, kind="method_of_measurement", sec="", title=""):
    return DocIndexEntry(filename=fn, kind=kind, spec_section_number=sec, spec_section_title=title,
                         text_layer=True, page_count=8)


def test_the_cross_check_catches_the_s28_record():
    """Silent by construction: nothing anywhere compared the two sources of a document's identity."""
    bad = _e("GP&PP/I-ND_2025_04-SMM_S28-0.pdf", sec="27", title="SECTION 28")
    assert section_number_disagreements([bad]) == [
        ("GP&PP/I-ND_2025_04-SMM_S28-0.pdf", "27", "28")]


def test_a_correctly_indexed_pack_reports_nothing():
    pack = [_e(f"GP&PP/I-ND_2025_04-SMM_S{int(n):02d}-0.pdf", sec=n) for n in ("1", "2", "3", "24", "28", "29")]
    pack += [_e(f"S/PS/PS{n}/I-ND_2025_04-S_PS{n}-0.pdf", "particular_specification", n)
             for n in ("1", "27", "28")]
    assert section_number_disagreements(pack) == []


def test_an_appendix_is_not_a_false_positive():
    """An appendix's number is its PARENT'S — `PSA1.12` is section 1 — so comparing it against the
    filename's own digits would report every appendix in the pack."""
    app = _e("S/PS/PS1/I-ND_2025_04-S_PSA1.12-0.pdf", "appendix", "1")
    assert section_number_disagreements([app]) == []


def test_a_document_whose_page_one_declares_nothing_is_not_a_false_positive():
    """The REVERSE case, and why this is a cross-check and not a rule: PS28's page 1 declares
    nothing at all and the filename is its only evidence. The two agree, so nothing is reported."""
    assert section_number_disagreements([
        _e("S/PS/PS28/I-ND_2025_04-S_PS28-0.pdf", "particular_specification", "28")]) == []


# -- DEFECT 2: one contest, one rule ------------------------------------------------------------------
SMM2_0 = "GP&PP/I-ND_2025_04-SMM_S02-0.pdf"
SMM2_1 = "TA #1/GP&PP/I-ND_2025_04-SMM_S02-1.pdf"
BQ = DocIndexEntry(filename="BQ/I-ND_2025_04_BQ-0.pdf", kind="schedule_of_rates", text_layer=True,
                   page_count=26, bill_mm_sections={"2": ["2"]})
PACK = [BQ, _e(SMM2_0, sec="2"), _e(SMM2_1, sec="2")]


def _plan(*, index=None, clause_refs=()):
    return resolve_section_plan(
        package_key="ground_investigation:2", trade="ground_investigation", section_title="GI",
        section="2", sections=["2"],
        items=[SorItem(item_ref="2.1", description="Moving rigs", section="2",
                       clause_refs=list(clause_refs))],
        doc_index=list(PACK if index is None else index), sor_sheet_name="SoR.xlsx",
    )


def _docs(plan):
    return {a.source_doc for a in plan.attachments}


def test_only_the_operative_revision_of_a_measurement_section_is_enclosed():
    docs = _docs(_plan())
    assert SMM2_1 in docs and SMM2_0 not in docs


def test_the_gate_states_the_revision_and_its_evidence():
    att = next(a for a in _plan().attachments if a.source_doc == SMM2_1)
    assert "Rev 1" in att.reason and "superseding" in att.reason
    assert "the -0/-1 filename suffix" in att.reason
    assert SUPERSEDED_BY_ADDENDUM in att.flags


@pytest.mark.parametrize("reverse", [False, True])
def test_the_outcome_does_not_depend_on_index_order(reverse):
    index = list(reversed(PACK)) if reverse else list(PACK)
    docs = _docs(_plan(index=index))
    assert SMM2_1 in docs and SMM2_0 not in docs


def test_an_unrevised_measurement_section_is_still_enclosed_with_no_revision_note():
    """A `-0` with no reissue is the only version there is, and must not be dropped for it."""
    att = next(a for a in _plan(index=[BQ, _e(SMM2_0, sec="2")]).attachments
               if a.source_doc == SMM2_0)
    assert "Rev" not in att.reason and SUPERSEDED_BY_ADDENDUM not in att.flags


def test_the_revision_note_reaches_the_clause_sliced_path_too():
    """The MM branch has three exits — sliced, whole-not-located, and the bill-named whole. A
    revision note on only some of them would be worse than none."""
    sliced = _e(SMM2_1, sec="2")
    sliced = sliced.model_copy(update={"clause_index": {"PB 71": [1]}})
    plan = _plan(index=[BQ, _e(SMM2_0, sec="2"), sliced], clause_refs=["PB 71"])
    att = next(a for a in plan.attachments if a.source_doc == SMM2_1)

    assert att.mode == "sliced" and "Rev 1" in att.reason
    assert SMM2_0 not in _docs(plan)


def test_a_measurement_section_and_a_specification_section_never_contest_each_other():
    """One rule, two POPULATIONS. SMM 2 and PS 2 share a number and mean nothing to each other; a
    contest between them would supersede one on the strength of the other's revision."""
    ps2 = DocIndexEntry(filename="S/PS/PS2/I-ND_2025_04-S_PS2-1.pdf", kind="particular_specification",
                        spec_section_number="2", text_layer=True, page_count=18)
    superseded, revised, _contested = _revision_contest(
        [_e(SMM2_0, sec="2"), ps2], lambda e: e.kind == "method_of_measurement")

    assert superseded == set(), "the -0 is the only measurement revision present"
    assert revised == {} and ps2.filename not in superseded
