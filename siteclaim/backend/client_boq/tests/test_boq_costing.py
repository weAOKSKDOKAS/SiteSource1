"""The costing model: days, resources, and the rate that comes out of them.

The rule these defend: **the engine must reproduce a working estimator's own spreadsheet, to the cent.**

That is not a nicety. The product only earns its place if the person who can already do this work can
check it faster than he can redo it — so the first thing it has to prove is that on his inputs it gets
his answer. If our number and his number differ, the code is wrong; the spreadsheet is the specification.

Every constant here is transcribed from that workbook (see ``_hke_workbook``), never re-derived by
calling the code under test.
"""

from __future__ import annotations

import pytest

from client_boq.boq.allocate import DAYS_SOIL, RateRecipe, RecipeTerm, price_item
from client_boq.boq.duration import output_at, simulate
from client_boq.boq.resources import MaterialGeometry
from client_boq.tests import _hke_workbook as hke


@pytest.fixture(scope="module")
def sheet():
    return hke.build_sheet()


@pytest.fixture(scope="module")
def duration(sheet):
    return sheet.duration


class TestTheDayCalculator:
    """A division would be wrong twice: drilling slows with depth, and a day does not end when the
    soil does."""

    def test_the_programme_matches_the_workbook(self, duration):
        assert duration.total_days == hke.EXPECT_TOTAL_DAYS
        assert duration.soil_complete_day == hke.EXPECT_SOIL_COMPLETE_DAY
        assert duration.rock_complete_day == hke.EXPECT_ROCK_COMPLETE_DAY

    def test_the_two_day_counts_a_rate_divides_by(self, duration):
        assert duration.soil_days == hke.EXPECT_SOIL_DAYS
        assert duration.rock_days_charged == hke.EXPECT_ROCK_CHARGED

    def test_output_decays_a_step_per_twenty_metre_band(self):
        # The bands are 20 m because the Method of Measurement stages drilling in 20 m lengths.
        assert output_at(20, 0, 0.05) == 20
        assert output_at(20, 19.9, 0.05) == 20
        assert output_at(20, 20, 0.05) == 19
        assert output_at(20, 39.9, 0.05) == 19
        assert output_at(20, 40, 0.05) == pytest.approx(18.05)

    def test_the_day_soil_finishes_is_shared_with_rock(self, duration):
        # Soil runs out 2 m into an 18.05 m day; the remaining 88.9% of that day drills rock.
        day4 = duration.days[3]
        assert day4.soil_drilled == 2
        assert day4.day_fraction_left == pytest.approx(0.889196675900277)
        assert day4.rock_drilled == pytest.approx(8.89196675900277)

    def test_rock_carries_the_rounding_up_to_a_whole_day(self, duration):
        # You pay for the whole of the last day. actual < charged, and the difference is the rounding.
        assert duration.rock_days_actual < duration.rock_days_charged
        assert duration.soil_days + duration.rock_days_charged == duration.total_days

    def test_an_output_of_zero_stops_rather_than_spinning(self):
        stalled = simulate(50, 0, soil_output=0, rock_output=0)
        assert stalled.unfinished and stalled.days == []

    def test_rock_only_and_soil_only_jobs(self):
        assert simulate(0, 40, soil_output=20, rock_output=10, decay=0).total_days == 4
        assert simulate(40, 0, soil_output=20, rock_output=10, decay=0).total_days == 2


class TestMaterialsComeFromGeometry:
    """Materials are computed from the sampling rules, not estimated — so they move when the
    schedule moves."""

    def test_the_workbook_quantities(self):
        geometry = MaterialGeometry()
        assert geometry.soil_tubes(60) == 30                     # a liner every 2 m
        assert geometry.soil_into_tubes_m(60) == 15              # 30 × 0.5 m
        assert geometry.soil_into_boxes_m(60) == 45              # the rest is compressed into boxes
        assert geometry.soil_boxes(60) == 2                      # ROUNDUP(45 / 30)
        assert geometry.rock_boxes(72) == 18                     # ROUNDUP(72 / 4)
        assert geometry.total_boxes(60, 72) == 20
        assert geometry.grout_litres(132) == pytest.approx(663.5043684381643)

    def test_soil_and_rock_never_share_a_box(self):
        geometry = MaterialGeometry()
        # Rounded up separately: 2 + 18, not ROUNDUP((45 + 72) / something).
        assert geometry.total_boxes(60, 72) == geometry.soil_boxes(60) + geometry.rock_boxes(72)

    def test_a_derivation_is_recorded_on_every_computed_line(self, sheet):
        for key in ("wooden_box", "soil_tube", "cement_grout"):
            assert sheet.line(key).derivation, f"{key} must say how its quantity was reached"


