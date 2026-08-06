"""A truncated title still matches — against the wrong subject. So titles are read whole.

THE DEFECT, from the live run on ND/2025/04. `_SECTION_DECL`'s title group is `[^\\n]`, so it stops
at the first line break, while the `\\s*` before it happily crosses one. Three of the eleven covers
set their title on two lines, and all three were cut at exactly the wrap:

    SECTION 28 / Environmental Ground / Investigation   ->  "Environmental Ground"
    SECTION 26 / Preservation and / Protection of Trees ->  "Preservation and"
    SECTION 30 / Management / of Subcontractors         ->  "Management"

`apply_ps_index_titles` then declined to correct them, because it only ever filled an EMPTY title —
a page-1 declaration always won. So the pack's own complete index sat unused beside three titles
with their subjects removed, and the matcher proposed on what was left: Bill 9 "Site Safety
**Management**" found PS 30 "**Management**" and proposed the subcontractor-management section.

Two fixes, both here. `section_declaration` reads past the break, conservatively. And the index now
overrides a page-1 title that is a strict PREFIX of it — not a disagreement, the same title with the
end missing — recording `ps_index` as the source when it does.

The eleven titles come from `parse_ps_index` over the real page-3 text (`test_ps_index.PAGE_3`), so
these tests and phase 2's cannot drift apart. The page-1 wraps are written to the shape the live run
reported; the pack itself is not in this repository.
"""

import json

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    _is_truncation_of,
    apply_ps_index_titles,
    load_doc_index,
    parse_ps_index,
    save_doc_index,
    section_declaration,
)
from pipeline.stage_03_dispatch.spec_match import propose_for_heading
from pipeline.tests.test_ps_index import PAGE_3

TITLES, _UNREADABLE = parse_ps_index([PAGE_3])
# The three the live run reported truncated, as page 1 sets them.
WRAPPED = {"28": "Environmental Ground\nInvestigation",
           "26": "Preservation and\nProtection of Trees",
           "30": "Management\nof Subcontractors"}


def _index_entry() -> DocIndexEntry:
    return DocIndexEntry(filename="S/PS/…-S_PS_Index-0.pdf", kind="ps_index", text_layer=True,
                         page_count=3, ps_index_titles=TITLES)


def _pack() -> list[DocIndexEntry]:
    """The pack as the live run indexed it: the contents document, plus eleven sections whose
    page 1 declares a title — three of them wrapped."""
    out = [_index_entry()]
    for n, t in TITLES.items():
        page1 = f"SECTION {n}\n{WRAPPED.get(n, t)}\n\nContract No. ND/2025/04\nPage 1 of 20\n"
        number, title = section_declaration(page1)
        out.append(DocIndexEntry(filename=f"S/PS/PS{n}/…-S_PS{n}-0.pdf",
                                 kind="particular_specification", spec_section_number=number,
                                 spec_section_title=title,
                                 spec_section_title_source="page_1" if title else "",
                                 text_layer=True, page_count=20))
    return out


PACK = apply_ps_index_titles(_pack())


def _by_section(entries, number):
    return next(e for e in entries if e.spec_section_number == number
                and e.kind == "particular_specification")


# -- the reader now crosses the wrap --------------------------------------------------------------
@pytest.mark.parametrize("number,expected", [
    ("28", "Environmental Ground Investigation"),
    ("26", "Preservation and Protection of Trees"),
    ("30", "Management of Subcontractors"),
])
def test_a_title_set_on_two_lines_is_read_whole(number, expected):
    assert section_declaration(f"SECTION {number}\n{WRAPPED[number]}\n") == (number, expected)


@pytest.mark.parametrize("page1,number,title", [
    ("SECTION 31\nLaboratory Testing\n", "31", "Laboratory Testing"),
    ("SECTION 27 - Construction Site Safety\n", "27", "Construction Site Safety"),
    ("SECTION 7 – GEOTECHNICAL WORKS\n", "7", "GEOTECHNICAL WORKS"),
])
def test_a_single_line_declaration_reads_exactly_as_it_always_did(page1, number, title):
    assert section_declaration(page1) == (number, title)


