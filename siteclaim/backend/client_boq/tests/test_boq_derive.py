"""The take-off half: the schedule, the site's rules, the derived quantities, and the groups.

The rule these defend: **the client's own bill is the answer key for our reading of his drawings — and
where the two disagree, saying so is the most valuable thing this code does.**

Every constant is from the reference contract (ND/2025/04) and is checkable against the issued
documents:

  * the schedule reconciles row by row — 29.90 m of soil + 5.0 m of rock = a 34.90 m hole
  * standing time is exactly 5.0 h a hole, on two independent bills (455 ÷ 91, and 45 ÷ 9)
  * recording is instruments × 365 ÷ 7 — 47 → 2,451, 68 → 3,546, 115 → 5,996, all to the unit
  * every standpipe and every piezometer gets one automatic device: 47 + 68 = 115
  * 21 trial pits at 1.5 × 1.5 × 3.0 m = 141.75 → the billed 142 m³, and 21 × 3 samples = 63
  * the drawing's Table 1 says 52 permeability tests; the bill says 54
"""

from __future__ import annotations

import pytest

from client_boq.boq import derive as derive_mod
from client_boq.boq.criteria import PitRules, SiteCriteria, TentativeTestCounts
from client_boq.boq.groups import (
    CLASS_A,
    CLASS_B,
    CLASS_C,
    GroupPlan,
    HoleGroup,
    blend,
    cluster,
    group_divisors,
    summarise,
)
from client_boq.boq.schedule import Station, StationSchedule, TrialPit
from client_boq.models import BillItem, ClientBill


def _station(name, soil, rock, *, e=826000.0, n=839000.0, standpipe=False, piezometer=False,
             length=None):
    return Station(station=name, easting=e, northing=n, soil_m=soil, rock_m=rock,
                   length_m=soil + rock if length is None else length,
                   standpipe=standpipe, piezometer=piezometer)


@pytest.fixture
def schedule():
    """A miniature of the real thing: 12 holes, two clusters 1 km apart, 21 pits."""
    stations = []
    for i in range(8):                                   # a roadside cluster
        stations.append(_station(f"ABH{i:02d}", 30.0, 0.0, e=826000.0 + i * 20,
                                 standpipe=i < 5, piezometer=i < 6))
    for i in range(4):                                   # a hillside cluster, 1 km east, with rock
        stations.append(_station(f"ABH1{i}", 25.0, 5.0, e=827200.0 + i * 20,
                                 standpipe=False, piezometer=i < 2))
    pits = [TrialPit(station=f"NTP{i:02d}", depth_m=3.0) for i in range(1, 22)]
    return StationSchedule(set_id="t", source_sheet="60740338/GI/210",
                           stations=stations, trial_pits=pits)


@pytest.fixture
def criteria():
    return SiteCriteria(source_sheet="60740338/GI/100",
                        tests=TentativeTestCounts(permeability=52, pressuremeter=30,
                                             acoustic_televiewer=8))


class TestTheScheduleChecksItself:
    def test_a_row_must_satisfy_its_own_arithmetic(self, schedule):
        assert schedule.usable() and schedule.bad_rows() == []

    def test_a_row_that_does_not_add_up_is_named_and_never_priced(self, schedule):
        schedule.stations.append(_station("ABH99", 20.0, 5.0, length=40.0))
        assert not schedule.usable()
        problem = schedule.bad_rows()[0]
        assert "ABH99" in problem and "25" in problem and "40" in problem

    def test_the_sums_the_bill_can_be_checked_against(self, schedule):
        assert schedule.soil_m() == 8 * 30 + 4 * 25 == 340
        assert schedule.rock_m() == 4 * 5 == 20
        assert schedule.hole_count() == 12
        assert schedule.standpipes() == 5 and schedule.piezometers() == 8

    def test_instruments_is_standpipes_plus_piezometers(self, schedule):
        # The identity behind the real bill: 47 + 68 = 115 AGMD, exactly.
        assert schedule.instruments() == schedule.standpipes() + schedule.piezometers() == 13

    def test_depth_bands_are_counted_because_deep_metres_are_slower(self, schedule):
        assert schedule.holes_past(20.0) == 12
        assert schedule.holes_past(40.0) == 0


