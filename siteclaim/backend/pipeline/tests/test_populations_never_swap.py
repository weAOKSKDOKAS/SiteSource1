"""A document enclosed as the Method of Measurement must BE one.

THE DEFECT, from the live pack. Builders Work enclosed

    TA #1/S/PS/PS1/…-S_PS1-1.pdf   "Method of Measurement Section 1 …  (101 pages)"

— the Particular Specification, filed in `S/PS/PS1/`, labelled as the measurement rules. And
`GP&PP/I-ND_2025_04-SMM_S01-0.pdf`, the real SMM section 1, reached no enquiry at all.

THE CAUSE. `_METHOD_OF_MEASUREMENT` matches the full title "Standard Method of Measurement"
ANYWHERE in page 1, and its comment claimed to be narrow enough that "a PS that merely CITES the
method of measurement in its preamble says 'Method of Measurement' without 'Standard'". PS 1 is
*General* — 101 pages of general preliminaries — and its clause 1.01 quotes the full title. So the
claim was wrong about exactly one document, and it was the one that mattered.

THE SECOND-ORDER EFFECT, worse than the missing label. Misclassified, PS1-1 joined the MM population
carrying section number 1 and revision 1 — so `_revision_contest` had it SUPERSEDE the genuine
`SMM_S01-0.pdf`. The real measurement section was not merely skipped; it was actively set aside as
an earlier revision of a document it has nothing to do with.

WHY THE EXISTING GUARD DID NOT COVER IT.
`test_a_measurement_section_and_a_specification_section_never_contest_each_other` asserts the
contest is scoped by `kind`, and that assertion still holds. It tests the contest, taking the kinds
as given. The defect was upstream of it: PS 1 *was* a `method_of_measurement` as far as the index
was concerned, so from the contest's point of view there was only ever one population. A guard on a
downstream rule cannot catch a wrong input to it — hence `kind_disagreements`, which compares the
population the index recorded against the population the filename names.

Fixtures, not the real pack: these are that pack's PATH shapes and a page-1 preamble of the form
PS 1 carries.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    _kind_for,
    kind_disagreements,
    section_number_disagreements,
)
from pipeline.stage_03_dispatch.relevant_docs import _revision_contest, resolve_section_plan
from schemas.models import DocType, SorItem

PS1_1 = "TA #1/S/PS/PS1/I-ND_2025_04-S_PS1-1.pdf"
PS1_0 = "S/PS/PS1/I-ND_2025_04-S_PS1-0.pdf"
SMM1 = "GP&PP/I-ND_2025_04-SMM_S01-0.pdf"
SMM3 = "GP&PP/I-ND_2025_04-SMM_S03-0.pdf"
SMM28 = "GP&PP/I-ND_2025_04-SMM_S28-0.pdf"
PS27 = "S/PS/PS27/I-ND_2025_04-S_PS27-0.pdf"

# PS 1's page 1, in the form that caused it: a general section quoting the SMM by its full title.
PS1_PAGE1 = ("PARTICULAR SPECIFICATION\nSECTION 1\nGENERAL\n\n"
             "1.01  Measurement shall be in accordance with the Standard Method of Measurement.\n")


# -- classification -------------------------------------------------------------------------------
def test_a_specification_that_quotes_the_smm_by_name_is_still_a_specification():
    """The reproduction. A phrase inside a document is weaker evidence than the name the issuer
    gave it."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, PS1_PAGE1, PS1_1) == "particular_specification"
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, PS1_PAGE1, PS1_0) == "particular_specification"


@pytest.mark.parametrize("path", [SMM1, SMM3, SMM28, "GP&PP/I-ND_2025_04-SMM_S24-0.pdf"])
def test_the_real_measurement_documents_are_untouched(path):
    """The guard must not cost the branch it protects: an SMM filename names no PS or GS section,
    so it never trips."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, "", path) == "method_of_measurement"


def test_a_measurement_document_named_otherwise_is_still_found_from_page_one():
    """The page-1 route survives for a file whose name identifies nothing — which is what it is
    for."""
    assert _kind_for(DocType.GENERAL, "Standard Method of Measurement\nPreambles\n",
                     "GP&PP/Particular_Preambles-0.pdf") == "method_of_measurement"


def test_a_general_specification_is_not_blocked_by_its_own_name():
    """`names_ps`, not `names_a_section`: a GS file legitimately names a GS section, and the MM
    branch's guard would have blocked the very branch this is."""
    assert _kind_for(DocType.GENERAL, "General Specification\nfor Civil Engineering Works\n",
                     "S/GS/I-ND_2025_04-S_GS7-0.pdf") == "general_specification"


def test_an_appendix_that_quotes_the_smm_is_still_an_appendix():
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, PS1_PAGE1,
                     "S/PS/PS1/I-ND_2025_04-S_PSA1.12-0.pdf") == "appendix"


# -- the contest the misclassification poisoned -------------------------------------------------------
def _e(fn, kind, sec, pages=8):
    return DocIndexEntry(filename=fn, kind=kind, spec_section_number=sec, text_layer=True,
                         page_count=pages)


def test_the_specification_no_longer_supersedes_the_measurement_section_it_shares_a_number_with():
    """The second-order effect, asserted directly. With PS1-1 correctly a specification, the MM
    population for section 1 contains only the SMM — and it is not superseded by anything."""
    index = [_e(SMM1, "method_of_measurement", "1", 35),
             _e(PS1_1, "particular_specification", "1", 101)]
    superseded, revised, _c = _revision_contest(index, lambda e: e.kind == "method_of_measurement")

    assert superseded == set() and revised == {}