def test_a_page_with_no_declaration_yields_nothing():
    assert section_declaration("Particular Specification\nContract No. ND/2025/04\n") == ("", "")


# -- what stops the read ----------------------------------------------------------------------------
@pytest.mark.parametrize("after,why", [
    ("7.01  General requirements\n", "a clause id — the heading has ended"),
    ("Page 3 of 40\n", "a page number carries digits"),
    ("\nProtection of Trees\n", "a blank line ends the heading block"),
    ("Particular Specification\n", "page furniture, not the title"),
    ("Contract No. ND/2025/04\n", "page furniture, not the title"),
    ("Table of Contents\n", "page furniture, not the title"),
    ("SECTION 27 - Construction Site Safety\n", "the NEXT section's declaration"),
    ("This Particular Specification shall be read together with the General Specification.\n",
     "body prose — too many words to be a heading"),
])
def test_the_continuation_stops_before_what_is_not_the_title(after, why):
    """A wrong title is worse than a short one — it matches, just against the wrong subject. So the
    continuation is conservative, and each of these boundaries is pinned."""
    _number, title = section_declaration(f"SECTION 26\nPreservation and\n{after}")
    assert title == "Preservation and", why


def test_the_joined_title_stays_inside_the_declarations_own_length_bound():
    long_tail = " ".join(["Extraordinarily"] * 5)
    _n, title = section_declaration(f"SECTION 26\nPreservation and Protection of Trees\n{long_tail}\n")
    assert title == "Preservation and Protection of Trees"
    assert len(title) <= 80


def test_at_most_two_continuation_lines_are_joined():
    """Three lines of title is the most any cover here sets; a fourth is something else."""
    _n, title = section_declaration(
        "SECTION 26\nPreservation\nand Protection\nof Trees\nand Shrubs Throughout\n")
    assert title == "Preservation and Protection of Trees"


# -- the index completes a truncation, and only a truncation -----------------------------------------
@pytest.mark.parametrize("short,full,is_trunc", [
    ("Preservation and", "Preservation and Protection of Trees", True),
    ("Management", "Management of Subcontractors", True),
    ("Environmental Ground", "Environmental Ground Investigation", True),
    ("ENVIRONMENTAL GROUND", "Environmental Ground Investigation", True),   # case-insensitive
    ("Trees Preservation", "Preservation and Protection of Trees", False),  # reordered, not cut
    ("Protection of Trees", "Preservation and Protection of Trees", False),  # a suffix, not a prefix
    ("Laboratory Testing", "Laboratory Testing", False),                    # identical, nothing to do
    ("", "Management of Subcontractors", False),
])
def test_a_truncation_is_a_strict_leading_word_run(short, full, is_trunc):
    assert _is_truncation_of(short, full) is is_trunc


@pytest.mark.parametrize("number", ["28", "26", "30"])
def test_a_truncated_page_one_title_is_completed_from_the_index(number):
    """Even with the reader fixed, the index stays the proof that a declaration was short — an
    index written by an earlier run still carries the truncation, and is repaired on read."""
    truncated = DocIndexEntry(filename=f"PS{number}.pdf", kind="particular_specification",
                              spec_section_number=number,
                              spec_section_title=section_declaration(
                                  f"SECTION {number}\n{WRAPPED[number].splitlines()[0]}\n")[1],
                              spec_section_title_source="page_1", text_layer=True, page_count=20)
    out = apply_ps_index_titles([_index_entry(), truncated])
    got = _by_section(out, number)

    assert got.spec_section_title == TITLES[number]
    assert got.spec_section_title_source == "ps_index"


