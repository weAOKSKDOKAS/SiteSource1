"""The specification index, and the gate on costs the bill has no item for.

Two rules, both about not letting something disappear.

**The index** turns a clause citation into a page, so the chain *bill item → item coverage → cited
clause → page* can be walked instead of hunted. It reports what it cannot parse — including a
contradiction in the client's own index, which is a real defect on the reference contract and not
something to quietly correct.

**The sweep** refuses to let a believed cost go unrouted, because on this contract silence is not
neutral:

    General Preambles ¶6 — "Items against which no rate is entered shall be deemed to be covered by
    the other rates in the bill of quantities."

An unpriced cost is not an open question. It is a promise to do that work for nothing, for the life of
a remeasured contract. So the estimator must choose: query it, load it onto a named item, spread it,
or accept it as a stated risk. Doing nothing is the one option the gate removes.
"""

from __future__ import annotations

import pytest

from client_boq.boq.docmap import parse_index
from client_boq.boq.unbilled import (
    ROUTE_ACCEPT,
    ROUTE_LOAD,
    ROUTE_QUERY,
    ROUTE_SPREAD,
    UnbilledCost,
    UnbilledSweep,
    UnroutedCost,
    gate,
)

# A faithful miniature of the real index's layout: ref / title (sometimes wrapped) / page.
INDEX = """
SECTION 1
GENERAL

CONTRACTOR'S SUPERINTENDENCE

1.11S
Contractor's supervision and personnel for ground investigation field
works
PS1/8
1.12E
Site Supervision Requirement for Geotechnical Works
PS1/15
Appendix 1.12
Furniture and Equipment for Project Manager's Site Accommodation

SECTION 7
GEOTECHNICAL WORKS

GENERAL

7.01A
Access scaffolding
PS7/1
7.01B
Moving Rigs
PS7/2
7.30S
Inspection Pits
PS7/4
7.45D
Depth of Investigation Holes
PS7/12
"""


@pytest.fixture(scope="module")
def docmap():
    return parse_index(INDEX, source="PS_Index")


class TestTheSpecificationIndex:
    def test_it_finds_the_sections_and_their_clauses(self, docmap):
        assert docmap.sections == {"1": "GENERAL", "7": "GEOTECHNICAL WORKS"}
        assert len(docmap.in_section("7")) == 4

    def test_a_wrapped_title_is_joined_not_split(self, docmap):
        entry = docmap.resolve("1.11S")
        assert entry.title == ("Contractor's supervision and personnel for ground investigation "
                               "field works")

    @pytest.mark.parametrize("citation", ["7.30S", "PS Clause 7.30S", "clause 7.30S", " 7.30S. "])
    def test_a_clause_resolves_however_a_document_cites_it(self, docmap, citation):
        entry = docmap.resolve(citation)
        assert entry.ref == "7.30S" and entry.page == "PS7/4"

    def test_a_citation_to_the_numbered_parent_still_lands(self, docmap):
        # A document that says "clause 7.30" when the index only lists 7.30S should not come back empty.
        assert docmap.resolve("7.30").ref == "7.30S"

    def test_the_page_reference_names_the_file_to_open(self, docmap):
        assert docmap.resolve("7.45D").document_hint() == "PS7"
        assert docmap.resolve("1.12E").document_hint() == "PS1"

    def test_an_entry_with_no_printed_page_is_kept_not_dropped(self, docmap):
        # The real index prints no page for several appendices. Losing them would make the map
        # quietly incomplete, which is worse than an entry with a blank page.
        entry = docmap.resolve("Appendix 1.12")
        assert entry is not None and entry.page == ""
        assert entry.document_hint() == "PS1"

    def test_an_unknown_clause_returns_nothing_rather_than_a_guess(self, docmap):
        assert docmap.resolve("99.99Z") is None

    def test_a_scanned_index_says_so_instead_of_returning_an_empty_map(self):
        empty = parse_index("   \n \n")
        assert empty.entries == []
        assert any("may be a scan" in note for note in empty.notes)

    def test_two_sections_with_one_title_is_reported_not_corrected(self):
        # Real defect on the reference contract: the index heads SECTION 28 with section 29's title,
        # while its own clauses and the contents page both say Environmental Ground Investigation.
        clashing = parse_index("SECTION 28\nPAYMENT OF WAGES\n28.01\nGeneral\nPS28/1\n"
                               "SECTION 29\nPAYMENT OF WAGES\n29.01\nGeneral\nPS29/1\n")
        assert any("both headed" in note and "mislabelled" in note for note in clashing.notes)


