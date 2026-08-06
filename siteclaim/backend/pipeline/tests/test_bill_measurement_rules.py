"""What the bill DOES point at, and the invariant that keeps everything else closed.

FINDING 1, settled: this issuer's Bill of Quantities has no Clause Ref column. Page 9 of
`BQ/I-ND_2025_04_BQ-0.pdf` is `Item No. | Item Description | Quantity | Unit | Rate | Amount`.
`clause_refs: []` is the correct answer here, permanently — this issuer's shape, not a defect.

FINDING 2: every bill page names the Method-of-Measurement section its items are measured under,
and every one of those ships in `GP&PP/`. Ten for ten on the real pack. That is the pointer the
bill carries, and nothing followed it — the MM branch fired only on `pb_clauses`, which this bill
does not have.

**This match is number-to-number, and it is correct, because BOTH numbers are SMM numbers.** It is
not the Particular Specification case: Bill 9 heads `SECTION 28` (SMM 28, Site Safety Management)
while PS 28 is *Environmental Ground Investigation*. The two rules must never be merged, and the
test at the bottom of this file is what says so.

FINDING 4: anything selected by CLAUSE REFERENCE is closed when there are no clause references.
`appendix_relevant_specs` subtracted only on the fallback path, so under a confirmed map all 25
appendices of PS 1 qualified — narrowed by nothing.

Fixtures, not the real pack: these are that bill's page SHAPE and that directory's NAME shape,
written by hand from what was read out of the pack.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    _FILENAME_SECTION,
    _kind_for,
    _own_name,
    bill_mm_sections,
)
from pipeline.stage_03_dispatch.relevant_docs import (
    NO_RELEVANCE_ESTABLISHED,
    resolve_section_plan,
)
from schemas.models import DocType, SorItem

# The bill's own pages: a bill header, then the measurement section it is priced under.
BQ_PAGES = [
    "Bill No. 1 - General and Preliminaries\nMeasurement shall be in accordance with:\n"
    "SECTION 1 : PRELIMINARIES\nSECTION 3 : SITE CLEARANCE\n1.1 Provide performance bond\n",
    "BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS\nSECTION 2 : GROUND INVESTIGATION\n"
    "2.1 Mobilisation of drilling plant\n",
    "Bill No.3 Laboratory Testing\nSECTION 2 : GROUND INVESTIGATION\n3.1 Triaxial test\n",
    "Bill No. 4 - Laboratory Testing\nSECTION 2 : GROUND INVESTIGATION\n",
    "Bill No. 5 - Laboratory Testing (Environmental Boreholes)\nSECTION 2 : GROUND INVESTIGATION\n",
    "Bill No. 6 - Groundwater Monitoring Works\nSECTION 2 : GROUND INVESTIGATION\n",
    "Bill No. 7 - Environmental Protection\nSECTION 24 : LANDSCAPE SOFTWORKS\n",
    "Bill No. 8 - Builders Work\nSECTION 29 : BUILDERS WORK\n",
    "Bill No. 9 - Site Safety Management\nSECTION 28 : SITE SAFETY MANAGEMENT\n",
]
# The pairs read out of the real pack, verbatim.
PAIRS = {"1": ["1", "3"], "2": ["2"], "3": ["2"], "4": ["2"], "5": ["2"],
         "6": ["2"], "7": ["24"], "8": ["29"], "9": ["28"]}

BQ = DocIndexEntry(filename="BQ/I-ND_2025_04_BQ-0.pdf", kind="schedule_of_rates", text_layer=True,
                   page_count=9, bill_mm_sections=bill_mm_sections(BQ_PAGES),
                   sor_section_pages={str(i + 1): [i] for i in range(9)})


def _smm(n: str, pages: int = 30) -> DocIndexEntry:
    path = f"GP&PP/SMM_S{int(n):02d}-0.pdf"
    return DocIndexEntry(filename=path, kind=_kind_for(DocType.PARTICULAR_SPECIFICATION, "", path),
                         spec_section_number=n, text_layer=True, page_count=pages)


SMM = [_smm(n) for n in ("1", "2", "3", "24", "28", "29")]
PS1 = DocIndexEntry(filename="S/PS/PS1/I-ND_2025_04-S_PS1-0.pdf", kind="particular_specification",
                    spec_section_number="1", spec_section_title="General",
                    spec_section_title_source="ps_index", text_layer=True, page_count=101)
PS1_APPENDICES = [
    DocIndexEntry(filename=f"S/PS/PS1/I-ND_2025_04-S_PSA1.{i:02d}-0.pdf", kind="appendix",
                  spec_section_number="1", text_layer=True, page_count=4)
    for i in range(1, 26)
]
PACK = [BQ, *SMM, PS1, *PS1_APPENDICES]


def _plan(sections, *, confirmed=None, clause_refs=(), index=None):
    return resolve_section_plan(
        package_key=f"pkg:{sections[0]}", trade="ground_investigation", section_title="x",
        section=sections[0], sections=list(sections),
        items=[SorItem(item_ref=f"{sections[0]}.1", description="Moving rigs", section=sections[0],
                       clause_refs=list(clause_refs))],
        doc_index=list(PACK if index is None else index), sor_sheet_name="SoR.xlsx",
        confirmed_ps_specs=confirmed,
    )


def _docs(plan):
    return {a.source_doc for a in plan.attachments}


# -- FINDING 2: the bill names its measurement section -------------------------------------------
def test_the_ten_bill_to_smm_pairs_from_the_real_pack_resolve():
    assert bill_mm_sections(BQ_PAGES) == PAIRS


@pytest.mark.parametrize("number", ["1", "2", "3", "24", "28", "29"])
def test_a_gp_and_pp_smm_file_is_indexed_as_a_method_of_measurement(number):
    path = f"GP&PP/SMM_S{int(number):02d}-0.pdf"
    assert _kind_for(DocType.PARTICULAR_SPECIFICATION, "", path) == "method_of_measurement"
    m = _FILENAME_SECTION.search(_own_name(path))
    assert m and m.group(1) == number, "the SMM section comes from the filename, no title matching"


@pytest.mark.parametrize("bill,expected", [
    ("2", {"GP&PP/SMM_S02-0.pdf"}),
    ("7", {"GP&PP/SMM_S24-0.pdf"}),
    ("9", {"GP&PP/SMM_S28-0.pdf"}),
    ("8", {"GP&PP/SMM_S29-0.pdf"}),
    ("1", {"GP&PP/SMM_S01-0.pdf", "GP&PP/SMM_S03-0.pdf"}),   # a bill may name more than one
])
def test_the_dispatched_bill_encloses_the_measurement_rules_it_is_priced_under(bill, expected):
    enclosed = {d for d in _docs(_plan([bill])) if d.startswith("GP&PP/")}
    assert enclosed == expected


def test_the_reason_says_where_the_pairing_came_from_and_how_big_it_is():
    att = next(a for a in _plan(["2"]).attachments if a.source_doc == "GP&PP/SMM_S02-0.pdf")
    assert "Method of Measurement Section 2" in att.reason
    assert "Bill 2 is priced under" in att.reason
    assert "the bill's own pages" in att.reason
    assert "30 pages" in att.reason


def test_a_named_measurement_section_the_pack_does_not_supply_is_named_never_dropped():
    without_smm2 = [e for e in PACK if e.filename != "GP&PP/SMM_S02-0.pdf"]
    plan = _plan(["2"], index=without_smm2)

    assert not any(d.startswith("GP&PP/SMM_S02") for d in _docs(plan))
    assert any(m.spec == "Method of Measurement Section 2" for m in plan.missing_specs)
    assert any("no matching SMM document in the pack" in m.referenced_by for m in plan.missing_specs)


def test_a_bill_that_names_no_measurement_section_encloses_none():
    quiet = DocIndexEntry(filename="BQ/quiet.pdf", kind="schedule_of_rates", text_layer=True,
                          page_count=1, bill_mm_sections={})
    plan = _plan(["2"], index=[quiet, *SMM])
    assert not any(d.startswith("GP&PP/") for d in _docs(plan))
    assert not any("Method of Measurement" in m.spec for m in plan.missing_specs)


def test_a_section_line_before_any_bill_header_belongs_to_no_bill():
    """Front matter, not a bill's measurement rules. `SECTION 24` on the contents page ahead of
    Bill 2 must not become Bill 2's — the pass attributes only what follows a bill it has opened."""
    pages = ["SECTION 24 : LANDSCAPE SOFTWORKS\nBill No. 2 - Ground Investigation\n"
             "SECTION 2 : GROUND INVESTIGATION\n"]
    assert bill_mm_sections(pages) == {"2": ["2"]}