def test_a_complete_page_one_title_still_wins():
    """The rule did not invert. A document's own words beat the index unless they are its own words
    cut short."""
    own = DocIndexEntry(filename="PS28.pdf", kind="particular_specification", spec_section_number="28",
                        spec_section_title="Environmental Ground Investigation (Amended)",
                        spec_section_title_source="page_1", text_layer=True, page_count=20)
    got = _by_section(apply_ps_index_titles([_index_entry(), own]), "28")

    assert got.spec_section_title == "Environmental Ground Investigation (Amended)"
    assert got.spec_section_title_source == "page_1"


def test_a_genuine_disagreement_keeps_the_documents_own_words():
    """Neither contains the other. That is a fact about the pack for a person to look at, not a tie
    for this function to break — so it is logged and the declaration stands."""
    own = DocIndexEntry(filename="PS30.pdf", kind="particular_specification", spec_section_number="30",
                        spec_section_title="Control of Domestic Subcontractors",
                        spec_section_title_source="page_1", text_layer=True, page_count=20)
    got = _by_section(apply_ps_index_titles([_index_entry(), own]), "30")

    assert got.spec_section_title == "Control of Domestic Subcontractors"
    assert got.spec_section_title_source == "page_1"


# -- provenance is never blank on a titled entry ------------------------------------------------------
def test_every_titled_section_in_the_pack_declares_where_its_title_came_from():
    """The live symptom: `ps_title_source` empty on every proposal, and the evidence line reading
    "The PS title came from an undeclared source"."""
    titled = [e for e in PACK if e.kind == "particular_specification" and e.spec_section_title]

    assert len(titled) == 11
    assert all(e.spec_section_title_source in ("page_1", "ps_index") for e in titled)
    assert {e.spec_section_title for e in titled} == set(TITLES.values()), "all eleven, complete"


def test_an_index_written_before_the_provenance_field_existed_is_backfilled():
    """`build_doc_entry` sets a title from page 1 and nowhere else, so a titled entry with no
    recorded source came from page 1. Stating that beats reporting "an undeclared source"."""
    legacy = DocIndexEntry(**{"filename": "PS31.pdf", "kind": "particular_specification",
                              "spec_section_number": "31", "spec_section_title": "Laboratory Testing",
                              "text_layer": True, "page_count": 12})
    assert legacy.spec_section_title_source == ""      # what the old JSON deserialises to

    assert _by_section(apply_ps_index_titles([legacy]), "31").spec_section_title_source == "page_1"


class _Ws:
    def __init__(self, tmp_path):
        self._p = tmp_path

    def doc_index_path(self, tender_id, create=False):
        return self._p / f"{tender_id}.json"


def test_a_persisted_index_is_completed_on_read_without_a_re_split(tmp_path):
    """A 232 MB pack must not have to be re-split to recover titles already sitting in the file."""
    ws = _Ws(tmp_path)
    stale = DocIndexEntry(filename="PS28.pdf", kind="particular_specification", spec_section_number="28",
                          spec_section_title="Environmental Ground", text_layer=True, page_count=20)
    save_doc_index(ws, "nd-2025-04", [_index_entry(), stale])

    on_disk = json.loads((tmp_path / "nd-2025-04.json").read_text())
    assert [d for d in on_disk if d["filename"] == "PS28.pdf"][0]["spec_section_title"] == \
        "Environmental Ground", "the file is untouched — the repair happens on read"

    got = _by_section(load_doc_index(ws, "nd-2025-04"), "28")
    assert got.spec_section_title == "Environmental Ground Investigation"
    assert got.spec_section_title_source == "ps_index"


def test_an_index_predating_the_contents_parser_is_a_no_op_not_a_guess(tmp_path):
    """Nothing to complete FROM. The pass must leave the truncation alone rather than invent an
    ending — that one genuinely needs a re-split, and the report says so."""
    ws = _Ws(tmp_path)
    stale = DocIndexEntry(filename="PS28.pdf", kind="particular_specification", spec_section_number="28",
                          spec_section_title="Environmental Ground", text_layer=True, page_count=20)
    save_doc_index(ws, "old", [stale])
    got = _by_section(load_doc_index(ws, "old"), "28")

    assert got.spec_section_title == "Environmental Ground"
    assert got.spec_section_title_source == "page_1"      # honest about where it came from