class TestDerivationAgainstTheBill:
    def test_a_derivation_that_lands_confirms_both_readings(self, schedule, criteria):
        bill = ClientBill(items=[BillItem(bill_no="2", full_ref="2.4", qty=340.0, unit="m")])
        report = derive_mod.derive(schedule, criteria, bill=bill, refs={"soil_m": "2.4"})
        soil = next(d for d in report.derived if d.label.startswith("Drilling, material"))
        assert soil.value == 340.0 and soil.agrees is True

    def test_a_divergence_is_reported_with_both_numbers(self, schedule, criteria):
        # The real one: GI/100 Table 1 says 52 permeability tests, the bill says 54.
        bill = ClientBill(items=[BillItem(bill_no="2", full_ref="2.22", qty=54.0, unit="nr")])
        report = derive_mod.derive(schedule, criteria, bill=bill, refs={"permeability": "2.22"})
        gap = next(d for d in report.divergences() if d.full_ref == "2.22")
        assert gap.value == 52 and gap.billed == 54
        assert "misread" in gap.note or "diverges" in gap.note

    def test_standing_time_is_five_hours_a_hole(self, schedule, criteria):
        report = derive_mod.derive(schedule, criteria)
        standing = next(d for d in report.derived if d.label.startswith("Standing time"))
        assert standing.value == 12 * 5.0 == 60.0
        assert "455" in standing.source, "the rule should say where it was recovered from"

    @pytest.mark.parametrize("instruments, weeks", [(47, 2451), (68, 3546), (115, 5996)])
    def test_recording_reproduces_the_real_bill_exactly(self, criteria, instruments, weeks):
        assert criteria.monitoring.instrument_weeks(instruments) == weeks

    def test_trial_pits_and_their_samples(self, schedule, criteria):
        report = derive_mod.derive(schedule, criteria)
        volume = next(d for d in report.derived if d.label == "Trial pits")
        samples = next(d for d in report.derived if d.label == "Samples from trial pits")
        assert volume.value == pytest.approx(21 * 6.75) == pytest.approx(141.75)
        assert samples.value == 63                       # 21 pits × 3, at 0.5, 1.5 and 2.5 m

    def test_the_trial_pit_sample_rule_reads_off_the_drawing(self):
        # "at 1m intervals, starting from 0.5m below the existing ground level" in a 3 m pit.
        assert PitRules().trial_samples_per_pit() == 3

    def test_every_derivation_carries_its_rule_and_its_source(self, schedule, criteria):
        for entry in derive_mod.derive(schedule, criteria).derived:
            assert entry.rule and entry.source, f"{entry.label} must say how and from where"

    def test_nothing_is_claimed_when_there_is_no_bill_to_check_against(self, schedule, criteria):
        report = derive_mod.derive(schedule, criteria)
        assert report.divergences() == [] and report.confirmations() == []
        assert len(report.unchecked()) == len(report.derived)


class TestGrouping:
    def test_proximity_proposes_the_two_spreads(self, schedule):
        groups = cluster(schedule, radius_m=250.0)
        assert len(groups) == 2
        assert sorted(g.hole_count for g in groups) == [4, 8]

    def test_a_group_carries_its_own_measured_facts(self, schedule):
        hillside = [g for g in cluster(schedule) if g.hole_count == 4][0]
        assert hillside.soil_m == 100.0 and hillside.rock_m == 20.0

    def test_a_station_without_coordinates_is_kept_not_dropped(self, schedule):
        schedule.stations.append(Station(station="ABHX", soil_m=10.0, length_m=10.0))
        groups = cluster(schedule)
        assert "Unlocated" in {g.label for g in groups}
        assert sum(g.hole_count for g in groups) == 13

    def test_a_group_says_what_it_still_needs(self, schedule):
        group = summarise(HoleGroup(label="G", stations=["ABH00"]), schedule)
        assert "access class" in group.ready() and "soil output (m/day)" in group.ready()
        ready = group.model_copy(update={"access_class": CLASS_A, "soil_output": 12})
        assert ready.ready() == []


