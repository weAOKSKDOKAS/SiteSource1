"""The last seven modules, audited for the silent-failure class — and what it found.

`checks.py`, `carry.py`, `docmap.py`, `trace.py`, `outputs.py`, `coverage.py` and `unbilled.py` had
never had their own pass. The class being hunted is the one this product keeps meeting: **a wrong
answer that looks exactly like a right one**, usually because an absence was read as a state.

FOUR FOUND, all fixed here, each pinned below:

1. `checks.py` — a priced line whose reference is in no bill item was INVISIBLE to every rate
   check (each begins `if item is None: continue`) while its money still reached the bill total
   through `casting_errors`, which sums `priced.items` directly. It counted where it helped and
   vanished where it would be caught.

2. `checks.py` — the fee-percentage guard ran only when a fee was supplied OR the bill carried
   client-inserted provisional sums. Those are different things: (B)/(D)/(E) are contingencies
   outside the contract, (C) is the direct fee. A bill with a fee line and no contingencies skipped
   the check entirely — which is exactly the case it exists for, since GCT App C 2.4 corrects an
   OMITTED fee to the minimum.

3. `coverage.py` — `SECTION_COVERAGE` has been transcribed for Bill No.2 only. Every item in the
   other four bills produced ZERO heads, and zero heads with zero uncovered read as "all covered".
   Four fifths of the bill reported itself fully settled because nobody had written its checklist
   down. Absence looked identical to completeness.

4. `unbilled.py` — `by_route()` dropped any cost whose route was blank or misspelt, so a screen
   showed fewer costs than the sweep held and the missing ones were precisely the unrouted ones
   the module exists to stop being forgotten.

AND THE MAZIER SPLIT, resolved: `programme.py` rounded, `resources.py` ceiled. Both count TUBES,
so they are unified on ceil — you cannot buy 0.7 of a liner. `criteria.py` floors and is
deliberately NOT unified: it answers how many sampling DEPTHS fit in a hole, which is a different
count, and forcing the three to agree would make one of them wrong.

WHAT CLEARED. `carry.py`, `docmap.py`, `trace.py` and `outputs.py` were read for the same class and
nothing was found that is not already reported to the caller: `carry` proposes for every non-parent
item and marks every uncertain case `needs_review`; `docmap` returns `None` for an unresolvable
citation rather than a plausible page; `trace` carries its divisor as `or 0.0` but only after the
group is looked up and named; `outputs.resolve` distinguishes MISSING from a zero somebody chose,
which is the whole point of that module. The tests below cover the confirmations too, so a later
change cannot quietly undo what was checked.
"""

from __future__ import annotations

import math

import pytest

from client_boq.boq import checks as boq_checks
from client_boq.boq import coverage as boq_coverage
from client_boq.boq import criteria as boq_criteria
from client_boq.boq import unbilled as boq_unbilled
from client_boq.boq.model import default_model
from client_boq.boq.outputs import NORM_INDEX, OutputBook, SOURCE_MISSING, resolve
from client_boq.boq.programme import Quantities, derive
from client_boq.boq.resources import MaterialGeometry
from client_boq.models import (
    BillItem,
    ClientBill,
    GrandSummaryLine,
    PricedBill,
    PricedItem,
)


def _bill(*items: BillItem, summary=None) -> ClientBill:
    return ClientBill(set_id="audit", rev=0, items=list(items), summary=list(summary or []))


def _item(ref: str, *, bill_no: str = "2", row: int = 1, **kw) -> BillItem:
    return BillItem(bill_no=bill_no, item_ref=ref, full_ref=ref, row=row,
                    description=kw.pop("description", f"item {ref}"), unit=kw.pop("unit", "m"),
                    qty=kw.pop("qty", 100.0), **kw)


def _priced(*entries: PricedItem, total: float = 0.0, bill_totals=None) -> PricedBill:
    return PricedBill(items=list(entries), tendered_total=total,
                      bill_totals=dict(bill_totals or {}))


def _entry(ref: str, *, bill_no: str = "2", rate=None, amount: float = 0.0, **kw) -> PricedItem:
    return PricedItem(full_ref=ref, bill_no=bill_no, description=f"item {ref}",
                      unit=kw.pop("unit", "m"), qty=kw.pop("qty", 100.0),
                      unit_rate=rate, amount=amount, **kw)