def _cost(**kwargs) -> UnbilledCost:
    base = {"key": "traffic", "label": "Temporary traffic arrangements",
            "source": "SMM S02 ¶2.13(h)", "amount": 40000.0}
    return UnbilledCost(**{**base, **kwargs})


class TestTheUnbilledSweep:
    def test_an_unrouted_cost_blocks_and_says_what_silence_costs(self):
        sweep = UnbilledSweep(costs=[_cost()])
        with pytest.raises(UnroutedCost) as raised:
            gate(sweep)
        message = str(raised.value)
        assert "Temporary traffic arrangements" in message
        assert "General Preambles ¶6" in message and "for free" in message

    def test_each_of_the_four_routes_settles_it(self):
        for route, extra in ((ROUTE_QUERY, {}), (ROUTE_SPREAD, {}),
                             (ROUTE_LOAD, {"target_ref": "2.4"}),
                             (ROUTE_ACCEPT, {"reason": "we think the PM will instruct it"})):
            gate(UnbilledSweep(costs=[_cost(route=route, **extra)]))   # must not raise

    def test_loading_onto_nothing_is_not_a_route(self):
        with pytest.raises(UnroutedCost, match="no item named"):
            gate(UnbilledSweep(costs=[_cost(route=ROUTE_LOAD)]))

    def test_a_risk_accepted_without_a_reason_is_refused(self):
        # A risk somebody took deliberately and one nobody noticed look identical six months later.
        with pytest.raises(UnroutedCost, match="no reason recorded"):
            gate(UnbilledSweep(costs=[_cost(route=ROUTE_ACCEPT)]))

    def test_an_invented_route_is_named_with_the_real_ones(self):
        with pytest.raises(UnroutedCost, match="is not a route"):
            gate(UnbilledSweep(costs=[_cost(route="ignore")]))

    def test_the_sweep_totals_what_each_route_carries(self):
        sweep = UnbilledSweep(costs=[
            _cost(key="uniform", label="Site uniform", amount=12000.0, route=ROUTE_SPREAD),
            _cost(key="smp", label="Subcontractor Management Plan", amount=8000.0,
                  route=ROUTE_SPREAD),
            _cost(key="platform", label="Access platform", amount=210000.0, route=ROUTE_LOAD,
                  target_ref="2.2b"),
            _cost(key="heli", label="Helicopter access, ABH244", amount=None, route=ROUTE_QUERY),
            _cost(key="rock", label="Harder ground than billed", amount=50000.0,
                  route=ROUTE_ACCEPT, reason="the historical logs suggest more rock than 20%"),
        ])
        assert sweep.settled()
        assert sweep.spread_total() == 20000.0
        assert sweep.loadings() == {"2.2b": 210000.0}
        assert [c.label for c in sweep.queries()] == ["Helicopter access, ABH244"]
        assert sweep.accepted_risk() == 50000.0

    def test_a_queried_cost_needs_no_amount_yet(self):
        # You raise the question before you know what the answer costs.
        gate(UnbilledSweep(costs=[_cost(amount=None, route=ROUTE_QUERY)]))

    def test_every_outstanding_item_is_listed_not_just_the_first(self):
        sweep = UnbilledSweep(costs=[_cost(key="a", label="A"), _cost(key="b", label="B")])
        assert len(sweep.outstanding()) == 2
