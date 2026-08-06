"""The machine proposes which specification governs which bill — on the TITLE, never the number.

Phase 1 recovered the bill's section heading past a page break; phase 2 filled `spec_section_title`
from the issuer's own index. This is the join, and it is a PROPOSAL: nothing here confirms anything,
and `test_spec_map_gate.py` pins that an unconfirmed proposal selects nothing.

THE TRAP, on this pack's real numbers: PS **2** is *Site Clearance*, PS **28** is *Environmental
Ground Investigation*, and the bill headed "Ground Investigation" is **Bill 2**. A number-to-number
match encloses site clearance for a drilling package. So the leading `SECTION n` token is stripped
deliberately and the number plays no part in the match.

The eleven PS titles are the real page-3 contents parsed by `parse_ps_index` (see
`test_ps_index.py`) — not retyped here, so the two tests cannot drift apart. The bill headings are
the shapes this pack is known to use.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry, parse_ps_index
from pipeline.stage_03_dispatch.spec_match import (
    SpecProposal,
    bill_headings_from_scope,
    propose_for_heading,
    propose_spec_map,
    strip_bill_number,
    title_words,
)
from pipeline.tests.test_ps_index import PAGE_3
from schemas.models import SectionMeta, SorItem, TradeWorkPackage


def _ps_index() -> list[DocIndexEntry]:
    """The pack's eleven PS sections as they arrive after phase 2: a number from the filename, a
    title from the index, and the provenance that says so."""
    titles, _unreadable = parse_ps_index([PAGE_3])
    return [DocIndexEntry(filename=f"S/PS/PS{n}/I-ND_2025_04-S_PS{n}-0.pdf",
                          kind="particular_specification", spec_section_number=n,
                          spec_section_title=t, spec_section_title_source="ps_index",
                          text_layer=True, page_count=10)
            for n, t in titles.items()]


IDX = _ps_index()


# -- the number is discarded, deliberately and visibly ---------------------------------------------
@pytest.mark.parametrize("heading,title,number", [
    ("SECTION 2 - GROUND INVESTIGATION", "GROUND INVESTIGATION", "2"),
    ("BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS", "GROUND INVESTIGATION FIELDWORKS", "2"),
    ("Bill No. 1 - General and Preliminaries", "General and Preliminaries", "1"),
    ("Bill No.3 Laboratory Testing", "Laboratory Testing", "3"),
    ("Builders Work", "Builders Work", ""),          # no leading number — untouched
    ("SECTION 28 – ENVIRONMENTAL GROUND INVESTIGATION", "ENVIRONMENTAL GROUND INVESTIGATION", "28"),
])
def test_the_leading_bill_number_is_stripped_and_returned(heading, title, number):
    assert strip_bill_number(heading) == (title, number)


def test_the_number_that_was_discarded_is_reported_not_hidden():
    """Stripping quietly would leave an operator unable to tell a considered decision from a bug."""
    p = propose_for_heading("SECTION 2 - GROUND INVESTIGATION", "2", IDX)
    assert p.discarded_number == "2"
    assert p.bill_heading == "SECTION 2 - GROUND INVESTIGATION"   # verbatim, still shown
    assert p.bill_title == "GROUND INVESTIGATION"
    assert "not a specification number" in p.evidence


# -- the trap this whole phase exists to avoid ------------------------------------------------------
@pytest.mark.parametrize("heading", [
    "SECTION 2 - GROUND INVESTIGATION",
    "BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS",
    "Bill No. 2 - Ground Investigation Fieldworks",
])
def test_bill_2_proposes_ps_28_and_never_ps_2(heading):
    """The pack's own counter-example. PS 2 exists, is titled *Site Clearance*, and is wrong."""
    p = propose_for_heading(heading, "2", IDX)

    assert p.ps_section == "28"
    assert p.ps_title == "Environmental Ground Investigation"
    assert p.confidence == "strong"
    assert p.matched_on == ["ground", "investigation"]
    assert p.ps_section != p.bill_section
    assert "2" not in [a.ps_section for a in p.alternatives]


