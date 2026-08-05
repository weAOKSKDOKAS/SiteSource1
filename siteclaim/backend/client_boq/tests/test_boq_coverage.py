"""What a rate must cover, and how a rate was reached.

Two modules, one rule between them: **the app assembles and cites; the person decides.**

*Coverage* is the sharper case. Reading the item coverage off the Method of Measurement is clerical —
two estimators get the same list, so a rule does it. Deciding whether *your* build-up already carries
"temporary traffic arrangements" is judgement — two estimators would disagree, so it is asked. That
is the whole test this product uses to decide what to automate, applied to the most consequential
list in the app.

*Trace* enforces the other half of the promise: every number opens. A leaf that cannot say whether it
came from a document, a person or the library is a bug, because a tree with one unattributed number
still looks complete — and looking complete is exactly the failure.
"""

from __future__ import annotations

import pytest

from client_boq.boq.allocate import RateBreakdown
from client_boq.boq.coverage import (
    BY_MODEL,
    DEEMED_INCLUDED,
    SCOPE_BILL,
    CoverageHead,
    bill_summary,
    coverage_for,
    heads_for,
)
from client_boq.boq.docmap import parse_index
from client_boq.boq.groups import HoleGroup
from client_boq.boq.schedule import Station, StationSchedule
from client_boq.boq.trace import (
    FROM_DOCUMENT,
    FROM_PERSON,
    Citation,
    TraceNode,
    trace_rate,
)
from client_boq.models import BillItem, ClientBill

