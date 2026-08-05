"""The daily cost of the spread, and how it reaches a rate.

Two rules these defend.

**The two day-costs stay apart.** Plant, labour and consumables scale with the rig count; the site
team does not. Merging them prices supervision per rig — over-recovering on a one-rig job and
under-recovering on a three-rig one — and the error is invisible until the job is finished.

**Ten percent is not ten percent.** A loading adds to cost (×1.100); a margin is taken on the selling
price (×1.111). Treating the second as the first under-recovers on every rate in the bill.

Figures are the reference template's, on ND/2025/04 quantities.
"""

from __future__ import annotations

import pytest

from client_boq.boq.buildup import build, build_spread
from client_boq.boq.model import (
    CHARGE_CONTRACT_DAY,
    CHARGE_RIG_DAY,
    MARKUP_LOADING,
    MARKUP_ON_SELLING,
    MarkupStep,
    SpreadLine,
    default_model,
)
from client_boq.boq.programme import Quantities, derive

TECHNOPOLE = Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0)


@pytest.fixture
def model():
    return default_model()


@pytest.fixture
def programme(model):
    return derive(TECHNOPOLE, model)


@pytest.fixture
def spread(programme, model):
    return build_spread(programme, model)


@pytest.fixture
def buildup(programme, model, spread):
    return build(programme, model, spread)


class TestTheDailyCost:
    def test_the_rig_day_cost_is_plant_labour_and_consumables(self, spread):
        # Plant 1,420 × 1.23 = 1,746.6 · driller 2,000 · workers 2 × 1,500 · fuel 600 · sundries 200
        assert spread.cost_per_rig_day == pytest.approx(1746.60 + 2000 + 3000 + 800, abs=0.01)

    def test_the_contract_day_cost_is_the_site_team_only(self, spread):
        # engineer 2,000 · foreman 2,000 · geologist 0.5 × 2,500 · PM 0.33 × 3,000
        assert spread.cost_per_contract_day == pytest.approx(2000 + 2000 + 1250 + 990, abs=0.01)

    def test_plant_carries_the_standby_factor_because_it_is_held_all_period(self, spread):
        rig = next(r for r in spread.rows if r.key == "drill_rig")
        assert rig.multiplier == 1.23 and rig.cost_per_day == pytest.approx(615.0)

    def test_a_shared_person_is_charged_by_their_allocation(self, spread):
        pm = next(r for r in spread.rows if r.key == "project_manager")
        assert pm.multiplier == 0.33 and pm.cost_per_day == pytest.approx(990.0)

    def test_one_site_team_covers_this_job(self, spread):
        assert spread.site_teams_required == 1, "1.56 rigs, one team supervises three"

    def test_a_fourth_rig_buys_a_second_team(self, programme, model):
        model.inputs["contract_period_months"] = 8          # squeeze the programme
        tighter = derive(TECHNOPOLE, model)
        assert tighter.rigs_exact == pytest.approx(3.909, abs=0.01)
        assert build_spread(tighter, model).site_teams_required == 2

    def test_the_p90_exposure_is_carried_beside_the_p50(self, spread, programme):
        assert spread.rig_cost_programme_p90 > spread.rig_cost_programme
        assert spread.rig_cost_programme_p90 == pytest.approx(
            spread.cost_per_rig_day * programme.work_days_p90)


class TestTheItemBuildup:
    def test_the_three_drilling_shares_sum_to_the_banded_programme(self, buildup, programme, spread):
        drilling = sum(buildup.index()[k].quantity
                       for k in ("soil_drilling", "rock_drilling", "setup_move"))
        assert drilling == pytest.approx(programme.work_days, abs=0.01)

    def test_soil_drilling_is_days_times_day_cost_over_soil_metres(self, buildup, programme, spread):
        row = buildup.index()["soil_drilling"]
        assert row.total_cost == pytest.approx(row.quantity * spread.cost_per_rig_day)
        assert row.cost_per_unit == pytest.approx(row.total_cost / 2300.0)

    def test_rock_drilling_divides_by_rock_plus_hard_material(self, buildup):
        row = buildup.index()["rock_drilling"]
        assert row.divisor == pytest.approx(700.0)
        assert "hard-material" in row.divisor_name

    def test_the_site_team_leaves_as_a_monthly_rate_for_bill_one(self, buildup, spread):
        row = buildup.index()["site_team"]
        assert row.cost_per_unit == pytest.approx(spread.site_team_cost_programme / 20.0)
        assert "never inside a drilling rate" in row.derivation

    def test_mobilisation_is_its_components_and_says_which(self, buildup):
        row = buildup.index()["mobilise"]
        assert row.total_cost == pytest.approx(5000 * 2 + 1500 * 2)
        assert "Crane lorry" in row.derivation and "Truck" in row.derivation

    def test_a_lump_rows_rate_is_its_own_amount(self, buildup):
        row = buildup.index()["mobilise"]
        assert row.cost_per_unit == pytest.approx(row.total_cost)

    def test_materials_come_from_the_derived_quantities_not_from_typing(self, buildup, programme):
        assert buildup.index()["soil_tubes"].quantity == programme.mazier_samples
        assert buildup.index()["core_boxes"].quantity == programme.core_boxes
        assert buildup.index()["backfill_grout"].quantity == pytest.approx(programme.grout_litres)

    def test_grout_is_spread_over_the_holes(self, buildup, programme):
        row = buildup.index()["backfill_grout"]
        assert row.cost_per_unit == pytest.approx(row.total_cost / 91)

    def test_every_row_shows_its_working(self, buildup):
        assert all(row.derivation for row in buildup.rows if not row.problem)

    def test_the_direct_total_is_the_sum_of_the_rows(self, buildup):
        assert buildup.total_direct_cost == pytest.approx(sum(r.total_cost for r in buildup.rows))