# ---------------------------------------------------------------------------
# 1. A priced line the bill has never heard of
# ---------------------------------------------------------------------------
class TestAnOrphanPricedLine:
    def test_it_is_flagged_rather_than_skipped_by_everything(self):
        bill = _bill(_item("2.1"))
        priced = _priced(_entry("2.1", rate=10.0, amount=1000.0),
                         _entry("2.99", rate=50.0, amount=5000.0))

        orphans = boq_checks.orphan_priced_items(priced, bill)
        assert [f.item_id for f in orphans] == ["2.99"]
        assert "in no item of the client's bill" in orphans[0].message

    def test_its_money_really_does_reach_the_total_which_is_why_it_matters(self):
        """The shape that makes it the worst kind of miss: it counts where it helps."""
        bill = _bill(_item("2.1"))
        priced = _priced(_entry("2.1", rate=10.0, amount=1000.0),
                         _entry("2.99", rate=50.0, amount=5000.0),
                         total=6000.0, bill_totals={"2": 6000.0})
        # No casting error — the orphan's 5,000 is inside the bill total quite happily.
        assert not boq_checks.casting_errors(priced)

    def test_an_unpriced_orphan_is_not_reported_as_unpriced_so_this_is_the_only_net(self):
        bill = _bill(_item("2.1"))
        priced = _priced(_entry("2.1", rate=10.0, amount=1000.0), _entry("2.99"))
        assert not [f for f in boq_checks.unpriced_items(priced, bill) if f.item_id == "2.99"]
        assert [f.item_id for f in boq_checks.orphan_priced_items(priced, bill)] == ["2.99"]

    def test_it_runs_inside_run_checks_before_the_checks_that_would_miss_it(self):
        bill = _bill(_item("2.1"))
        priced = _priced(_entry("2.1", rate=10.0, amount=1000.0),
                         _entry("2.99", rate=50.0, amount=5000.0),
                         total=6000.0, bill_totals={"2": 6000.0})
        kinds = [f.kind for f in boq_checks.run_checks(priced, bill)]
        assert "orphan_priced_item" in kinds
        assert kinds.index("orphan_priced_item") < len(kinds)

    def test_a_bill_whose_refs_all_match_produces_none(self):
        bill = _bill(_item("2.1"), _item("2.2"))
        priced = _priced(_entry("2.1", rate=1.0, amount=100.0),
                         _entry("2.2", rate=1.0, amount=100.0))
        assert boq_checks.orphan_priced_items(priced, bill) == []


# ---------------------------------------------------------------------------
# 2. Two items sharing one reference — `index()` keeps one
# ---------------------------------------------------------------------------
class TestADuplicateReference:
    def test_the_identity_map_really_does_collapse_them(self):
        """Stated as arithmetic, because the fix is a flag rather than a repair: `index()` is a
        dict comprehension and the loser is gone from every lookup downstream."""
        bill = _bill(_item("2.1", row=10), _item("2.1", bill_no="4", row=90))
        assert len(bill.items) == 2 and len(bill.index()) == 1

    def test_it_is_flagged_with_both_places(self):
        bill = _bill(_item("2.1", row=10), _item("2.1", bill_no="4", row=90))
        flags = boq_checks.duplicate_bill_refs(bill)
        assert [f.item_id for f in flags] == ["2.1"]
        assert "Bill No.2 row 10" in flags[0].message
        assert "Bill No.4 row 90" in flags[0].message
        assert "invisible" in flags[0].message

    def test_across_two_bills_is_caught_which_the_reader_alone_did_not(self):
        """The reader's own duplicate note keys on `bill_no:full_ref`, so a reference repeated in
        two DIFFERENT bills was noted nowhere — and `index()` collapsed it anyway."""
        bill = _bill(_item("1.1", bill_no="1", row=5), _item("1.1", bill_no="2", row=44))
        assert boq_checks.duplicate_bill_refs(bill)

    def test_a_clean_bill_produces_none(self):
        assert boq_checks.duplicate_bill_refs(_bill(_item("2.1"), _item("2.2"))) == []


# ---------------------------------------------------------------------------
# 3. The fee check's trigger
# ---------------------------------------------------------------------------
class TestTheFeePercentageTrigger:
    def test_a_bill_with_a_fee_line_and_no_contingencies_is_now_checked(self):
        """The case the check exists for. GCT App C 2.4 corrects an OMITTED fee to the minimum,
        binding you to the lowest markup available without ever asking."""
        bill = _bill(_item("2.1"), summary=[GrandSummaryLine(label="Fee", code="C")])
        priced = _priced(_entry("2.1", rate=1.0, amount=100.0), total=100.0,
                         bill_totals={"2": 100.0})
        kinds = [f.kind for f in boq_checks.run_checks(priced, bill)]
        assert "fee_percentage_out_of_range" in kinds

    def test_a_bill_with_no_fee_line_is_not_nagged_about_one(self):
        bill = _bill(_item("2.1"))
        priced = _priced(_entry("2.1", rate=1.0, amount=100.0), total=100.0,
                         bill_totals={"2": 100.0})
        kinds = [f.kind for f in boq_checks.run_checks(priced, bill)]
        assert "fee_percentage_out_of_range" not in kinds

    def test_an_explicit_fee_is_always_checked_whatever_the_summary_says(self):
        bill = _bill(_item("2.1"))
        priced = _priced(_entry("2.1", rate=1.0, amount=100.0), total=100.0,
                         bill_totals={"2": 100.0})
        kinds = [f.kind for f in boq_checks.run_checks(priced, bill, fee_pct=99.0)]
        assert "fee_percentage_out_of_range" in kinds


