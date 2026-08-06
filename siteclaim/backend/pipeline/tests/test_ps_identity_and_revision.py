"""A Particular Specification must be identified, and its versions reconciled.

Two defects, one screen, both observed on CEDD ND/2025/04.

**A1 — identity.** The pack names every specification `I-ND_2025_04-S_PS28-0.pdf`. The filename
fallback was `(?:^|[^A-Za-z])S0*(\\d+)\\b`, which matches `PS-S07` and CANNOT match that name: in
`S_PS28` the lone `S` is followed by `_`, and `PS28`'s `S` is preceded by a letter. So every PS on
that pack resolved to an empty `spec_section_number` and `relevant_docs`' PS branch skipped it at a
bare `continue`. PS28 never reached an enquiry.

**A2 — versions.** An addendum reissues a document; it does not delete the rest. Where a section was
reissued the operative artifact is the highest revision, and the earlier one must not go out beside
it unmarked — a firm pricing against a superseded specification is pricing the wrong scope. Where a
section was NOT reissued the `-0` original is the only version and must be sent.

**The revision assumption is named, not buried.** The pack carries no revision marker inside the
document; the `-0`/`-1` filename suffix is the only evidence, and the plan says so.

Fixtures, not the real pack — the filenames are that pack's convention, the documents are not.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry, _FILENAME_SECTION, build_doc_entry
from pipeline.stage_03_dispatch.relevant_docs import (
    REVISION_ASSUMPTION,
    SUPERSEDED_BY_ADDENDUM,
    _doc_revision,
    resolve_section_plan,
)
from schemas.models import DocType, SorItem


# -- A1: the filename convention this issuer actually uses -------------------------------------------
@pytest.mark.parametrize("filename,section", [
    ("PS/I-ND_2025_04-S_PS28-0.pdf", "28"),        # the real name that resolved to nothing
    ("PS/I-ND_2025_04-S_PS7-0.pdf", "7"),
    ("SPEC/I-ND_2025_04-S_PS28-1.pdf", "28"),      # the addendum's replacement
    ("GS/I-ND_2025_04-S_GS26-0.pdf", "26"),
    ("PS-S07.pdf", "7"),                            # the OLD convention, still working
    ("GS-S26.pdf", "26"),
])
def test_a_section_number_is_recovered_from_the_filename(filename, section):
    m = _FILENAME_SECTION.search(filename)
    assert m is not None and m.group(1) == section


@pytest.mark.parametrize("filename", [
    "PS/I-ND_2025_04-S_PSA7.12-0.pdf",   # an APPENDIX to PS7 — not PS7
    "PS/I-ND_2025_04-S_PS7.12-0.pdf",    # a dotted clause-shaped token, not a section
    "BQ/I-ND_2025_04_BQ-0.pdf",          # the bill
    "MM/SMM-0.pdf",                       # the method of measurement
    "TA #1/ACC-0.pdf",                    # additional conditions of contract
])
def test_a_name_that_is_not_a_section_claims_none(filename):
    """`PSA7.12` is an appendix TO PS7. Claiming it as PS7 would enclose the wrong document, so the
    digits must follow `PS`/`GS` immediately — the `A` breaks the match — and a dotted continuation
    is refused outright."""
    assert _FILENAME_SECTION.search(filename) is None


def test_the_entry_carries_the_recovered_section(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    # No `SECTION 28` on page 1 — the exact case the filename fallback exists for.
    doc.new_page().insert_text((60, 70), "28.2.07  Grouting shall be carried out as specified.")
    data = doc.tobytes()
    doc.close()

    entry = build_doc_entry("PS/I-ND_2025_04-S_PS28-0.pdf", DocType.PARTICULAR_SPECIFICATION, data)
    assert entry.spec_section_number == "28"


# -- A1: an unidentifiable PS is named, not dropped --------------------------------------------------
def _items(*clause_refs: str):
    return [SorItem(item_ref="G1", description="Borehole", section="G", clause_refs=list(clause_refs))]


def _plan(entries, *, refs=("PS 28.2.07",)):
    return resolve_section_plan(
        package_key="ground_investigation:G", trade="ground_investigation",
        section_title="Drilling", section="G", sections=["G"],
        items=_items(*refs), doc_index=entries, sor_sheet_name="SoR_gi.xlsx",
    )


def test_a_present_but_unidentifiable_ps_appears_as_a_missing_spec():
    """It used to vanish at a bare `continue`: nothing said the pack HELD a specification nobody
    could place. That is a different fact from "the referenced section is absent"."""
    plan = _plan([DocIndexEntry(filename="PS/mystery.pdf", kind="particular_specification",
                                spec_section_number="", text_layer=True, page_count=4)])
    specs = [m.spec for m in plan.missing_specs]
    assert any("mystery.pdf" in s and "no identifiable section number" in s for s in specs)
    assert any(m.referenced_by == "present in the pack, not enclosed" for m in plan.missing_specs)


def test_an_identified_ps_is_enclosed_where_it_used_to_be_skipped():
    plan = _plan([DocIndexEntry(
        filename="PS/I-ND_2025_04-S_PS28-0.pdf", kind="particular_specification",
        spec_section_number="28", text_layer=True, page_count=6,
        clause_index={"28.2.07": [2]})])
    assert [a.source_doc for a in plan.attachments if "PS28" in a.source_doc]
    assert not [m for m in plan.missing_specs if m.spec == "PS Section 28"]


# -- A2: version precedence --------------------------------------------------------------------------
@pytest.mark.parametrize("filename,rev", [
    ("PS/I-ND_2025_04-S_PS28-0.pdf", 0),
    ("PS/I-ND_2025_04-S_PS28-1.pdf", 1),
    ("PS/I-ND_2025_04-S_PS28.pdf", 0),      # no suffix claims no revision
    ("TA #1/I-ND_2025_04-S_PS28-2.pdf", 2),  # the FOLDER's "#1" is not a revision
])
def test_the_revision_is_read_off_the_stem(filename, rev):
    assert _doc_revision(filename) == rev


def _ps(filename, section, rev_pages):
    return DocIndexEntry(filename=filename, kind="particular_specification",
                         spec_section_number=section, text_layer=True, page_count=6,
                         clause_index=rev_pages)


def test_a_reissued_section_sends_the_addendum_and_not_the_superseded_original():
    plan = _plan([
        _ps("PS/I-ND_2025_04-S_PS28-0.pdf", "28", {"28.2.07": [2]}),
        _ps("TA #1/I-ND_2025_04-S_PS28-1.pdf", "28", {"28.2.07": [1]}),
    ])
    enclosed = [a.source_doc for a in plan.attachments if "PS28" in a.source_doc]
    assert enclosed == ["TA #1/I-ND_2025_04-S_PS28-1.pdf"]     # the -1 alone


def test_the_gate_says_which_revision_went_out_and_names_the_assumption():
    """A firm pricing against a superseded specification is pricing the wrong scope. That decision
    must be visible BEFORE drafting, including the fact that a filename suffix decided it."""
    plan = _plan([
        _ps("PS/I-ND_2025_04-S_PS28-0.pdf", "28", {"28.2.07": [2]}),
        _ps("TA #1/I-ND_2025_04-S_PS28-1.pdf", "28", {"28.2.07": [1]}),
    ])
    att = next(a for a in plan.attachments if "PS28" in a.source_doc)
    assert "Rev 1" in att.reason and "superseding" in att.reason
    assert REVISION_ASSUMPTION in att.reason
    assert SUPERSEDED_BY_ADDENDUM in att.flags


def test_a_section_the_addendum_never_touched_still_sends_its_original():
    """The other half, and the one that was broken: PS28 was reaching an enquiry as NEITHER
    version. An addendum revising PS7 says nothing about PS28."""
    plan = _plan([
        _ps("PS/I-ND_2025_04-S_PS28-0.pdf", "28", {"28.2.07": [2]}),
        _ps("PS/I-ND_2025_04-S_PS7-0.pdf", "7", {"7.34": [1]}),
        _ps("TA #1/I-ND_2025_04-S_PS7-1.pdf", "7", {"7.34": [1]}),
    ], refs=("PS 28.2.07", "PS 7.34"))
    enclosed = [a.source_doc for a in plan.attachments if "PS" in a.source_doc]

    assert "PS/I-ND_2025_04-S_PS28-0.pdf" in enclosed        # untouched section: the -0 goes
    assert "TA #1/I-ND_2025_04-S_PS7-1.pdf" in enclosed      # reissued section: the -1 goes
    assert "PS/I-ND_2025_04-S_PS7-0.pdf" not in enclosed     # ...and its -0 does not


def test_an_unrevised_section_says_nothing_about_revisions():
    """No claim where there is no evidence: a lone `-0` is not "Rev 0 supersedes" anything."""
    plan = _plan([_ps("PS/I-ND_2025_04-S_PS28-0.pdf", "28", {"28.2.07": [2]})])
    att = next(a for a in plan.attachments if "PS28" in a.source_doc)
    assert "Rev" not in att.reason and SUPERSEDED_BY_ADDENDUM not in att.flags


def test_an_appendix_never_supersedes_the_section_it_belongs_to():
    """`PSA7.12` is an appendix to PS7. It resolves to no section number, so it is not in the
    comparison at all — and PS7's own original stays the operative document."""
    plan = _plan([
        _ps("PS/I-ND_2025_04-S_PS7-0.pdf", "7", {"7.34": [1]}),
        DocIndexEntry(filename="PS/I-ND_2025_04-S_PSA7.12-0.pdf",
                      kind="particular_specification", spec_section_number="",
                      text_layer=True, page_count=2),
    ], refs=("PS 7.34",))
    assert "PS/I-ND_2025_04-S_PS7-0.pdf" in [a.source_doc for a in plan.attachments]
