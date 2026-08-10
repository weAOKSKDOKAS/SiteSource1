"""Two silent zeroes in the costing engine, both probed before fixing.

**A cross-check that never ran reported agreement.** With the split rates zeroed (a half-configured
model), `derive()` skipped `divergence`/`allocation` inside `if programme.method_b_days:` — so the
convergence check read a divergence of 0.0 and said "the two methods agree to 0.0%" while Method A
said 623 work-days and Method B said nothing at all. Worse, `allocation` stayed 1.0 over a zero
split, so `scaled_days()` returned 0 for every kind and the build-up priced ALL drilling at $0
total cost. A model misconfiguration surfaced as a confident agreement and a free programme.

**A typo'd input key priced at zero.** `model.value()` defaults an absent input to 0.0 — right for
an optional knob, wrong for a NAMED read: a mark-up component misspelt by one letter took the whole
risk loading out of the selling factor (probed: ×1.278 instead of ×1.342), and a basis row's
`unit_cost_key` typo prices its material at $0. Nothing reported either. `problems()` now checks
that every key a step or a basis row names actually exists.
"""

import pytest

from client_boq.boq import buildup as bu
from client_boq.boq.model import FixedComponent, default_model
from client_boq.boq.programme import Quantities, derive

QTY = Quantities(holes=91, soil_m=1800.0, rock_m=500.0)


def _zero_split(model):
    model.inputs["setup_days_per_hole"] = 0.0
    model.inputs["soil_m_per_day"] = 0.0
    model.inputs["rock_m_per_day"] = 0.0
    return model


# -- the cross-check cannot pretend to agree -------------------------------------------------------
def test_a_cross_check_that_never_ran_is_a_stop_not_an_agreement():
    programme = derive(QTY, _zero_split(default_model()))
    convergence = next(c for c in programme.checks if c.key == "convergence")

    assert convergence.verdict == "stop"
    assert "no work-days" in convergence.message
    assert "agree" not in convergence.message


def test_the_programme_reports_it_as_a_problem_and_is_not_usable():
    programme = derive(QTY, _zero_split(default_model()))

    assert any("Method B produced no work-days" in p for p in programme.problems)
    assert programme.usable() is False


def test_the_band_checks_still_run_without_method_b():
    """Depth and band-confidence are about the BAND, which Method A used either way."""
    programme = derive(QTY, _zero_split(default_model()))
    keys = {c.key for c in programme.checks}
    assert {"convergence", "depth", "band_confidence"} <= keys


def test_a_configured_model_still_converges_normally():
    """The guard must not cost the ordinary case."""
    programme = derive(QTY, default_model())
    convergence = next(c for c in programme.checks if c.key == "convergence")

    assert programme.method_b_days > 0
    assert convergence.verdict in {"ok", "marginal", "stop"}
    assert "never ran" not in convergence.message
    assert programme.usable() is True


def test_partial_split_rates_still_count_as_method_b_running():
    """Only ALL-zero splits mean the method never ran — a soil-only job with no rock rate is a
    different (legitimate) state and must not trip the stop."""
    model = default_model()
    model.inputs["rock_m_per_day"] = 0.0
    programme = derive(Quantities(holes=10, soil_m=500.0, rock_m=0.0), model)

    assert programme.method_b_days > 0
    assert not any("Method B produced no work-days" in p for p in programme.problems)


# -- a named key must exist -------------------------------------------------------------------------
def test_a_typoed_markup_component_is_reported_not_zeroed():
    model = default_model()
    model.markup[1].components = ["risk_loadng"]          # the probe's typo

    problems = model.problems()
    assert any("risk_loadng" in p and "does not exist" in p for p in problems)


def test_a_typoed_unit_cost_key_is_reported():
    model = default_model()
    row = model.basis_index()["soil_tubes"]
    row.unit_cost_key = "soil_tub_cost"                   # one letter out

    assert any("soil_tub_cost" in p for p in model.problems())


def test_a_typoed_fixed_component_rate_key_is_reported():
    model = default_model()
    mobilise = model.basis_index()["mobilise"]
    mobilise.components.append(FixedComponent(label="Barge", rate_key="barge_rate",
                                              qty_key="barge_days"))

    problems = model.problems()
    assert any("barge_rate" in p for p in problems)
    assert any("barge_days" in p for p in problems)


def test_the_default_model_names_no_missing_keys():
    """The template's own model must pass its own validation — the guard is for edits, not for the
    baseline."""
    assert default_model().problems() == []


def test_adding_the_missing_input_clears_the_problem():
    model = default_model()
    mobilise = model.basis_index()["mobilise"]
    mobilise.components.append(FixedComponent(label="Barge", rate_key="barge_rate",
                                              qty_key="barge_days"))
    model.inputs["barge_rate"] = 20000.0
    model.inputs["barge_days"] = 2.0

    assert model.problems() == []
    buildup = bu.build(derive(QTY, model), model)
    assert buildup.index()["mobilise"].total_cost == pytest.approx(
        5000 * 2 + 1500 * 2 + 20000 * 2, abs=0.01), "and the barge now actually prices"
