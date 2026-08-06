"""If a section is superseded, its replacement is enclosed — or the gate says why not.

THE DEFECT, on the live pack. Builders Work enclosed twenty-five appendices of PS 1 and **neither
PS 1 document** — not the `-0`, and not the `TA #1/…-S_PS1-1.pdf` that supersedes it. A confirmed
mapping that suppresses the original and fails to enclose its replacement leaves the section absent
entirely, which is the worst of the three outcomes and has to be impossible.

THE CAUSE, and it is not identity. PS 1 is **101 pages**, titled *General*, and long enough to carry
its own table of contents on page 1 with the `SECTION 1` declaration further in. The `ps_index`
page-1 fallback — "Particular Specification" + a contents heading + no `SECTION n` — matched it, so
BOTH revisions classified `ps_index`: neither was enclosed, and neither competed in
`_ps_revisions`, which is why the `-0`'s absence looked like supersession. PS 27 declares
`SECTION 27` on page 1 and was untouched. That is exactly the difference that showed on the pack.

THE FIX. A file whose own name says which section it is has already answered the question; a
contents page inside it does not reopen it. The fallback now also requires that the basename names
no section — the same "read the file's own name, never the folder or the furniture" rule
`_own_name` records.

Fixtures, not the real pack: these are that pack's PATH and COVER shapes, written by hand.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry, _kind_for
from pipeline.stage_03_dispatch.relevant_docs import resolve_section_plan
from schemas.models import DocType, SorItem

PS1_0 = "S/PS/PS1/I-ND_2025_04-S_PS1-0.pdf"
PS1_1 = "TA #1/S/PS/PS1/I-ND_2025_04-S_PS1-1.pdf"
PS27_0 = "S/PS/PS27/I-ND_2025_04-S_PS27-0.pdf"
PS27_1 = "TA #2/S/PS/PS27/I-ND_2025_04-S_PS27-1.pdf"
INDEX_DOC = "S/PS/I-ND_2025_04-S_PS_Index-0.pdf"

# A long section's page 1: its own contents, with the SECTION declaration further in.
CONTENTS_COVER = ("PARTICULAR SPECIFICATION\n\nTABLE OF CONTENTS\n\n"
                  "1.01  General\n1.02  Definitions\n1.03  Interpretation\n")
# A short section's page 1: it declares itself.
DECLARED_COVER = "PARTICULAR SPECIFICATION\nSECTION 27\nConstruction Site Safety\n"


# -- the cause, at its root --------------------------------------------------------------------------
@pytest.mark.parametrize("path", [PS1_0, PS1_1])
def test_a_long_section_with_its_own_contents_page_is_not_the_packs_index(path):
    """The reproduction. Before the filename guard both of these returned `ps_index`."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, CONTENTS_COVER, path) == "particular_specification"


def test_the_section_that_declares_itself_was_never_affected():
    """PS 27's reissue WAS enclosed on the pack — the contrast that located the cause."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, DECLARED_COVER, PS27_1) == "particular_specification"


def test_the_packs_real_index_is_still_recognised():
    """The fix must not cost what phase 2 bought. `…-S_PS_Index-0.pdf` names no section number —
    `_FILENAME_PS_SECTION` finds none in it — so the guard does not fire and the name still wins."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, CONTENTS_COVER, INDEX_DOC) == "ps_index"


def test_an_index_named_otherwise_is_still_recognised_from_page_one():
    """The page-1 fallback survives for a document whose name identifies nothing."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, CONTENTS_COVER, "S/PS/contents.pdf") == "ps_index"


@pytest.mark.parametrize("path", [
    "S/PS/PS1/I-ND_2025_04-S_PSA1.12-0.pdf",       # an appendix names its parent section
    "S/GS/I-ND_2025_04-S_GS7-0.pdf",               # a General Specification section
    "TA #1/S/PS/PS31/I-ND_2025_04-S_PS31-1.pdf",   # a reissue under its addendum
])
def test_any_document_whose_name_identifies_a_section_is_safe_from_the_fallback(path):
    """What the guard is: a name that identifies a section closes the question. Which kind it then
    resolves to is the ordinary classification below it — the point here is that a contents page
    can no longer take any of them."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, CONTENTS_COVER, path) != "ps_index"