def test_the_shape_that_was_happening_is_named_so_the_fix_is_not_a_coincidence():
    """The before-picture: with PS1-1 IN the MM population it beats the SMM on revision."""
    index = [_e(SMM1, "method_of_measurement", "1", 35),
             _e(PS1_1, "method_of_measurement", "1", 101)]     # the stored kind, as it was
    superseded, revised, _c = _revision_contest(index, lambda e: e.kind == "method_of_measurement")

    assert superseded == {SMM1} and revised == {"1": 1}


# -- the cross-check that would have caught it ----------------------------------------------------------
def test_the_number_cross_check_could_not_have_caught_this():
    """Both say section 1. Nothing about the NUMBERS was wrong — which is why a second check was
    needed rather than a tighter version of the first."""
    assert section_number_disagreements([_e(PS1_1, "method_of_measurement", "1")]) == []


def test_the_kind_cross_check_does():
    assert kind_disagreements([_e(PS1_1, "method_of_measurement", "1")]) == [
        (PS1_1, "method_of_measurement", "particular_specification")]


def test_a_correctly_classified_pack_reports_nothing():
    pack = [_e(SMM1, "method_of_measurement", "1"), _e(SMM3, "method_of_measurement", "3"),
            _e(SMM28, "method_of_measurement", "28"),
            _e(PS1_1, "particular_specification", "1"), _e(PS27, "particular_specification", "27"),
            _e("S/PS/PS1/I-ND_2025_04-S_PSA1.12-0.pdf", "appendix", "1"),
            _e("S/GS/I-ND_2025_04-S_GS7-0.pdf", "general_specification", "7"),
            _e("BQ/I-ND_2025_04_BQ-0.pdf", "schedule_of_rates", "")]
    assert kind_disagreements(pack) == []
    assert section_number_disagreements(pack) == []


def test_an_appendix_stored_as_a_specification_is_reported_too():
    """The `PSA` token settles the population before the `PS` one does."""
    assert kind_disagreements([_e("S/PS/PS1/…-S_PSA1.12-0.pdf", "method_of_measurement", "1")]) == [
        ("S/PS/PS1/…-S_PSA1.12-0.pdf", "method_of_measurement", "appendix")]


# -- end to end: Builders Work ---------------------------------------------------------------------------
BQ = DocIndexEntry(filename="BQ/I-ND_2025_04_BQ-0.pdf", kind="schedule_of_rates", text_layer=True,
                   page_count=26, bill_mm_sections={"1": ["1", "3"], "9": ["28"]})
PACK = [BQ,
        _e(SMM1, "method_of_measurement", "1", 35), _e(SMM3, "method_of_measurement", "3", 2),
        _e(SMM28, "method_of_measurement", "28", 8),
        _e(PS1_0, "particular_specification", "1", 101), _e(PS1_1, "particular_specification", "1", 101),
        _e(PS27, "particular_specification", "27", 30)]


def _plan(confirmed, *, index=None):
    return resolve_section_plan(
        package_key="builders_work:9", trade="builders_work", section_title="Builders Work",
        section="9", sections=["9", "1"],
        items=[SorItem(item_ref="9.1", description="Safety officer", section="9", clause_refs=[])],
        doc_index=list(PACK if index is None else index), sor_sheet_name="SoR.xlsx",
        confirmed_ps_specs=confirmed, unconfirmed_sections=[],
    )


def _by_doc(plan):
    return {a.source_doc: a.reason for a in plan.attachments}


def test_builders_work_encloses_the_real_smm_1_and_never_the_specification_in_its_place():
    enclosed = _by_doc(_plan({"27", "1"}))

    assert SMM1 in enclosed and "Method of Measurement Section 1" in enclosed[SMM1]
    assert "Method of Measurement" not in enclosed.get(PS1_1, "")


def test_the_specification_reaches_the_same_enquiry_under_its_own_description():
    """One document doing both jobs was the whole complaint. Two documents, two descriptions."""
    enclosed = _by_doc(_plan({"27", "1"}))

    assert PS1_1 in enclosed and "PS Section 1" in enclosed[PS1_1]
    assert PS1_0 not in enclosed, "the superseded revision, correctly out"
    assert SMM1 in enclosed and PS1_1 in enclosed, "both present, neither standing in for the other"


def test_the_false_missing_report_is_gone():
    """The gate said `PS Section 1 — confirmed specification map, no document enclosed` while PS 1
    sat in the bundle wearing the MM label."""
    plan = _plan({"27", "1"})
    assert not any("PS Section 1" in m.spec for m in plan.missing_specs)


def test_a_cited_measurement_section_absent_from_the_pack_is_reported_not_substituted():
    """The rule stated the other way round: when the correct document does not exist, the gate
    names it — never a same-numbered document from another population."""
    without_smm1 = [e for e in PACK if e.filename != SMM1]
    plan = _plan({"27", "1"}, index=without_smm1)
    enclosed = _by_doc(plan)

    assert not any("Method of Measurement Section 1" in r for r in enclosed.values())
    assert any(m.spec == "Method of Measurement Section 1" for m in plan.missing_specs)
    assert PS1_1 in enclosed and "PS Section 1" in enclosed[PS1_1], "the PS is unaffected by it"