def test_site_clearance_is_never_offered_for_a_ground_investigation_bill():
    p = propose_for_heading("SECTION 2 - GROUND INVESTIGATION", "2", IDX)
    offered = {p.ps_section} | {a.ps_section for a in p.alternatives}
    assert "2" not in offered, "PS 2 is Site Clearance — the number matched, the work does not"


# -- the tiers -------------------------------------------------------------------------------------
def test_an_identical_title_is_exact():
    p = propose_for_heading("Bill No.3 Laboratory Testing", "3", IDX)
    assert (p.ps_section, p.confidence) == ("31", "exact")
    assert p.ps_title == "Laboratory Testing"


def test_containment_is_strong_but_still_only_a_proposal():
    """"Ground Investigation" ⊂ "Environmental Ground Investigation". Strong is the top tier a
    non-identical pair can reach, and it confirms nothing by itself."""
    p = propose_for_heading("SECTION 2 - GROUND INVESTIGATION", "2", IDX)
    assert p.confidence == "strong"


def test_a_weak_match_presents_as_weak():
    """"General and Preliminaries" against PS 1 "General" — real, and the thinnest thing the
    matcher will say. It must not arrive looking like an answer."""
    p = propose_for_heading("Bill No. 1 - General and Preliminaries", "1", IDX)
    assert (p.ps_section, p.confidence) == ("1", "weak")
    assert p.matched_on == ["general"]
    assert "weak" in p.evidence


def test_a_generic_word_alone_carries_no_proposal_at_all():
    """"Builders Work" and PS 7 "Geotechnical Works" share "work" and nothing else.

    Offering that as a weak candidate would invite a confirming click on a match with no content —
    worse than saying nothing, because it looks like the machine found something.
    """
    p = propose_for_heading("Builders Work", "5", IDX)
    assert p.ps_section == "" and p.confidence == "none"
    assert p.alternatives == []
    assert "no specification section shares a distinctive word" in p.evidence


def test_a_bill_section_with_no_heading_says_so_rather_than_matching_nothing_to_something():
    p = propose_for_heading("", "6", IDX)
    assert p.confidence == "none"
    assert "declares no heading" in p.evidence


# -- the evidence an operator reads -----------------------------------------------------------------
def test_the_proposal_carries_everything_needed_to_disagree_with_it():
    p = propose_for_heading("BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS", "2", IDX)

    assert p.bill_heading and p.bill_title and p.discarded_number == "2"
    assert p.ps_title == "Environmental Ground Investigation"
    assert p.ps_title_source == "ps_index"          # provenance carried through from phase 2
    assert p.ps_document.endswith("S_PS28-0.pdf")
    assert p.matched_on and p.confidence == "strong"
    for fragment in ("GROUND INVESTIGATION FIELDWORKS", "Environmental Ground Investigation",
                     "ground, investigation", "ps_index"):
        assert fragment in p.evidence


def test_a_page_one_title_is_reported_as_such():
    """Provenance is not decoration: a title the document states about itself is different evidence
    from one the pack's index states about it, and the operator is shown which."""
    idx = [DocIndexEntry(filename="PS28.pdf", kind="particular_specification",
                         spec_section_number="28", spec_section_title="Ground Investigation",
                         spec_section_title_source="page_1", text_layer=True, page_count=4)]
    p = propose_for_heading("SECTION 2 - GROUND INVESTIGATION", "2", idx)
    assert p.ps_title_source == "page_1" and "page_1" in p.evidence


def test_a_specification_with_no_title_cannot_be_proposed():
    """Phase 2 fills what it can; a section it could not name has nothing to match on and is not
    offered on the strength of its number."""
    idx = [DocIndexEntry(filename="PS28.pdf", kind="particular_specification",
                         spec_section_number="28", text_layer=True, page_count=4)]
    assert propose_for_heading("SECTION 28 - GROUND INVESTIGATION", "28", idx).confidence == "none"


