"""A folder name is not a section number, and an appendix never supersedes its specification.

`_FILENAME_SECTION` was searched over the WHOLE ARCHIVE PATH. On the real pack an appendix lives at
`S/PS/PS7/I-ND_2025_04-S_PSA7.12-0.pdf`, so the pattern matched `PS7` IN THE FOLDER and the appendix
was handed `spec_section_number = "7"` — it claimed to BE the section it merely belongs to. The
pattern itself was right; it was reading the wrong string, and every unit test passed a basename,
which is exactly why nothing caught it.

The consequence was in `_ps_revisions`. The pack ships a revised APPENDIX
(`TA #1/…-S_PSA1.12-1.pdf`) beside the revised SPECIFICATION (`TA #1/…-S_PS1-1.pdf`). Both resolved
to section 1 at revision 1; `rev > current[0]` is strict; so **whichever the index listed first
won**, and in the other order the firm received an appendix and NOT the specification section it
appends to, with nothing on the gate to say so. 25 PSA files under PS1, 28 under PS7, 38 under PS31.

Everything here drives the REAL PACK'S PATH SHAPES. A basename-only fixture is what hid this.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    _FILENAME_APPENDIX,
    _FILENAME_SECTION,
    _own_name,
    build_doc_entry,
)
from pipeline.stage_03_dispatch.relevant_docs import (
    _competes_as_a_specification,
    _ps_revisions,
    resolve_section_plan,
)
from schemas.models import DocType, SorItem

# The real paths, verbatim in shape.
PS1_ORIG = "S/PS/PS1/I-ND_2025_04-S_PS1-0.pdf"
PS1_REV = "TA #1/S/PS/PS1/I-ND_2025_04-S_PS1-1.pdf"
PSA1_ORIG = "S/PS/PS1/I-ND_2025_04-S_PSA1.12-0.pdf"
PSA1_REV = "TA #1/S/PS/PS1/I-ND_2025_04-S_PSA1.12-1.pdf"
PS28 = "S/PS/PS28/I-ND_2025_04-S_PS28-0.pdf"
PSA7 = "S/PS/PS7/I-ND_2025_04-S_PSA7.12-0.pdf"


# -- identity comes from the file, not the folder -------------------------------------------------
@pytest.mark.parametrize("path", [PSA7, PSA1_ORIG, PSA1_REV, "S/PS/PS1/I-ND_2025_04-S_PSA1.12A-0.pdf"])
def test_an_appendix_under_its_parents_folder_claims_no_ps_section(path):
    """The defect, at its root. Searched over the path, `PS7`/`PS1` in the FOLDER matched."""
    assert _FILENAME_SECTION.search(_own_name(path)) is None
    assert _FILENAME_SECTION.search(path) is not None, "the folder still matches — that was the bug"


@pytest.mark.parametrize("path,section", [(PS28, "28"), (PS1_ORIG, "1"), (PS1_REV, "1")])
def test_a_specification_under_its_own_folder_still_resolves(path, section):
    m = _FILENAME_SECTION.search(_own_name(path))
    assert m is not None and m.group(1) == section


@pytest.mark.parametrize("path,parent", [(PSA7, "7"), (PSA1_ORIG, "1")])
def test_an_appendix_resolves_the_section_it_belongs_to(path, parent):
    """Its identity is not nothing — it is "an appendix to section N", which is what the appendix
    branch matches on. Fixing the claim must not erase the document."""
    m = _FILENAME_APPENDIX.search(_own_name(path))
    assert m is not None and m.group(1) == parent


def test_the_indexed_entry_reads_its_own_name(tmp_path):
    """End to end through `build_doc_entry`, with page 1 declaring only the DOTTED appendix form —
    which `_APPENDIX_COVER` excludes, so this file used to be classified a specification."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((60, 70), "Appendix 1.12  Borehole Log Proforma")
    data = doc.tobytes()
    doc.close()

    entry = build_doc_entry(PSA1_ORIG, DocType.PARTICULAR_SPECIFICATION, data)
    assert entry.kind == "appendix"
    assert entry.spec_section_number == "1"       # the section it BELONGS to, as an appendix


# -- who may compete to BE a section --------------------------------------------------------------
def _e(fn, sec, kind="particular_specification", ci=None):
    return DocIndexEntry(filename=fn, kind=kind, spec_section_number=sec, text_layer=True,
                         page_count=4, clause_index=ci or {})


