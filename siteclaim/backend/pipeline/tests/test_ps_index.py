"""The PS Index is a document in its own right, and it names every specification section.

`S/PS/I-ND_2025_04-S_PS_Index-0.pdf` is the Particular Specification's own table of contents. Two
things were wrong with how it arrived:

* it classified as `particular_specification` with no section number — page 1 declares none and
  `_FILENAME_SECTION` correctly finds none in that basename — so the "present but unidentifiable"
  report fired on it **every run**, naming a false alarm beside the real ones it exists to surface;
* it is the ONLY place the pack states each PS section's TITLE, and nothing read it. On this pack no
  PS section declares `SECTION n — Title` on page 1, so the specification side of any title match
  was empty.

Both are fixed here: the index gets its own `kind`, and a deterministic parser reads its contents
into `spec_section_number -> title`, applied across the set by `apply_ps_index_titles`.

**The text below is the real page 3, verbatim** — supplied from the pack as `page_text(data, 1, 3)`
— not an invented layout. Its spacing is genuinely ragged and that is the point: the rule reads the
gap as whitespace, never as a column. The surrounding pages (a cover, a blank, the running header
and footer) are written by hand to the shape the pack was described as having; the pack itself is
not in this repository.

No model call anywhere in this path.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    _FILENAME_APPENDIX,
    _FILENAME_SECTION,
    _kind_for,
    _own_name,
    apply_ps_index_titles,
    build_doc_index,
    parse_ps_index,
)
from pipeline.stage_03_dispatch.relevant_docs import resolve_section_plan
from schemas.models import DocType, SorItem

INDEX_DOC = "S/PS/I-ND_2025_04-S_PS_Index-0.pdf"
PS28 = "S/PS/PS28/I-ND_2025_04-S_PS28-0.pdf"
PS2 = "S/PS/PS2/I-ND_2025_04-S_PS2-0.pdf"

# Page 3 of the real index, verbatim. Every leading space is the source's own.
PAGE_3 = """\
                        PARTICULAR SPECIFICATION
                          TABLE OF CONTENTS
    SECTION   TITLE
         1        General
         2         Site Clearance
         7        Geotechnical Works
        25       Environmental Protection
        26        Preservation and Protection of Trees
        27        Construction Site Safety
        28       Environmental Ground Investigation
        29       Payment of Wages of the Site Workers
        30      Management of Subcontractors
        31       Laboratory Testing
        32        Site Uniform