class TestTheResourceSheet:
    def test_quantities_come_from_the_duration_drivers(self, sheet, duration):
        # Plant and staff are on site four days longer than the drilling itself.
        assert sheet.qty_of("rig") == duration.total_days + hke.MOB_DAYS == 15
        assert sheet.qty_of("fuel") == duration.total_days == 11

    def test_the_class_subtotals_match_the_workbook(self, sheet):
        assert sheet.by_class() == {
            "plant": 14760.0, "equipment": 11439.0, "labour": 75000.0, "supervision": 93600.0,
            "subcontract": 18825.0, "material": 25905.13, "consumable": 8800.0,
            "other": 2128.0, "transport": 13000.0,
        }

    def test_the_totals_match_the_workbook(self, sheet):
        assert sheet.total() == round(hke.EXPECT_COST_TOTAL, 2)
        assert sheet.selling() == round(hke.EXPECT_SELLING_TOTAL, 2)

    def test_a_coefficient_is_the_share_this_job_consumes(self, sheet):
        # A project manager across three jobs; water barriers that will see five more.
        assert sheet.line("pm").unit_cost() == 3000 * 0.33
        assert sheet.total_of("water_barriers") == 665 * 16 * 0.2 == 2128

    def test_one_day_of_the_spread(self, sheet):
        assert sheet.daily_cost(hke.DAILY_KEYS) == hke.EXPECT_DAILY_COST

    def test_an_unknown_line_is_named_not_silently_zero(self, sheet):
        with pytest.raises(KeyError, match="no resource line"):
            sheet.total_of("nonexistent")


class TestTheTenRates:
    """The regression that the whole design rests on."""

    @pytest.mark.parametrize("ref", sorted(hke.EXPECT_RATES))
    def test_rate_reproduces_the_workbook_to_the_cent(self, sheet, ref):
        breakdown = price_item(hke.recipes()[ref], [sheet])
        assert breakdown.rate == round(hke.EXPECT_RATES[ref], 2)

    def test_a_drilling_rate_is_days_times_daily_cost_over_metres(self, sheet, duration):
        # Hand-computed: 3.110803324099723 × 12,986.60 × 1.33 ÷ 60 m.
        expected = round(duration.soil_days * hke.EXPECT_DAILY_COST * 1.33 / hke.SOIL_M, 2)
        assert price_item(hke.recipes()["C"], [sheet]).rate == expected == 895.51

    def test_a_lump_item_carries_no_rate_divisor(self, sheet):
        breakdown = price_item(hke.recipes()["A"], [sheet])
        assert breakdown.lump and breakdown.divisor == 1.0
        assert "the amount is the rate" in breakdown.formula

    def test_every_rate_shows_its_working(self, sheet):
        breakdown = price_item(hke.recipes()["C"], [sheet])
        assert breakdown.formula and breakdown.terms
        first = breakdown.terms[0]
        assert {"label", "key", "units", "unit_cost", "value"} <= set(first)

    def test_a_zero_divisor_leaves_the_item_unpriced_and_says_why(self, sheet):
        # Not a crash — one bad item must not stop the other twenty-six pricing. But not a silent
        # zero either: it comes back unpriced, with the reason, for the guards to flag.
        breakdown = price_item(
            RateRecipe(full_ref="X", terms=[RecipeTerm(key="rig", units=1)], divisor=0,
                       divisor_label="m"),
            [sheet])
        assert breakdown.rate is None
        assert "the m is zero" in breakdown.formula
        assert "rather than guessed" in breakdown.formula
        assert breakdown.cost > 0, "the cost is still known; only the rate cannot be formed"

    def test_a_recipe_needing_days_without_a_duration_says_so(self, sheet):
        bare = sheet.model_copy(update={"duration": None})
        recipe = RateRecipe(full_ref="X", terms=[RecipeTerm(key="rig", units=1)],
                            days=DAYS_SOIL, divisor=10)
        with pytest.raises(ValueError, match="no duration model"):
            price_item(recipe, [bare])