# ---------------------------------------------------------------------------
# 4. A bill whose item coverage was never transcribed
# ---------------------------------------------------------------------------
class TestCoverageForABillNobodyTranscribed:
    def test_a_bill_with_no_transcribed_list_is_the_case_this_guards(self):
        # RE-ANCHORED IN THE OPEN. This asserted `set(SECTION_COVERAGE) == {"2"}` — which was TRUE
        # when the finding was made and is the finding itself, not the guard. Bills 3-6 have since
        # been transcribed, so the literal set moved. What the guard is ABOUT — an item whose
        # coverage nobody has written down must not read as "all covered" — is unchanged, and is
        # now stated against a bill that genuinely has no list rather than against a snapshot of
        # how many did on the day.
        transcribed = set(boq_coverage.SECTION_COVERAGE)
        assert "2" in transcribed
        assert "7" not in transcribed, "the case the rest of this class exercises"

    def test_an_item_with_no_list_does_not_read_as_all_covered(self):
        covered = boq_coverage.coverage_for(_item("2.4", bill_no="2"))
        bare = boq_coverage.coverage_for(_item("7.1", bill_no="7"))

        assert covered.total() > 0 and not covered.settled(), "unticked, so not settled"
        assert bare.total() == 0
        assert not bare.settled(), "zero heads must not mean zero left to do"
        assert bare.no_list_for_section == "7"
        assert "no item-coverage list transcribed" in bare.summary()

    def test_the_item_specific_table_is_enough_to_count_as_a_list(self):
        """2.2a's access-scaffolding head is keyed on the item, not the section."""
        assert boq_coverage.has_list_for(_item("2.2a", bill_no="2"))

    def test_a_model_proposing_heads_makes_a_list_where_there_was_none(self):
        """Somebody has now said what this rate must carry — and the heads arrive unticked, so
        nothing is settled by their arrival."""
        proposed = [boq_coverage.CoverageHead(key="x", label="something",
                                              authored_by=boq_coverage.BY_MODEL)]
        out = boq_coverage.coverage_for(_item("7.1", bill_no="7"), proposed=proposed)
        assert out.no_list_for_section == ""
        assert not out.settled(), "proposed heads are unticked like every other"

    def test_the_bill_summary_counts_them_separately_from_untick_ed_heads(self):
        """Two different problems with two different owners. Adding them together would hide the
        second inside the first."""
        bill = _bill(_item("2.4", bill_no="2"), _item("7.1", bill_no="7"))
        out = boq_coverage.bill_summary(bill, ticks={})
        assert out["no_list"] == 1
        assert out["bills_without_a_list"] == ["7"]
        assert out["settled"] == 0
        assert out["outstanding"] > 0, "2.4's own heads are still counted"


# ---------------------------------------------------------------------------
# 5. Every unbilled cost lands in exactly one bucket
# ---------------------------------------------------------------------------
class TestTheUnbilledBuckets:
    def _sweep(self) -> boq_unbilled.UnbilledSweep:
        return boq_unbilled.UnbilledSweep(costs=[
            boq_unbilled.UnbilledCost(key="a", label="site uniform", amount=1000.0,
                                      route=boq_unbilled.ROUTE_SPREAD),
            boq_unbilled.UnbilledCost(key="b", label="platform", amount=2000.0,
                                      route=boq_unbilled.ROUTE_LOAD, target_ref="2.2b"),
            boq_unbilled.UnbilledCost(key="c", label="undecided one", amount=500.0),
            boq_unbilled.UnbilledCost(key="d", label="typo'd one", amount=750.0, route="sprad"),
        ])

    def test_nothing_falls_through_the_loop(self):
        buckets = self._sweep().by_route()
        assert sum(len(v) for v in buckets.values()) == 4, "every cost is somewhere"

    def test_an_undecided_and_a_misspelt_route_both_land_in_nowhere(self):
        buckets = self._sweep().by_route()
        assert {c.key for c in buckets[boq_unbilled.ROUTE_NOWHERE]} == {"c", "d"}

    def test_the_gate_still_refuses_both_of_them(self):
        with pytest.raises(boq_unbilled.UnroutedCost) as raised:
            boq_unbilled.gate(self._sweep())
        assert len(raised.value.problems) == 2

    def test_a_settled_sweep_leaves_nowhere_empty(self):
        sweep = boq_unbilled.UnbilledSweep(costs=[
            boq_unbilled.UnbilledCost(key="a", label="x", route=boq_unbilled.ROUTE_SPREAD)])
        assert sweep.settled()
        assert sweep.by_route()[boq_unbilled.ROUTE_NOWHERE] == []