"""

# The eleven entries, in the order the document prints them.
EXPECTED = [
    ("1", "General"),
    ("2", "Site Clearance"),
    ("7", "Geotechnical Works"),
    ("25", "Environmental Protection"),
    ("26", "Preservation and Protection of Trees"),
    ("27", "Construction Site Safety"),
    ("28", "Environmental Ground Investigation"),
    ("29", "Payment of Wages of the Site Workers"),
    ("30", "Management of Subcontractors"),
    ("31", "Laboratory Testing"),
    ("32", "Site Uniform"),
]

HEADER = "Contract No. ND/2025/04\nParticular Specification\nScope\n"
FOOTER = "AECOM-AtkinsRealis JV  PS/{page}\n"


def _page(body: str, page: str) -> str:
    """One page as the pack prints it: the running header, the body, the running footer."""
    return HEADER + body + FOOTER.format(page=page)


COVER = _page("                        PARTICULAR SPECIFICATION\n", "i")
BLANK = _page("", "ii")
INDEX_PAGES = [COVER, BLANK, _page(PAGE_3, "iii")]


# -- the eleven entries --------------------------------------------------------------------------
def test_the_real_page_three_yields_exactly_eleven_entries():
    titles, unreadable = parse_ps_index([PAGE_3])
    assert list(titles.items()) == EXPECTED
    assert len(titles) == 11
    assert unreadable == []


def test_the_same_eleven_survive_the_running_header_and_footer():
    """The pack repeats `Contract No. …` / `Particular Specification` / `Scope` on every page and
    footers each with `AECOM-AtkinsRealis JV  PS/iii`. None of them opens with a number, so none is
    a candidate row — and the cover and the blank page before the list contribute nothing."""
    titles, unreadable = parse_ps_index(INDEX_PAGES)
    assert list(titles.items()) == EXPECTED
    assert unreadable == []
    for furniture in ("Contract", "AECOM", "Scope", "AtkinsRealis"):
        assert not any(furniture in t for t in titles.values())


def test_the_gap_between_number_and_title_is_genuinely_ragged():
    """The reason the rule may not use a fixed column, made checkable against the real text.

    `1` is followed by 8 spaces, `30` by 6, `2` by 9. A column-offset parser would cut some titles
    and miss others; whitespace of any width is the only honest reading.
    """
    gaps = set()
    for line in PAGE_3.splitlines():
        stripped = line.lstrip()
        if stripped[:1].isdigit():
            digits = len(stripped) - len(stripped.lstrip("0123456789"))
            rest = stripped[digits:]
            gaps.add(len(rest) - len(rest.lstrip(" ")))
    assert len(gaps) > 1, f"the source spacing is not ragged after all: {gaps}"
    assert dict(parse_ps_index([PAGE_3])[0])["30"] == "Management of Subcontractors"


# -- the anchor ------------------------------------------------------------------------------------
def test_nothing_before_the_section_title_header_row_can_be_an_entry():
    """Anchored on the header row, not scanned. A numbered line above it — a clause reference, a
    revision table, a page of contract particulars — is not a table-of-contents entry."""
    preamble = _page(
        "7.28  Rotary drilling shall be carried out in accordance with …\n"
        "2  Revision A issued under Tender Addendum #1\n",
        "ii",
    )
    titles, _unreadable = parse_ps_index([preamble, _page(PAGE_3, "iii")])
    assert list(titles.items()) == EXPECTED
    assert titles["2"] == "Site Clearance"          # not "Revision A issued under …"
    assert "7" in titles and titles["7"] == "Geotechnical Works"


def test_a_document_with_no_header_row_yields_nothing_rather_than_a_guess():
    """No anchor, no entries. A specification body full of numbered clauses must not become an
    index just because it was handed to the parser."""
    body = _page("7.28  Rotary drilling\n7.29  Standpipe installation\n", "1")
    assert parse_ps_index([body]) == ({}, [])


def test_the_specification_body_after_the_list_is_not_read():
    """The list ends where it ends. A page after it that contributes no row stops the read, so
    prose further into the document can never add an entry."""
    after = _page("1  This Particular Specification shall be read with the General …\n", "1")
    titles, _unreadable = parse_ps_index(INDEX_PAGES + [after, after])
    assert list(titles.items()) == EXPECTED
    assert titles["1"] == "General"                 # not overwritten by the body's leading "1"


# -- a row that cannot be read -----------------------------------------------------------------------
def test_a_row_with_no_readable_title_is_reported_never_filled():
    """The invariant: an invented title would become the specification side of a match nobody could
    check. A number with nothing readable beside it is returned as unreadable and left out."""
    damaged = PAGE_3.replace("        32        Site Uniform\n", "        32        .\n")
    titles, unreadable = parse_ps_index([damaged])

    assert "32" not in titles
    assert len(titles) == 10
    assert unreadable == ["32        ."]


def test_the_readable_rows_around_a_damaged_one_still_come_through():
    damaged = PAGE_3.replace("        28       Environmental Ground Investigation\n", "        28\n")
    titles, unreadable = parse_ps_index([damaged])

    assert "28" not in titles and unreadable == ["28"]
    assert titles["27"] == "Construction Site Safety"
    assert titles["29"] == "Payment of Wages of the Site Workers"


# -- identity ------------------------------------------------------------------------------------------
def test_the_index_is_not_a_specification_section():
    """Its own kind. It declares no `SECTION n`, so under the PS branch it was reported as an
    unidentifiable specification on every run of this pack."""
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, COVER, INDEX_DOC) == "ps_index"


def test_the_filename_patterns_are_left_alone_and_still_find_nothing_here():
    """Stated in the brief and worth pinning: neither pattern resolves a number from this basename,
    which is exactly why the identity had to come from somewhere else."""
    own = _own_name(INDEX_DOC)
    assert _FILENAME_SECTION.search(own) is None
    assert _FILENAME_APPENDIX.search(own) is None


def test_a_specification_that_declares_its_own_section_is_never_taken_for_the_index():
    """The page-1 fallback (`Particular Specification` + a contents heading) must not steal a real
    section that happens to list its own clauses."""
    page1 = ("PARTICULAR SPECIFICATION\nTABLE OF CONTENTS\n"
             "SECTION 28 - ENVIRONMENTAL GROUND INVESTIGATION\n")
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, page1, PS28) == "particular_specification"


def test_an_index_named_otherwise_is_still_recognised_from_page_one():
    page1 = "PARTICULAR SPECIFICATION\nTABLE OF CONTENTS\n"
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, page1, "S/PS/contents.pdf") == "ps_index"


# -- the false alarm is gone ------------------------------------------------------------------------
def _entry(fn, kind, sec="", **kw):
    return DocIndexEntry(filename=fn, kind=kind, spec_section_number=sec, text_layer=True,
                         page_count=4, **kw)


def _plan(entries):
    return resolve_section_plan(
        package_key="ground_investigation:G", trade="ground_investigation",
        section_title="Drilling", section="G", sections=["G"],
        items=[SorItem(item_ref="G1", description="Borehole", section="G", clause_refs=["PS 28.2.07"])],
        doc_index=entries, sor_sheet_name="SoR_gi.xlsx",
    )


def test_the_index_no_longer_appears_as_a_missing_specification():
    plan = _plan([_entry(INDEX_DOC, "ps_index"),
                  _entry(PS28, "particular_specification", "28", clause_index={"28.2.07": [1]})])

    assert not any(INDEX_DOC in m.spec for m in plan.missing_specs), \
        [m.spec for m in plan.missing_specs]
    assert not any("no identifiable section number" in m.spec for m in plan.missing_specs)
    assert PS28 in [a.source_doc for a in plan.attachments]   # the real specification still goes


def test_that_report_is_what_the_index_used_to_trigger():
    """The before-picture, so the test above is known to be testing the fix and not a coincidence:
    the SAME document under its old kind still produces the false alarm."""
    plan = _plan([_entry(INDEX_DOC, "particular_specification"),
                  _entry(PS28, "particular_specification", "28", clause_index={"28.2.07": [1]})])
    assert any(INDEX_DOC in m.spec and "no identifiable section number" in m.spec
               for m in plan.missing_specs)


def test_the_index_is_not_enclosed_with_an_enquiry():
    """It is a contents page for the pack, not scope a firm prices against. Not reported, and not
    attached either — those are different things and both are deliberate."""
    plan = _plan([_entry(INDEX_DOC, "ps_index"),
                  _entry(PS28, "particular_specification", "28", clause_index={"28.2.07": [1]})])
    assert INDEX_DOC not in [a.source_doc for a in plan.attachments]


# -- the titles land on the sections -----------------------------------------------------------------
def _indexed(**kw):
    titles, unreadable = parse_ps_index([PAGE_3])
    return _entry(INDEX_DOC, "ps_index", ps_index_titles=titles, ps_index_unreadable=unreadable, **kw)


def test_a_section_that_declares_no_title_takes_the_one_the_index_states():
    out = apply_ps_index_titles([_indexed(), _entry(PS28, "particular_specification", "28")])
    ps28 = next(e for e in out if e.filename == PS28)

    assert ps28.spec_section_title == "Environmental Ground Investigation"
    assert ps28.spec_section_title_source == "ps_index"       # provenance, not a silent fill


def test_a_page_one_declaration_still_wins():
    """A title a document states about ITSELF is stronger evidence than one another document states
    about it. The fill only reaches an empty title."""
    declared = _entry(PS28, "particular_specification", "28",
                      spec_section_title="ENVIRONMENTAL GROUND INVESTIGATION (AMENDED)",
                      spec_section_title_source="page_1")
    out = apply_ps_index_titles([_indexed(), declared])
    ps28 = next(e for e in out if e.filename == PS28)

    assert ps28.spec_section_title == "ENVIRONMENTAL GROUND INVESTIGATION (AMENDED)"
    assert ps28.spec_section_title_source == "page_1"


def test_a_section_the_index_does_not_name_is_left_empty():
    """No entry, no guess. Section 9 is not in this pack's contents."""
    out = apply_ps_index_titles([_indexed(), _entry("…-S_PS9-0.pdf", "particular_specification", "9")])
    ps9 = next(e for e in out if e.spec_section_number == "9")

    assert ps9.spec_section_title == ""
    assert ps9.spec_section_title_source == ""