def test_a_letter_coded_section_is_a_schedule_of_rates_section_not_an_smm_number():
    """`SECTION A : PRELIMINARIES ITEMS` in a Schedule of Rates is a section OF that document."""
    assert bill_mm_sections(["Bill No. 1\nSECTION A : PRELIMINARIES ITEMS\n"]) == {}


def test_the_measurement_rules_ride_under_every_relevance_source():
    """A heading is not a clause, so the clause-reference invariant does not close this branch."""
    for label, kwargs in [("none", {}), ("confirmed_map", {"confirmed": {"1"}}),
                          ("clause_refs", {"clause_refs": ["PS 1.02"]})]:
        plan = _plan(["2"], **kwargs)
        assert "GP&PP/SMM_S02-0.pdf" in _docs(plan), label


# -- FINDING 4: the clause-reference invariant ------------------------------------------------------
def test_under_a_confirmed_map_no_appendix_is_enclosed():
    """The flood: all 25 appendices of PS 1 qualified because the subtraction only ran on the
    fallback path. An appendix is selected by citation, and this bill cites nothing."""
    plan = _plan(["1"], confirmed={"1"})

    assert PS1.filename in _docs(plan)                    # the section itself, selected
    assert not any(d.startswith("S/PS/PS1/I-ND_2025_04-S_PSA") for d in _docs(plan))