def test_an_appendix_never_competes_even_when_its_stored_kind_is_wrong():
    """Two guards, neither foolable by a folder: the kind AND the issuer's own `PSA` token, read
    off the basename. The token is what catches an index written before the classifier learned it."""
    assert _competes_as_a_specification(_e(PS1_REV, "1")) is True
    assert _competes_as_a_specification(_e(PSA1_REV, "1")) is False      # stale kind, still refused
    assert _competes_as_a_specification(_e(PSA1_REV, "1", kind="appendix")) is False


@pytest.mark.parametrize("reverse", [False, True])
def test_the_specification_wins_its_section_whatever_the_index_order(reverse):
    """The reproduction, both ways round. Order A gave PS1-1; order B gave PSA1.12-1."""
    idx = [_e(PS1_ORIG, "1"), _e(PS1_REV, "1"), _e(PSA1_REV, "1")]
    if reverse:
        idx.reverse()

    superseded, revised, contested = _ps_revisions(idx)
    assert revised == {"1": 1}
    assert superseded == {PS1_ORIG}                  # only the earlier SPECIFICATION is set aside
    assert PSA1_REV not in superseded                # the appendix was never in the running
    assert contested == []


def test_a_genuine_tie_is_deterministic_and_reported_not_a_coin_flip():
    """Two documents claiming ONE section at ONE revision is a fact about the pack.

    Resolved lexicographically — chosen only because it is stable and independent of how the index
    happened to be built — and the one set aside is named, never dropped quietly.
    """
    a = _e("S/PS/PS9/I-ND_2025_04-S_PS9-1.pdf", "9")
    b = _e("TA #2/S/PS/PS9/I-ND_2025_04-S_PS9-1.pdf", "9")

    forward = _ps_revisions([a, b])
    backward = _ps_revisions([b, a])
    assert forward == backward, "the answer must not depend on list order"

    superseded, _revised, contested = forward
    assert superseded == {b.filename}                       # 'S/…' sorts before 'TA #2/…'
    assert contested == [(a.filename, b.filename)]


def test_the_gate_names_the_document_that_lost_a_tie():
    plan = _plan([
        _e("S/PS/PS1/I-ND_2025_04-S_PS1-1.pdf", "1", ci={"1.12": [1]}),
        _e("TA #2/S/PS/PS1/I-ND_2025_04-S_PS1-1.pdf", "1", ci={"1.12": [1]}),
    ])
    specs = [m.spec for m in plan.missing_specs]
    assert any("claims the same section and revision" in s for s in specs)
    assert any(m.referenced_by == "contested revision, resolved by filename order"
               for m in plan.missing_specs)


# -- the appendix still reaches the firm ------------------------------------------------------------
def _plan(entries, *, refs=("PS 1.12", "Appendix 1.12")):
    return resolve_section_plan(
        package_key="ground_investigation:G", trade="ground_investigation",
        section_title="Drilling", section="G", sections=["G"],
        items=[SorItem(item_ref="G1", description="Borehole", section="G",
                       clause_refs=list(refs))],
        doc_index=entries, sor_sheet_name="SoR_gi.xlsx",
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_both_the_specification_and_its_appendix_are_enclosed(reverse):
    """Fixing the appendix's identity must not make it vanish — it goes down the appendix branch.

    The entries carry the STALE stored kind and the folder-derived section, which is what a
    `doc_index.json` written before this change holds. The effective-kind override fixes them at
    read time, with no re-split.
    """
    idx = [_e(PS1_ORIG, "1", ci={"1.12": [1]}), _e(PSA1_ORIG, "1", ci={"1.12": [0]})]
    if reverse:
        idx.reverse()

    enclosed = {a.source_doc: a.reason for a in _plan(idx).attachments}
    assert PS1_ORIG in enclosed and "PS Section 1" in enclosed[PS1_ORIG]
    assert PSA1_ORIG in enclosed and "Appendix 1" in enclosed[PSA1_ORIG]


def test_the_enclosed_set_is_identical_in_either_order():
    idx = [_e(PS1_ORIG, "1", ci={"1.12": [1]}), _e(PS1_REV, "1", ci={"1.12": [1]}),
           _e(PSA1_REV, "1", ci={"1.12": [0]})]
    forward = {a.source_doc for a in _plan(idx).attachments}
    backward = {a.source_doc for a in _plan(list(reversed(idx))).attachments}

    assert forward == backward
    assert PS1_REV in forward and PSA1_REV in forward      # the revised spec AND its revised appendix
    assert PS1_ORIG not in forward                          # the superseded original, correctly out


def test_ps28_under_its_own_folder_is_still_delivered():
    """The previous fix must survive this one: a specification whose page 1 declares nothing."""
    plan = _plan([_e(PS28, "28", ci={"28.2.07": [1]})], refs=("PS 28.2.07",))
    assert PS28 in [a.source_doc for a in plan.attachments]