def test_with_no_index_in_the_set_nothing_changes():
    entries = [_entry(PS28, "particular_specification", "28")]
    assert apply_ps_index_titles(entries) == entries


def test_a_document_that_is_neither_a_specification_nor_an_appendix_is_not_titled():
    """The Schedule of Rates carries a section number of its own vocabulary; the PS contents say
    nothing about it and must not be applied to it."""
    sor = _entry("SoR.pdf", "schedule_of_rates", "2")
    out = apply_ps_index_titles([_indexed(), sor])
    assert next(e for e in out if e.filename == "SoR.pdf").spec_section_title == ""


# -- what phase 3 must not do ---------------------------------------------------------------------
def test_the_numbers_do_not_correspond_so_a_number_match_would_enclose_the_wrong_section():
    """The domain rule this whole path exists to serve, recorded against the real contents.

    The bill headed "Ground Investigation" is **Bill 2** — a Standard-Method-of-Measurement number.
    Section 2 of the Particular Specification is **Site Clearance**. Matching bill number to PS
    number would enclose site clearance for a ground-investigation package and omit the
    specification that actually governs it, which is PS **28**.
    """
    titles, _unreadable = parse_ps_index([PAGE_3])
    assert titles["2"] == "Site Clearance"
    assert titles["28"] == "Environmental Ground Investigation"
    assert "Ground Investigation" not in titles["2"]