# -- the invariant: a superseded section is always replaced ---------------------------------------------
def _e(fn, page1, pages=101):
    kind = _kind_for(DocType.PARTICULAR_SPECIFICATION, page1, fn)
    number = "1" if "PS1" in fn else "27"
    return DocIndexEntry(filename=fn, kind=kind, spec_section_number=number,
                         spec_section_title="General" if number == "1" else "Construction Site Safety",
                         spec_section_title_source="ps_index", text_layer=True, page_count=pages)


PACK = [
    _e(PS1_0, CONTENTS_COVER), _e(PS1_1, CONTENTS_COVER),
    _e(PS27_0, DECLARED_COVER, 30), _e(PS27_1, DECLARED_COVER, 30),
] + [
    DocIndexEntry(filename=f"S/PS/PS1/I-ND_2025_04-S_PSA1.{i:02d}-0.pdf", kind="appendix",
                  spec_section_number="1", text_layer=True, page_count=4)
    for i in range(1, 26)
]


def _plan(confirmed, *, index=None):
    return resolve_section_plan(
        package_key="builders_work:1", trade="builders_work", section_title="Builders Work",
        section="1", sections=["1", "9"],
        items=[SorItem(item_ref="1.1", description="Builders work", section="1", clause_refs=[])],
        doc_index=list(PACK if index is None else index), sor_sheet_name="SoR.xlsx",
        confirmed_ps_specs=confirmed,
    )


def _docs(plan):
    return {a.source_doc for a in plan.attachments}


@pytest.mark.parametrize("confirmed,section,winner,loser", [
    ({"1"}, "1", PS1_1, PS1_0),
    ({"27"}, "27", PS27_1, PS27_0),
    ({"1", "27"}, "both", None, None),
])
def test_a_superseded_section_is_never_absent_its_replacement_takes_its_place(
        confirmed, section, winner, loser):
    docs = _docs(_plan(confirmed))
    if winner:
        assert winner in docs, "the replacement is enclosed"
        assert loser not in docs, "the superseded original is not"
    else:
        assert {PS1_1, PS27_1} <= docs
        assert not ({PS1_0, PS27_0} & docs)


def test_every_relevant_section_ends_up_present_in_exactly_one_revision():
    """The invariant stated directly: for each PS section this unit selects, exactly one document
    for that section is enclosed. Absent is not an option a confirmed mapping may produce."""
    for confirmed in ({"1"}, {"27"}, {"1", "27"}):
        plan = _plan(confirmed)
        for number in confirmed:
            enclosed = [a for a in plan.attachments
                        if a.source_doc.startswith(("S/PS", "TA #"))
                        and f"PS{number}-" in a.source_doc]
            assert len(enclosed) == 1, f"section {number}: {[a.source_doc for a in enclosed]}"


def test_the_replacement_states_its_revision_and_evidence():
    att = next(a for a in _plan({"1"}).attachments if a.source_doc == PS1_1)
    assert "Rev 1" in att.reason and "superseding" in att.reason
    assert "the -0/-1 filename suffix" in att.reason


def test_the_appendices_are_withheld_and_reported_not_silently_absent():
    """The other half of what Builders Work actually received: twenty-five appendices narrowed by
    nothing, while the section they belong to was missing."""
    plan = _plan({"1"})
    assert not any("PSA1" in d for d in _docs(plan))
    assert any("25 appendices of PS 1 available, not enclosed" in m.spec for m in plan.missing_specs)


@pytest.mark.parametrize("reverse", [False, True])
def test_the_outcome_does_not_depend_on_index_order(reverse):
    index = list(reversed(PACK)) if reverse else list(PACK)
    docs = _docs(_plan({"1"}, index=index))
    assert PS1_1 in docs and PS1_0 not in docs


def test_a_stale_index_that_stored_the_wrong_kind_is_repaired_on_read():
    """A `doc_index.json` written before the guard carries `ps_index` for both PS 1 documents. That
    one genuinely needs a re-split — there is no rule that can turn `ps_index` back into a
    specification without re-reading page 1 — so the gate must at least not claim the section was
    enclosed. Recorded so the limit is known rather than discovered."""
    stale = [DocIndexEntry(filename=PS1_0, kind="ps_index", text_layer=True, page_count=101),
             DocIndexEntry(filename=PS1_1, kind="ps_index", text_layer=True, page_count=101)]
    plan = _plan({"1"}, index=stale)

    assert not ({PS1_0, PS1_1} & _docs(plan))
    assert plan.relevance_source == "confirmed_map"
    assert any("PS Section 1" in m.spec for m in plan.missing_specs), \
        "a confirmed section with no document present is reported missing"