def test_the_withheld_appendices_are_counted_named_and_given_their_page_total():
    """Withheld is not absent. An operator has to be able to see the size of what narrowing would
    have sent, and choose."""
    note = next(m for m in _plan(["1"], confirmed={"1"}).missing_specs
                if "appendices of PS 1" in m.spec)

    assert "25 appendices of PS 1 available, not enclosed" in note.spec
    assert "(100 pages)" in note.spec
    assert "no clause reference narrows them" in note.spec


def test_under_the_whole_specification_fallback_no_appendix_is_enclosed_either():
    plan = _plan(["1"], confirmed=None)
    assert plan.relevance_source == "none"
    assert not any("PSA" in d for d in _docs(plan))


def test_under_clause_refs_the_appendix_branch_is_open_exactly_as_before():
    """The invariant closes a branch when there are no clauses. It must not close one when there
    are — this is the path the whole resolver was built for."""
    plan = _plan(["1"], clause_refs=["PS 1.02", "Appendix 1.03"])
    assert plan.relevance_source == "clause_refs"
    assert any("PSA1" in d for d in _docs(plan))
    assert not any("appendices of PS 1 available" in m.spec for m in plan.missing_specs)


def test_the_whole_specification_enclosure_states_its_page_count():
    """PS 1 is 101 pages. Whole-document enclosure is not free and the gate should say so."""
    att = next(a for a in _plan(["1"], confirmed=None).attachments if a.source_doc == PS1.filename)
    assert "(101 pages)" in att.reason and NO_RELEVANCE_ESTABLISHED in att.flags


def test_a_confirmed_selection_states_its_page_count_too():
    att = next(a for a in _plan(["1"], confirmed={"1"}).attachments if a.source_doc == PS1.filename)
    assert "(101 pages)" in att.reason and "CONFIRMED specification map" in att.reason


# -- the two rules that must never be merged ----------------------------------------------------------
def test_the_bill_number_matches_an_smm_number_and_never_a_ps_number():
    """Bill 9 names SMM 28 — Site Safety Management — and PS 28 is Environmental Ground
    Investigation. The SMM pairing is number-to-number and right; the PS pairing is by title and
    needs a human. Enclosing PS 28 off Bill 9's `SECTION 28` line would be the exact trap.
    """
    ps28 = DocIndexEntry(filename="S/PS/PS28/I-ND_2025_04-S_PS28-0.pdf",
                         kind="particular_specification", spec_section_number="28",
                         spec_section_title="Environmental Ground Investigation",
                         spec_section_title_source="ps_index", text_layer=True, page_count=40)
    docs = _docs(_plan(["9"], confirmed={"27"}, index=[BQ, *SMM, ps28]))

    assert "GP&PP/SMM_S28-0.pdf" in docs, "SMM 28 is what Bill 9 names"
    assert ps28.filename not in docs, "PS 28 is a different document with the same number"