class TestTheMarkupChain:
    def test_the_combined_factor_is_the_template_s(self, buildup):
        # overhead 1.15 × risk 1.05 × margin 1/(1−0.10) = 1.34166…
        assert buildup.selling_factor == pytest.approx(1.15 * 1.05 / 0.9, abs=1e-9)

    def test_a_margin_is_taken_on_the_selling_price_not_added_to_cost(self, model):
        margin = next(s for s in model.markup if s.key == "margin")
        assert margin.factor(model.inputs) == pytest.approx(1 / 0.9)
        assert margin.factor(model.inputs) != pytest.approx(1.10), "1.111, not 1.100"

    def test_the_same_ten_percent_as_a_loading_is_a_different_number(self, model):
        loading = MarkupStep(key="x", label="x", kind=MARKUP_LOADING, components=["margin"])
        assert loading.factor(model.inputs) == pytest.approx(1.10)

    def test_a_hundred_percent_margin_is_refused_rather_than_infinite(self, model):
        model.inputs["margin"] = 1.0
        assert any("no finite answer" in p for p in model.problems())
        assert any("infinite" in p for p in build(derive(TECHNOPOLE, model), model).problems)

    def test_the_chain_is_reported_step_by_step(self, buildup):
        assert [s["key"] for s in buildup.markup_steps] == ["overhead", "risk", "margin"]
        assert all("factor" in s for s in buildup.markup_steps)


class TestTheModelIsTheEstimators:
    def test_a_resource_can_be_removed(self, programme, model):
        before = build_spread(programme, model).cost_per_rig_day
        model.spread = [l for l in model.spread if l.key != "drill_rig"]
        assert build_spread(programme, model).cost_per_rig_day == pytest.approx(before - 615.0)

    def test_a_resource_can_be_added(self, programme, model):
        model.spread.append(SpreadLine(key="barge", label="Barge", block="PLANT", multiplier=1.0,
                                       rate=8000.0, charge=CHARGE_RIG_DAY))
        assert build_spread(programme, model).cost_per_rig_day > 8000.0

    def test_moving_a_person_onto_the_rig_day_changes_which_total_carries_them(self, programme, model):
        rig_before = build_spread(programme, model).cost_per_rig_day
        for line in model.spread:
            if line.key == "geologist":
                line.charge = CHARGE_RIG_DAY
        after = build_spread(programme, model)
        assert after.cost_per_rig_day == pytest.approx(rig_before + 1250.0)
        # 6,240 a contract-day becomes 4,990: engineer 2,000 + foreman 2,000 + PM 990.
        assert after.cost_per_contract_day == pytest.approx(4990.0)

    def test_a_driver_can_be_repointed(self, programme, model):
        for row in model.basis_rows:
            if row.key == "backfill_grout":
                row.divisor = "soil_m"
        row = build(programme, model).index()["backfill_grout"]
        assert row.cost_per_unit == pytest.approx(row.total_cost / 2300.0)

    def test_the_chain_can_be_reordered_without_changing_the_product(self, programme, model):
        before = build(programme, model).selling_factor
        model.markup = list(reversed(model.markup))
        assert build(programme, model).selling_factor == pytest.approx(before)

    def test_a_markup_step_can_be_dropped(self, programme, model):
        model.markup = [s for s in model.markup if s.key != "risk"]
        assert build(programme, model).selling_factor == pytest.approx(1.15 / 0.9)

    def test_an_extra_mobilisation_component_lands_in_the_cost(self, programme, model):
        from client_boq.boq.model import FixedComponent
        model.inputs["barge_rate"] = 20000.0
        model.inputs["barge_days"] = 1.0
        for row in model.basis_rows:
            if row.key == "mobilise":
                row.components.append(FixedComponent(label="Barge", rate_key="barge_rate",
                                                     qty_key="barge_days"))
        assert build(programme, model).index()["mobilise"].total_cost == pytest.approx(33000.0)


class TestWhatItRefusesToGuess:
    def test_a_zero_divisor_leaves_the_row_unpriced_and_says_why(self, model):
        no_rock = derive(Quantities(holes=91, soil_m=3000.0), model)
        row = build(no_rock, model).index()["rock_drilling"]
        assert row.cost_per_unit is None
        assert "no rate can be formed" in row.problem and "rather than guessed" in row.problem

    def test_one_unpriceable_row_does_not_stop_the_others(self, model):
        no_rock = derive(Quantities(holes=91, soil_m=3000.0), model)
        result = build(no_rock, model)
        assert result.index()["soil_drilling"].cost_per_unit is not None
        assert result.problems

    def test_a_fixed_row_with_no_components_says_so_rather_than_pricing_at_nothing(
            self, programme, model):
        for row in model.basis_rows:
            if row.key == "mobilise":
                row.components = []
        row = build(programme, model).index()["mobilise"]
        assert "prices at nothing" in row.problem