class TestTheCountThatChecksTheWork:
    """The client bills 80 Class A and 11 Class B but never says which holes. The count is the only
    external check on a judgement the estimator otherwise makes alone."""

    def test_agreement_is_silence(self):
        plan = GroupPlan(
            groups=[HoleGroup(label="road", stations=[f"a{i}" for i in range(80)],
                              access_class=CLASS_A),
                    HoleGroup(label="hill", stations=[f"b{i}" for i in range(11)],
                              access_class=CLASS_B)],
            billed_class_counts={CLASS_A: 80, CLASS_B: 11})
        assert plan.counts() == {CLASS_A: 80, CLASS_B: 11, CLASS_C: 0}
        assert plan.reconcile() == []

    def test_a_miscount_names_the_class_and_the_gap(self):
        plan = GroupPlan(
            groups=[HoleGroup(label="road", stations=[f"a{i}" for i in range(74)],
                              access_class=CLASS_A),
                    HoleGroup(label="hill", stations=[f"b{i}" for i in range(8)],
                              access_class=CLASS_B)],
            billed_class_counts={CLASS_A: 80, CLASS_B: 11})
        problems = " · ".join(plan.reconcile())
        assert "Class A: you have 74 against the 80" in problems and "under by 6" in problems

    def test_unassigned_stations_block_before_anything_else(self):
        plan = GroupPlan(groups=[HoleGroup(label="g", stations=["a", "b"])],
                         billed_class_counts={CLASS_A: 2})
        assert "2 station(s) have no access class yet" in plan.reconcile()[0]

    def test_class_c_has_no_bill_item_and_says_so(self):
        plan = GroupPlan(
            groups=[HoleGroup(label="air", stations=["x"], access_class=CLASS_C)],
            billed_class_counts={CLASS_A: 0, CLASS_B: 0})
        problems = " · ".join(plan.reconcile())
        assert "helicopter" in problems and "no bill item" in problems
        assert "queried" in problems


class TestBlendingAcrossGroups:
    """One rate has to cover 91 unlike holes. Price each group, then let arithmetic average them."""

    def _sheets(self, easy_rate, hard_rate):
        from client_boq.boq.allocate import RateRecipe, RecipeTerm
        from client_boq.boq.resources import ResourceSheet, SheetLine

        def sheet(label, rate):
            return ResourceSheet(label=label, markup_pct=0.0, lines=[
                SheetLine(key="crew", label="crew", qty=1, rate=rate)])
        recipe = RateRecipe(full_ref="2.4", terms=[RecipeTerm(key="crew")], divisor_label="m")
        return recipe, [sheet("easy", easy_rate), sheet("hard", hard_rate)]

    def test_identical_groups_blend_to_the_same_rate_as_one_block(self):
        recipe, sheets = self._sheets(1000.0, 1000.0)
        blended = blend(recipe, sheets, {"easy": 10.0, "hard": 10.0})
        assert blended.rate == 100.0                     # (1000 + 1000) ÷ 20 m

    def test_a_slower_group_moves_the_blend_by_the_predicted_amount(self):
        recipe, sheets = self._sheets(1000.0, 3000.0)
        blended = blend(recipe, sheets, {"easy": 10.0, "hard": 10.0})
        assert blended.rate == 200.0                     # (1000 + 3000) ÷ 20 m

    def test_the_blend_shows_which_group_is_carrying_it(self):
        recipe, sheets = self._sheets(1000.0, 3000.0)
        blended = blend(recipe, sheets, {"easy": 10.0, "hard": 10.0})
        assert [g["group"] for g in blended.groups] == ["easy", "hard"]
        assert [g["cost"] for g in blended.groups] == [1000.0, 3000.0]

    def test_a_missing_divisor_is_refused_rather_than_guessed(self):
        recipe, sheets = self._sheets(1000.0, 1000.0)
        with pytest.raises(KeyError, match="not something to infer"):
            blend(recipe, sheets, {"easy": 10.0})

    def test_divisors_come_from_the_groups_own_metres(self, schedule):
        groups = [summarise(g, schedule) for g in cluster(schedule)]
        assert sum(group_divisors(groups, "soil").values()) == schedule.soil_m()
        assert sum(group_divisors(groups, "rock").values()) == schedule.rock_m()