# -- the whole map ------------------------------------------------------------------------------------
def test_every_bill_section_appears_including_the_ones_with_no_counterpart():
    """A map that omits what it could not match reads as complete when it is not."""
    headings = {"1": "Bill No. 1 - General and Preliminaries",
                "2": "BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS",
                "3": "Bill No.3 Laboratory Testing",
                "5": "Bill No. 5 - Builders Work"}
    out = propose_spec_map(headings, IDX)

    assert [p.bill_section for p in out] == ["1", "2", "3", "5"]      # bill order, numerically
    assert {p.bill_section: (p.ps_section, p.confidence) for p in out} == {
        "1": ("1", "weak"), "2": ("28", "strong"), "3": ("31", "exact"), "5": ("", "none")}


def test_the_map_is_deterministic():
    a = [p.model_dump() for p in propose_spec_map({"2": "SECTION 2 - GROUND INVESTIGATION"}, IDX)]
    b = [p.model_dump() for p in propose_spec_map({"2": "SECTION 2 - GROUND INVESTIGATION"},
                                                  list(reversed(IDX)))]
    assert a == b, "the answer must not depend on the order the doc index was built in"


def test_an_empty_doc_index_proposes_nothing_and_does_not_raise():
    out = propose_spec_map({"2": "SECTION 2 - GROUND INVESTIGATION"}, [])
    assert [p.confidence for p in out] == ["none"]


# -- where the bill heading comes from ----------------------------------------------------------------
def test_the_bill_header_row_is_the_heading_when_the_chunker_captured_one():
    pkg = TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sections=[SectionMeta(code="2", title="GROUND INVESTIGATION FIELDWORKS", item_count=3)],
        sor_items=[SorItem(item_ref="2.1", section="2", description="Mobilisation")])
    assert bill_headings_from_scope(pkg) == {"2": "GROUND INVESTIGATION FIELDWORKS"}


def test_the_recovered_heading_path_is_the_fallback_when_no_header_row_was_captured():
    """Phase 1's contribution, used. Before `running_furniture`, every item past a section's first
    page carried the page title instead of its section heading — so this fallback would have
    proposed a match against the project name."""
    pkg = TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sections=[SectionMeta(code="2", title="", item_count=1)],
        sor_items=[SorItem(item_ref="2.2", section="2", description="Rotary drilling",
                           heading_path=["SECTION 2 - GROUND INVESTIGATION",
                                         "Ground Investigation Fieldworks"])])
    headings = bill_headings_from_scope(pkg)

    assert headings == {"2": "SECTION 2 - GROUND INVESTIGATION"}
    assert propose_for_heading(headings["2"], "2", IDX).ps_section == "28"


def test_a_package_with_neither_source_contributes_no_heading():
    pkg = TradeWorkPackage(trade="x", scope_summary="", sections=[SectionMeta(code="9")],
                           sor_items=[SorItem(item_ref="9.1", section="9")])
    assert bill_headings_from_scope(pkg) == {}


# -- the normaliser ------------------------------------------------------------------------------------
@pytest.mark.parametrize("a,b", [
    ("GROUND INVESTIGATION", "Ground Investigation"),        # case
    ("Ground Investigation", "Ground  Investigation"),       # spacing
    ("Geotechnical Works", "Geotechnical Work"),             # plural
    ("Preservation and Protection of Trees", "Preservation Protection Tree"),  # function words
])
def test_two_spellings_of_one_title_reduce_to_the_same_words(a, b):
    assert title_words(a) == title_words(b)


def test_the_proposal_is_a_plain_model_with_no_verdict_field():
    """Structurally unable to confirm itself — the same rule `DepartureProposal` follows in
    client_boq. A `confirmed` flag here would eventually be set by something that is not a person.
    """
    assert not {"confirmed", "approved", "status"} & set(SpecProposal.model_fields)
