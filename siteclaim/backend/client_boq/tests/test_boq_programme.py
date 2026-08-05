"""The production model: quantities to work-days, and the checks that come with them.

The rule these defend: **the model is the estimator's, and the evidence is the app's.**

Every band, threshold and coefficient lives on an editable object, so these tests do two things at
once — they pin the reference run (defaults must reproduce ``GI_Costing_Template.xlsx``) and they
prove the model can be changed without the engine caring.

The worked example throughout is ND/2025/04: 91 holes, 2,300 m soil, 600 m rock, 100 m artificial
hard material. Every expected figure below was computed from the template's own formulas.

One finding is asserted rather than smoothed over: the model derives about 1,431 hours of standing
time where the client's Bill 2.3 carries 455. A three-fold gap on a remeasured item is exactly the
kind of thing this engine exists to put in front of somebody.
"""

from __future__ import annotations

import pytest

from client_boq.boq.empirical import Band
from client_boq.boq.model import default_model
from client_boq.boq.programme import Quantities, against_the_bill, derive

# ND/2025/04, from Bill 2 items 2.2, 2.4, 2.5 and 2.6.
TECHNOPOLE = Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0)


@pytest.fixture
def model():
    return default_model()


@pytest.fixture
def programme(model):
    return derive(TECHNOPOLE, model)


class TestTheReferenceRun:
    """The defaults must reproduce the template. Not a rule for the user — a check on us."""

    def test_the_rock_fraction_is_read_from_the_bill_not_typed(self, programme):
        assert programme.rock_fraction == pytest.approx(700 / 3000)      # 23.3%

    def test_that_fraction_picks_the_second_band(self, programme):
        assert programme.band.label == "15% to 35% rock"
        assert programme.band.rate == 3.69 and programme.band.holes == 32

    def test_the_banded_total_is_the_pricing_basis(self, programme):
        assert programme.work_days == pytest.approx(3000 / 3.69)         # 813.0
        assert programme.work_days == pytest.approx(813.008, abs=0.01)

    def test_the_productivity_band_carries_the_exposure(self, programme):
        assert programme.work_days_p10 == pytest.approx(813.008 * 0.62, abs=0.01)
        assert programme.work_days_p90 == pytest.approx(813.008 * 1.55, abs=0.01)

    def test_the_split_rate_cross_check_lands_where_the_template_says(self, programme):
        # The template's own cells carry the coefficients rounded to two significant figures
        # (4.7 / 7.3 / 2.6), and it computes with those. `empirical.FITTED` keeps the unrounded fit.
        assert programme.setup_days == pytest.approx(91 * 4.7)
        assert programme.soil_days == pytest.approx(2300 / 7.3)
        assert programme.rock_days == pytest.approx(700 / 2.6)
        assert programme.method_b_days == pytest.approx(1012.0, abs=0.5)

    def test_the_two_methods_land_just_inside_the_stop(self, programme):
        # +24.5% on the reference contract — marginal, and one nudge from "do not price".
        assert programme.divergence == pytest.approx(0.245, abs=0.005)
        convergence = next(c for c in programme.checks if c.key == "convergence")
        assert convergence.verdict == "marginal" and not convergence.blocking

    def test_rigs_are_derived_and_rounded_up(self, programme):
        assert programme.work_days_available_per_rig == 520.0            # 20 months x 26 days
        assert programme.rigs_exact == pytest.approx(1.5635, abs=0.001)
        assert programme.rigs_required == 2

    def test_calendar_days_carry_the_weather_not_the_production_rate(self, programme):
        assert programme.calendar_days == pytest.approx(813.008 * 1.18, abs=0.05)

    def test_the_derived_material_quantities(self, programme):
        assert programme.mazier_samples == 1150                          # 2300 / 2
        assert programme.soil_in_tubes_m == pytest.approx(575.0)         # 1150 x 0.5
        assert programme.soil_boxes == 58                                # ceil(1725 / 30)
        assert programme.rock_boxes == 175                               # ceil(700 / 4)
        assert programme.core_boxes == 233
        assert programme.grout_litres == pytest.approx(15079.6, abs=1.0)

    def test_soil_and_rock_boxes_round_up_separately_because_they_cannot_share(self, programme):
        assert programme.core_boxes == programme.soil_boxes + programme.rock_boxes


class TestTheAllocationThatReconcilesTheTwoMethods:
    """The band sets the total; the split sets how it divides. This is the factor between them."""

    def test_the_scaled_split_sums_back_to_the_banded_total(self, programme):
        total = sum(programme.scaled_days(k) for k in ("setup", "soil", "rock"))
        assert total == pytest.approx(programme.work_days, abs=0.01)

    def test_the_allocation_is_a_over_b(self, programme):
        assert programme.allocation == pytest.approx(
            programme.work_days / programme.method_b_days)

    def test_the_split_keeps_its_shape_after_scaling(self, programme):
        raw = programme.soil_days / programme.rock_days
        scaled = programme.scaled_days("soil") / programme.scaled_days("rock")
        assert raw == pytest.approx(scaled)