INDEX = """
SECTION 7
GEOTECHNICAL WORKS

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


def _item(ref="2.4", **kwargs):
    base = {"bill_no": "2", "full_ref": ref, "qty": 2300.0, "unit": "m",
            "description": "Drilling, vertically downwards, material other than rock"}
    return BillItem(**{**base, **kwargs})


class TestTheList:
    def test_a_drilling_item_carries_the_sections_own_coverage(self):
        keys = {h.key for h in heads_for(_item())}
        assert "smm.2.13.a" in keys and "smm.2.13.h" in keys

    def test_a_rig_move_carries_the_access_scaffolding_head_the_drilling_items_do_not(self):
        # SMM S02 ¶2.08(h) puts platforms in the item coverage for MOVING rigs, not for drilling —
        # which is why a Class B platform is loaded onto 2.2b and never onto the metre rate.
        assert "smm.2.08.h" in {h.key for h in heads_for(_item("2.2b"))}
        assert "smm.2.08.h" not in {h.key for h in heads_for(_item("2.4"))}

    def test_a_head_that_cites_a_clause_resolves_to_a_page(self, docmap):
        entry = next(e for e in coverage_for(_item(), docmap=docmap).entries
                     if e.key == "ps.7.30S")
        assert entry.page == "PS7/4" and entry.document_hint == "PS7"

    def test_a_citation_the_index_does_not_have_says_so_rather_than_inventing_a_page(self):
        thin = parse_index("SECTION 7\nGEOTECHNICAL WORKS\n7.01A\nAccess scaffolding\nPS7/1\n")
        entry = next(e for e in coverage_for(_item(), docmap=thin).entries if e.key == "ps.7.30S")
        assert entry.page == ""
        assert "does not list it" in entry.unresolved

    def test_with_no_index_read_the_head_admits_it_cannot_open(self):
        entry = next(e for e in coverage_for(_item()).entries if e.key == "ps.7.30S")
        assert "has not been read" in entry.unresolved

    def test_the_thirty_one_deemed_included_heads_are_one_bill_level_line(self):
        # Thirty-one heads repeated against twenty-seven items would bury the eight that are
        # actually about this item, and the header count is only useful while it is actionable.
        coverage = coverage_for(_item())
        assert DEEMED_INCLUDED.key not in {e.key for e in coverage.entries}
        assert coverage.bill_level is not None
        assert coverage.bill_level.scope == SCOPE_BILL


class TestNothingIsEverPreTicked:
    def test_a_fresh_item_has_every_head_outstanding(self):
        coverage = coverage_for(_item())
        assert len(coverage.uncovered()) == coverage.total()
        assert not coverage.settled()

    def test_a_models_proposal_arrives_unticked_like_everything_else(self):
        # A model may WIDEN the list. It may never shorten it and it may never settle it.
        proposed = [CoverageHead(key="model.x", label="Night-work supervision",
                                 clause_ref="PS 1.11S", authored_by=BY_MODEL)]
        entry = next(e for e in coverage_for(_item(), proposed=proposed).entries
                     if e.key == "model.x")
        assert entry.authored_by == BY_MODEL and entry.ticked is False

    def test_a_tick_carries_a_name_and_a_date(self):
        ticks = {"smm.2.13.a": {"ticked": True, "ticked_by": "SW", "ticked_at": "2026-08-03"}}
        entry = next(e for e in coverage_for(_item(), ticks=ticks).entries if e.key == "smm.2.13.a")
        assert entry.covered() and entry.ticked_by == "SW" and entry.ticked_at == "2026-08-03"

    def test_the_header_counts_what_is_left(self):
        ticks = {key: {"ticked": True, "ticked_by": "SW"}
                 for key in ("smm.2.13.a", "smm.2.13.b", "smm.2.13.c")}
        coverage = coverage_for(_item(), ticks=ticks)
        assert coverage.summary() == f"{coverage.total()} heads · {coverage.total() - 3} not covered"

    def test_everything_ticked_says_so_rather_than_counting_zero(self):
        ticks = {h.key: {"ticked": True, "ticked_by": "SW"} for h in heads_for(_item())}
        assert coverage_for(_item(), ticks=ticks).summary().endswith("all covered")

    def test_unticked_heads_are_a_decision_waiting_not_an_error(self):
        # Nothing in this module blocks. The sweep is the app's only hard stop.
        coverage = coverage_for(_item())
        assert "shall not be measured" in coverage.note

    def test_a_tick_survives_a_re_read_because_it_is_keyed_to_the_head(self):
        ticks = {"smm.2.13.a": {"ticked": True, "ticked_by": "SW"}}
        first = coverage_for(_item(), ticks=ticks)
        again = coverage_for(_item(description="Drilling — reworded by an addendum"), ticks=ticks)
        assert [e.ticked for e in first.entries] == [e.ticked for e in again.entries]


class TestAcrossTheWholeBill:
    def test_the_summary_skips_parents_and_the_clients_own_priced_items(self):
        bill = ClientBill(items=[
            _item("2.2", is_parent=True), _item("2.4"),
            _item("9.1", bill_no="9", pre_priced=True),
        ])
        rows = bill_summary(bill, {})["items"]
        assert [r["full_ref"] for r in rows] == ["2.4"]

    def test_it_totals_what_is_still_outstanding(self):
        bill = ClientBill(items=[_item("2.4"), _item("2.5")])
        summary = bill_summary(bill, {})
        assert summary["settled"] == 0
        assert summary["outstanding"] == 2 * len(heads_for(_item("2.4")))


class TestTheDerivationTree:
    def _breakdown(self, **kwargs):
        base = {"full_ref": "2.4", "label": "Drilling", "rate": 1104.15, "cost": 2_539_545.0,
                "divisor": 2300.0, "divisor_label": "m", "markup_pct": 15.0}
        return RateBreakdown(**{**base, **kwargs})

    def test_a_rate_is_shown_as_a_division_not_as_a_number(self):
        trace = trace_rate(self._breakdown(), unit="m", qty=2300.0, amount=2_539_545.0)
        assert trace.root is not None and trace.root.op == "÷"
        assert [c.label for c in trace.root.children] == ["cost", "m"]

    def test_the_extension_check_passes_when_the_arithmetic_holds(self):
        trace = trace_rate(self._breakdown(), unit="m", qty=2300.0, amount=2_539_545.0)
        assert trace.extension_checks()
        assert any("extension checks" in c for c in trace.checks)

    def test_an_extension_that_does_not_check_is_reported_with_both_numbers(self):
        trace = trace_rate(self._breakdown(), unit="m", qty=2300.0, amount=9_999.0)
        assert not trace.extension_checks()
        assert any("does not check" in p for p in trace.problems)

    def test_the_margin_is_a_persons_decision_and_carries_their_name(self):
        trace = trace_rate(self._breakdown(), margin_pct=15.0, margin_owner="J. Dai",
                           margin_at="3 Aug")
        margin = next(n for n in trace.root.leaves() if "margin" in n.label)
        assert margin.origin == FROM_PERSON and margin.owner == "J. Dai"

    def test_the_sweep_spread_is_its_own_line_inside_the_rate(self):
        # It has to be inside the rate — you cannot tender "plus 52,000" — and it has to be visible,
        # because a spread hidden in a metre rate is the thing this screen exists to expose.
        trace = trace_rate(self._breakdown(), margin_owner="J. Dai",
                           spread_share=12_340.0, spread_total=52_000.0)
        share = next(n for n in trace.root.leaves() if n.label == "spread share")
        assert share.value == 12_340.0
        assert "not hiding in the metres" in share.note

    def test_a_blended_rate_names_which_group_is_carrying_it(self):
        breakdown = self._breakdown(groups=[
            {"group": "Roadside", "cost": 1_540_200.0, "divisor": 1780.0, "days": 1},
            {"group": "Hillside", "cost": 668_100.0, "divisor": 520.0, "days": 1},
        ])
        groups = [HoleGroup(label="Roadside", stations=["a"] * 68),
                  HoleGroup(label="Hillside", stations=["b"] * 23)]
        trace = trace_rate(breakdown, groups=groups)
        build_up = trace.root.children[0].children[0]
        assert [c.label for c in build_up.children] == ["Roadside", "Hillside"]
        assert "68 holes" in build_up.children[0].note

    def test_the_divisor_says_which_drawing_it_came_from(self):
        schedule = StationSchedule(
            set_id="t", source_sheet="60740338/GI/210",
            stations=[Station(station="A", soil_m=30.0, length_m=30.0)])
        trace = trace_rate(self._breakdown(), unit="m", schedule=schedule,
                           divisor_cite=Citation(part_id="09-DRG", page=3, label="GI/210"))
        divisor = trace.root.children[1]
        assert divisor.origin == FROM_DOCUMENT and divisor.cite.part_id == "09-DRG"
        assert "GI/210" in divisor.note

    def test_a_lump_item_says_the_amount_is_the_rate(self):
        trace = trace_rate(self._breakdown(lump=True, rate=47_349.6), unit="item")
        assert "the amount IS the rate" in trace.root.note

    def test_an_unpriced_item_names_what_silence_costs(self):
        trace = trace_rate(self._breakdown(rate=None, divisor=0.0), unit="m", qty=100.0)
        assert any("free" in p and "General Preambles" in p for p in trace.problems)


class TestEveryNumberOpens:
    """The check that keeps the screen's promise. A tree with one unattributed leaf still looks
    complete, and looking complete is the failure."""

    def test_a_document_leaf_with_no_page_is_reported(self):
        node = TraceNode(label="2,300 m", value=2300.0, origin=FROM_DOCUMENT)
        assert "names no page" in node.unsupported()[0]

    def test_a_persons_decision_with_nobody_on_it_is_reported(self):
        node = TraceNode(label="× 1.15 margin", value=15.0, origin=FROM_PERSON)
        assert "nobody's name is on it" in node.unsupported()[0]

    def test_a_bare_number_at_the_bottom_of_the_tree_is_reported(self):
        node = TraceNode(label="something", value=42.0)
        assert "bare number with nothing behind it" in node.unsupported()[0]

    def test_a_complete_tree_reports_nothing(self):
        node = TraceNode(label="rate", op="÷", children=[
            TraceNode(label="cost", value=100.0, origin=FROM_PERSON, owner="SW"),
            TraceNode(label="m", value=10.0, origin=FROM_DOCUMENT,
                      cite=Citation(part_id="09-DRG", page=3)),
        ])
        assert node.unsupported() == []

    def test_a_real_trace_is_fully_attributed(self):
        trace = trace_rate(
            RateBreakdown(
                full_ref="2.4", rate=1104.15, cost=2_539_545.0, divisor=2300.0, divisor_label="m",
                terms=[{"label": "Rotary rig", "key": "rig", "units": 15.0,
                        "unit_cost": 615.0, "value": 9225.0}]),
            unit="m", qty=2300.0, amount=2_539_545.0, margin_pct=15.0, margin_owner="J. Dai",
            divisor_cite=Citation(part_id="09-DRG", page=3, label="GI/210"))
        assert trace.problems == []

    def test_a_build_up_with_nothing_under_it_is_reported_rather_than_shown(self):
        # A breakdown carrying neither resource terms nor groups leaves "build-up" standing as a
        # number with no derivation. That is precisely the shape this check exists to refuse — the
        # screen's promise is that every number opens, and this one does not.
        trace = trace_rate(RateBreakdown(full_ref="2.4", rate=1.0, cost=100.0, divisor=100.0),
                           unit="m", qty=100.0, amount=100.0)
        assert any("build-up" in p and "nothing behind it" in p for p in trace.problems)