# -- end to end, through the index builder ---------------------------------------------------------
def _pdf(pages: list[str]) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        y = 60
        for line in text.splitlines() or [""]:
            page.insert_text((40, y), line, fontname="cour", fontsize=8)
            y += 11
    data = doc.tobytes()
    doc.close()
    return data


def test_build_doc_index_reads_the_index_and_names_the_sections():
    """The whole path on real PDF bytes: classify, parse, then apply across the set.

    PS28's own page 1 declares no section — which is the pack's actual shape and why the filename
    fallback exists — so before this it reached dispatch with a number and no name at all.
    """
    docs = [
        (INDEX_DOC, DocType.PARTICULAR_SPECIFICATION, _pdf(INDEX_PAGES)),
        (PS28, DocType.PARTICULAR_SPECIFICATION,
         _pdf([_page("28.2.07  Trial pits\n", "1")])),
        (PS2, DocType.PARTICULAR_SPECIFICATION, _pdf([_page("2.1  Clearance of the site\n", "1")])),
    ]
    entries = {e.filename: e for e in build_doc_index(docs)}

    assert entries[INDEX_DOC].kind == "ps_index"
    assert len(entries[INDEX_DOC].ps_index_titles) == 11
    assert entries[INDEX_DOC].ps_index_unreadable == []

    assert entries[PS28].spec_section_number == "28"          # from the filename, unchanged
    assert entries[PS28].spec_section_title == "Environmental Ground Investigation"
    assert entries[PS28].spec_section_title_source == "ps_index"
    assert entries[PS2].spec_section_title == "Site Clearance"
    assert entries[PS2].spec_section_title_source == "ps_index"