class TestTheChecks:
    def test_the_depth_check_says_this_tender_is_inside_the_band(self, programme):
        depth = next(c for c in programme.checks if c.key == "depth")
        assert depth.verdict == "ok"
        assert depth.value == pytest.approx(32.97 / 34.8 - 1, abs=0.005)   # -5.3%

    def test_extrapolating_beyond_the_calibration_depth_is_named(self, model):
        deep = Quantities(holes=10, soil_m=800.0, rock_m=200.0, hard_m=0.0)  # 100 m mean depth
        depth = next(c for c in derive(deep, model).checks if c.key == "depth")
        assert depth.verdict == "marginal" and "extrapolated" in depth.message

    def test_a_thin_band_says_the_residual_factor_is_carrying_the_estimate(self, model):
        thin = Quantities(holes=20, soil_m=900.0, rock_m=100.0)          # 10% rock -> n = 12 band
        confidence = next(c for c in derive(thin, model).checks if c.key == "band_confidence")
        assert confidence.verdict == "ok" and "12 holes" in confidence.message

    def test_divergent_methods_say_do_not_price(self, model):
        # One hole of 3,000 m: the split model's per-hole set-up almost vanishes, the band does not.
        odd = Quantities(holes=1, soil_m=2300.0, rock_m=700.0)
        convergence = next(c for c in derive(odd, model).checks if c.key == "convergence")
        assert convergence.verdict == "stop" and convergence.blocking
        assert "before pricing" in convergence.message

    def test_a_blocking_check_reports_and_does_not_refuse(self, model):
        odd = derive(Quantities(holes=1, soil_m=2300.0, rock_m=700.0), model)
        # The sweep is the app's only hard stop. This says so loudly and still produces a programme.
        assert odd.stops() and odd.usable()


class TestAgainstTheBill:
    def test_the_standing_time_gap_on_the_reference_contract_is_reported(self, programme):
        # ~1,431 h derived against 455 h billed. Nothing else in the app would surface this.
        assert programme.standing_hours == pytest.approx(1430.9, abs=1.0)
        check = against_the_bill(programme, billed_standing_hours=455.0)
        assert check.verdict == "marginal"
        assert "1,431" in check.message and "455" in check.message and "3.1x" in check.message

    def test_a_standing_time_that_agrees_says_so_quietly(self, programme):
        assert against_the_bill(programme, 1400.0).verdict == "ok"

    def test_no_billed_figure_means_no_claim(self, programme):
        assert against_the_bill(programme, None) is None


class TestTheModelIsTheEstimators:
    """Editable structure, fixed arithmetic. These prove the first half."""

    def test_a_refitted_band_moves_the_programme(self, model):
        model.bands.bands[1] = model.bands.bands[1].model_copy(update={"rate": 5.0, "holes": 60})
        assert derive(TECHNOPOLE, model).work_days == pytest.approx(3000 / 5.0)

    def test_a_new_band_can_be_added_and_is_selected(self, model):
        model.bands.bands.append(
            Band(label="20% to 25% rock", lower=0.20, rate=9.9, holes=40,
                 calibration_depth_m=33.0))
        assert derive(TECHNOPOLE, model).band.label == "20% to 25% rock"

    def test_a_job_below_every_band_is_reported_rather_than_clamped(self, model):
        model.bands.bands = [b for b in model.bands.bands if b.lower >= 0.35]
        result = derive(TECHNOPOLE, model)
        assert not result.usable()
        assert "there is no band for it" in " ".join(result.problems)

    def test_the_residual_site_factor_scales_the_whole_programme(self, model):
        model.inputs["residual_site_factor"] = 1.2
        assert derive(TECHNOPOLE, model).work_days == pytest.approx(3000 / 3.69 * 1.2)

    def test_the_thresholds_are_the_estimators_too(self, model):
        model.method.divergent_threshold = 0.20
        convergence = next(c for c in derive(TECHNOPOLE, model).checks if c.key == "convergence")
        assert convergence.verdict == "stop", "24.6% now exceeds the tightened 20% stop"

    def test_changing_the_sample_interval_changes_the_tubes_and_the_boxes(self, model):
        model.inputs["mazier_interval_m"] = 1.0
        result = derive(TECHNOPOLE, model)
        assert result.mazier_samples == 2300
        assert result.soil_boxes == 39, "more soil goes into tubes, so fewer boxes"


class TestWhatItRefusesToGuess:
    def test_no_metres_means_no_programme(self, model):
        result = derive(Quantities(holes=10), model)
        assert not result.usable() and "no drilled length" in " ".join(result.problems)

    def test_no_holes_means_the_mean_depth_cannot_be_worked_out(self, model):
        result = derive(Quantities(soil_m=100.0), model)
        assert "per-hole set-up" in " ".join(result.problems)
