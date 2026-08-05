"""The revision diff, and carrying rates across it.

The rule these defend: **the item reference is the identity; a moved row is not a change; a changed
caption is.**

All three halves are load-bearing, and each is measured from the reference tender:

* Between Rev 0 and Rev 1, 35 items moved rows and **0 were renumbered**. Reporting the moves as
  changes would bury the five real changes under thirty-five false ones, which is precisely how a
  safeguard stops being read.
* The largest price movement in that tender — three groundwater quantities multiplied by 2.17, six
  months of monitoring per instrument becoming twelve — was announced as "Updated the quantities of
  item nos. 6.4 - 6.6", against a workbook carrying no fill, no bold, no comment and no tracked
  change on any of the 1,239 cells.
* The second addendum edited one caption, "marine" to "land" traffic, and touched none of the three
  items beneath it. General Preambles 2 makes a sub-heading part of what an item covers, so their
  scope moved. An item-row diff reports nothing there.
"""

from __future__ import annotations

import pytest

from client_boq.boq import carry
from client_boq.boq.diff import diff_bills
from client_boq.boq.reader import read_workbook
from client_boq.models import (
    CARRY_NEW_ZERO,
    CARRY_SAME_RATE,
    CHANGE_ADDED,
    CHANGE_DESCRIPTION,
    CHANGE_HEADING,
    CHANGE_QTY,
)
from client_boq.tests._bqfixture import build_bill_workbook

pytest.importorskip("openpyxl")


@pytest.fixture(scope="module")
def bills(tmp_path_factory):
    root = tmp_path_factory.mktemp("boqdiff")
    return {rev: read_workbook(build_bill_workbook(root / f"bq-{rev}.xlsx", rev), set_id="t", rev=rev)
            for rev in (0, 1, 2)}


@pytest.fixture(scope="module")
def first(bills):
    return diff_bills(bills[0], bills[1])


@pytest.fixture(scope="module")
def second(bills):
    return diff_bills(bills[1], bills[2])


def _kinds(diff, ref):
    return {c.kind for c in diff.changes if c.full_ref == ref}


def _change(diff, ref, kind):
    return next(c for c in diff.changes if c.full_ref == ref and c.kind == kind)


class TestAMoveIsNotAChange:
    def test_relocated_items_are_reported_as_moved_not_changed(self, first):
        assert first.moved_only, "the split pushes items down; they must be seen and dismissed"
        for ref in first.moved_only:
            assert not _kinds(first, ref)

    def test_nothing_is_ever_renumbered(self, bills):
        # Every reference in Rev 0 still exists in Rev 2, seven rows lower in places.
        assert set(bills[0].index()) - {"2.2"} <= set(bills[2].index())

    def test_an_item_that_only_moved_still_counts_as_unchanged(self, first):
        assert first.unchanged >= len(first.moved_only)


class TestTheQuantityChangeNobodyAnnounced:
    @pytest.mark.parametrize("ref, before, after", [
        ("6.4", 1128, 2451), ("6.5", 1623, 3546), ("6.6", 2760, 5996)])
    def test_each_is_caught_with_its_magnitude(self, first, ref, before, after):
        change = _change(first, ref, CHANGE_QTY)
        assert f"{before:,}" in change.detail and f"{after:,}" in change.detail
        assert "×2.1" in change.detail or "x2.1" in change.detail

    def test_a_doubled_quantity_carries_the_rate_and_demands_a_second_look(self, bills, first):
        carried = carry.carry_rates(first, bills[0], bills[1], {"6.4": 42.0})
        entry = next(c for c in carried if c.full_ref == "6.4")
        # GCT App C 2.2(v) says to use the same rate. That is what happens — and it is flagged,
        # because a rate built for 24 weeks of monitoring is not obviously right for 52.
        assert entry.rate == 42.0 and entry.basis == CARRY_SAME_RATE
        assert entry.needs_review and "+117%" in entry.reason
        assert "same rate shall be used" in entry.rule


class TestTheCaptionChange:
    def test_items_the_client_never_touched_are_flagged(self, second):
        for ref in ("1.5", "1.6"):
            change = _change(second, ref, CHANGE_HEADING)
            assert "marine" in change.before and "land" in change.after
            assert "own row is unchanged" in change.detail

    def test_a_caption_change_reopens_the_rate_beneath_it(self, bills, second):
        carried = carry.carry_rates(second, bills[1], bills[2], {"1.5": 90000.0})
        entry = next(c for c in carried if c.full_ref == "1.5")
        assert entry.rate == 90000.0 and entry.needs_review
        assert "heading" in entry.reason


class TestTheSplit:
    def test_it_reads_as_a_split_not_as_a_vanished_quantity(self, first):
        change = _change(first, "2.2", CHANGE_QTY)
        assert "2.2a 80 nr" in change.detail and "2.2b 11 nr" in change.detail

    def test_the_variants_are_reconciled_against_what_the_parent_carried(self, first):
        assert "add back to the 91 nr" in _change(first, "2.2", CHANGE_QTY).detail

    def test_the_variants_arrive_as_new_and_unpriced(self, first):
        for ref in ("2.2a", "2.2b"):
            assert CHANGE_ADDED in _kinds(first, ref)

    def test_a_parent_is_not_offered_a_rate(self, bills, first):
        carried = carry.carry_rates(first, bills[0], bills[1], {"2.2": 1500.0})
        assert not any(c.full_ref == "2.2" for c in carried)


class TestTheNarrowedDescription:
    def test_it_is_caught_and_says_why_it_matters(self, second):
        change = _change(second, "4.18", CHANGE_DESCRIPTION)
        assert "ground water" in change.before and "ground water" not in change.after
        assert "the quantity did not move" in change.detail

    def test_the_rate_carries_and_is_flagged(self, bills, second):
        carried = carry.carry_rates(second, bills[1], bills[2], {"4.18": 3200.0})
        entry = next(c for c in carried if c.full_ref == "4.18")
        assert entry.rate == 3200.0 and entry.needs_review
        assert "different work" in entry.reason


class TestCarryingRates:
    def test_a_new_item_is_unpriced_not_zero_and_says_what_unpriced_costs(self, bills, second):
        carried = carry.carry_rates(second, bills[1], bills[2], {})
        entry = next(c for c in carried if c.full_ref == "1.61A")
        assert entry.rate is None and entry.basis == CARRY_NEW_ZERO
        assert "General Preambles 6" in entry.reason and entry.needs_review

    def test_a_pre_priced_item_takes_the_clients_own_figure(self, bills, second):
        carried = carry.carry_rates(second, bills[1], bills[2], {"9.1": 1.0})
        entry = next(c for c in carried if c.full_ref == "9.1")
        assert entry.rate == 4860 and not entry.needs_review

    def test_an_untouched_item_carries_silently(self, bills, second):
        carried = carry.carry_rates(second, bills[1], bills[2], {"2.4": 1164.15})
        entry = next(c for c in carried if c.full_ref == "2.4")
        assert entry.rate == 1164.15 and not entry.needs_review
        assert "no circumstances can the tendered rates be changed" in entry.rule

    def test_the_worklist_is_exactly_what_needs_looking_at(self, bills, first):
        carried = carry.carry_rates(first, bills[0], bills[1],
                                    {"6.4": 42.0, "6.5": 42.0, "6.6": 42.0, "2.4": 1164.15})
        pending = {entry.full_ref for entry in carry.pending_review(carried)}
        assert {"6.4", "6.5", "6.6"} <= pending
        assert "2.4" not in pending