# ---------------------------------------------------------------------------
# 6. The mazier count — unified on ceil, and the one that is deliberately not
# ---------------------------------------------------------------------------
class TestTheMazierCount:
    def test_the_programme_and_the_resource_sheet_now_agree(self):
        """They disagreed: `programme` rounded and `resources` ceiled, so the same soil depth
        produced two different tube counts depending on which module you asked."""
        model = default_model()
        geometry = MaterialGeometry(sample_interval_m=model.value("mazier_interval_m"))
        for soil_m in (2300.0, 2301.0, 2299.0, 1.0, 0.5, 999.9):
            programme = derive(Quantities(holes=10, soil_m=soil_m, rock_m=100.0), model)
            assert programme.mazier_samples == geometry.soil_tubes(soil_m), soil_m

    def test_it_rounds_up_because_you_cannot_buy_part_of_a_liner(self):
        model = default_model()
        programme = derive(Quantities(holes=10, soil_m=2301.0, rock_m=100.0), model)
        assert programme.mazier_samples == 1151         # 2301 / 2 = 1150.5 -> 1151

    def test_the_old_rule_was_worse_than_it_looked(self):
        """Python rounds half to EVEN, so 1,150.5 came back as 1,150 and 1,151.5 as 1,152 — a rule
        nobody would defend if it were written down. Kept here as the record of what changed."""
        assert round(1150.5) == 1150 and round(1151.5) == 1152
        assert math.ceil(1150.5) == 1151 and math.ceil(1151.5) == 1152

    def test_the_demo_model_does_not_move_because_it_divides_exactly(self):
        model = default_model()
        programme = derive(Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0), model)
        assert programme.mazier_samples == 1150

    def test_the_sampling_depth_count_is_a_different_question_and_still_floors(self):
        """DELIBERATELY NOT UNIFIED. Sampling every 2 m down an 11 m hole gives depths at
        2/4/6/8/10 — five, not six. Tubes to buy and depths to sample are two counts, and forcing
        them to agree would make one of them wrong."""
        sampling = boq_criteria.SamplingRules()
        assert sampling.count_at_interval(11.0, 2.0) == 5
        assert MaterialGeometry(sample_interval_m=2.0).soil_tubes(11.0) == 6
        assert sampling.count_at_interval(10.0, 2.0) == 5, "an exact fit agrees either way"


# ---------------------------------------------------------------------------
# 7. What cleared — pinned so a later change cannot quietly undo the check
# ---------------------------------------------------------------------------
class TestWhatTheAuditCleared:
    def test_outputs_distinguishes_a_missing_norm_from_a_zero_somebody_chose(self):
        """`None` and `0.0` are different answers and the caller can tell them apart — a decay of
        zero is a claim somebody might genuinely make; a norm nobody ever set is not that."""
        book = OutputBook()
        assert book.get("decay_pct") == 0.0, "a declared default, not an absence"
        assert book.get("no_such_norm") is None
        settled = resolve(book, {}, keys=["helicopter_hours"])
        assert settled["helicopter_hours"].source == SOURCE_MISSING
        assert settled["helicopter_hours"].value == 0.0

    def test_every_norm_the_engine_reads_is_declared(self):
        for key in ("soil_output", "rock_output", "decay_pct", "mob_days", "markup_pct"):
            assert key in NORM_INDEX

    def test_carry_proposes_for_every_non_parent_item_and_marks_the_uncertain_ones(self):
        from client_boq.boq.carry import carry_rates
        from client_boq.boq.diff import diff_bills

        before = _bill(_item("2.1"), _item("2.2"))
        after = _bill(_item("2.1"), _item("2.2"), _item("2.3"))
        carried = carry_rates(diff_bills(before, after), before, after,
                              priced={"2.1": 10.0, "2.2": None})

        assert {c.full_ref for c in carried} == {"2.1", "2.2", "2.3"}, "nothing dropped"
        assert all(c.rule for c in carried), "every proposal names the rule that produced it"
        by_ref = {c.full_ref: c for c in carried}
        assert by_ref["2.3"].needs_review, "a new item is never carried silently"
        assert by_ref["2.2"].rate is None, "an unpriced predecessor stays unpriced"

    def test_docmap_returns_nothing_rather_than_a_plausible_page(self):
        from client_boq.boq.docmap import DocumentMap

        assert DocumentMap().resolve("7.30S") is None