# -- the two wrong proposals, re-examined --------------------------------------------------------------
def test_bill_9_site_safety_management_no_longer_proposes_subcontractor_management():
    """The regression this whole brief is about. "Management" matched "Site Safety Management"; the
    full title is "Management of Subcontractors", a different subject entirely."""
    p = propose_for_heading("Bill No. 9 - Site Safety Management", "9", PACK)

    assert (p.ps_section, p.ps_title) == ("27", "Construction Site Safety")
    assert p.confidence == "weak"                       # two loose words — shown as loose
    assert sorted(p.matched_on) == ["safety", "site"]
    assert "30" in [a.ps_section for a in p.alternatives], "PS 30 is still offered, ranked below"


def test_bill_5_and_bill_4_now_agree():
    """Near-identical headings proposed different specifications. They must not."""
    four = propose_for_heading("Bill No. 4 - Laboratory Testing", "4", PACK)
    five = propose_for_heading("Bill No. 5 - Laboratory Testing (Environmental Boreholes)", "5", PACK)

    assert four.ps_section == five.ps_section == "31"
    assert (four.confidence, five.confidence) == ("exact", "strong")
    assert five.ps_section != "28", "the truncated 'Environmental Ground' used to pull this away"


def test_every_proposal_names_where_its_specification_title_came_from():
    bills = {"1": "Bill No. 1 - General and Preliminaries",
             "2": "BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS",
             "4": "Bill No. 4 - Laboratory Testing",
             "7": "Bill No. 7 - Environmental Protection",
             "9": "Bill No. 9 - Site Safety Management"}
    for code, heading in bills.items():
        p = propose_for_heading(heading, code, PACK)
        assert p.ps_section, f"bill {code} lost its proposal"
        assert p.ps_title_source in ("page_1", "ps_index"), f"bill {code}: {p.ps_title_source!r}"
        assert "undeclared source" not in p.evidence


def test_the_number_trap_still_holds_with_whole_titles():
    """The rule the previous phase exists for, re-checked against complete titles."""
    p = propose_for_heading("BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS", "2", PACK)
    assert p.ps_section == "28" and p.ps_title == "Environmental Ground Investigation"
    assert "2" not in {p.ps_section} | {a.ps_section for a in p.alternatives}


# -- the two bills with no proposal, explained ----------------------------------------------------------
def test_bill_1_gets_its_weak_proposal_once_ps_1_actually_has_a_title():
    """Not stopwords. "General and Preliminaries" and "General" are both made only of common words,
    and the both-generic rule already covers that pair. It proposed nothing live because PS 1 had no
    title to match against at all."""
    assert propose_for_heading("Bill No. 1 - General and Preliminaries", "1", PACK).ps_section == "1"

    untitled = [e for e in PACK if e.spec_section_number != "1"] + [
        DocIndexEntry(filename="PS1.pdf", kind="particular_specification", spec_section_number="1",
                      text_layer=True, page_count=8)]
    assert propose_for_heading("Bill No. 1 - General and Preliminaries", "1", untitled).ps_section == ""


def test_bill_6_shares_only_a_generic_word_and_that_is_the_right_answer():
    """"Groundwater Monitoring Works" and "Geotechnical Works" share "work" and nothing else — the
    same shape as "Builders Work", which is unambiguously not the geotechnical specification.

    Widening the rule to catch this one catches that one too, and a proposal an operator learns to
    click through defeats the gate. Recorded as a deliberate refusal, not an oversight.
    """
    assert propose_for_heading("Bill No. 6 - Groundwater Monitoring Works", "6", PACK).ps_section == ""
    assert propose_for_heading("Bill No. 8 - Builders Work", "8", PACK).ps_section == ""

    # The word they share, and the only one — which is why neither can be proposed on it.
    from pipeline.stage_03_dispatch.spec_match import title_words
    assert title_words("Groundwater Monitoring Works") & title_words("Geotechnical Works") == {"work"}
