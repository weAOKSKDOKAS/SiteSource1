"""The rig count is computed as a curve over n, and the machine PROPOSES the cheapest feasible one.

The identity that makes the curve honest: total rig-days do not move with n (n × work_days/n), so
"more rigs cost more" is wrong on its face. What moves is supervision, mobilisations (one per rig),
and how long the time-related preliminaries run.

RE-ANCHORED IN THE OPEN alongside the site-team/GFT split: supervision is two terms now, and they
pull in opposite directions. The GFT steps UP with n (one per `gft_ratio` rigs) but runs for a
shorter duration; the SITE team's count is fixed and only its duration falls. Both are still on the
curve; the mechanism each test pinned is unchanged, only the resource it names.
Deterministic throughout — no model call.
"""

import math

import pytest

from client_boq.boq import optimiser as opt
from client_boq.boq.model import default_model
from client_boq.boq.programme import Quantities, derive

TECHNOPOLE = Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0)


def _programme(model=None, **inputs):
    model = model or default_model()
    model.inputs.update(inputs)
    return derive(TECHNOPOLE, model), model


# -- the curve ---------------------------------------------------------------------------------
def test_every_n_from_one_to_twelve_is_priced():
    programme, model = _programme()
    curve = opt.optimise(programme, model)
    assert [o.n for o in curve.options] == list(range(1, 13))


def test_total_rig_days_do_not_move_with_n():
    """The identity the whole comparison rests on."""
    programme, model = _programme()
    curve = opt.optimise(programme, model)
    rig_costs = {round(o.rig_cost, 2) for o in curve.options}
    assert len(rig_costs) == 1, "n × rig_day × (work_days/n) is constant"


def test_duration_halves_when_rigs_double():
    programme, model = _programme()
    curve = opt.optimise(programme, model)
    by_n = {o.n: o for o in curve.options}
    assert by_n[2].duration_work_days == pytest.approx(by_n[1].duration_work_days / 2)
    assert by_n[8].duration_work_days == pytest.approx(by_n[4].duration_work_days / 2)


def test_gfts_step_at_the_stated_ratio_and_site_teams_do_not():
    programme, model = _programme()
    curve = opt.optimise(programme, model)
    by_n = {o.n: o for o in curve.options}
    assert by_n[6].gfts == 1 and by_n[7].gfts == 2, "6:1 — the seventh rig buys the second GFT"
    assert {o.site_teams for o in curve.options} == {1.0}, "the site team is per SITE, not per rig"


def test_mobilisation_rises_one_spread_at_a_time():
    programme, model = _programme()
    curve = opt.optimise(programme, model)
    mob_per_rig = curve.mob_per_rig
    assert mob_per_rig == pytest.approx(5000 * 2 + 1500 * 2), "the model's own mobilise components"
    for option in curve.options:
        assert option.mob_cost == pytest.approx(mob_per_rig * option.n)


def test_infeasible_counts_are_marked_not_dropped():
    """A count that does not fit the contract period stays ON the curve, named — the estimator
    should see what the deadline is costing, not have it hidden."""
    programme, model = _programme(contract_period_months=8.0)   # floor becomes 4 rigs
    curve = opt.optimise(programme, model)
    by_n = {o.n: o for o in curve.options}

    assert programme.rigs_required == 4
    assert not by_n[1].feasible and "does not fit" in by_n[1].note
    assert by_n[4].feasible
    assert curve.floor_n == 4


def test_the_proposal_is_the_cheapest_feasible_count():
    programme, model = _programme()
    curve = opt.optimise(programme, model)
    feasible = [o for o in curve.options if o.feasible]
    cheapest = min(feasible, key=lambda o: (o.total_cost, o.n))

    assert curve.proposal_n == cheapest.n
    assert curve.proposed().proposed is True
    assert sum(1 for o in curve.options if o.proposed) == 1


def test_a_tie_goes_to_fewer_rigs():
    """Same money, less plant standing on site."""
    programme, model = _programme()
    model.basis_rows = [r for r in model.basis_rows if r.driver != "fixed"]   # mob 0
    for line in model.spread:
        if line.charge == "contract_day":
            line.rate = 0.0                                                    # teams free
    curve = opt.optimise(programme, model)
    feasible = [o for o in curve.options if o.feasible]

    assert curve.proposal_n == min(o.n for o in feasible)


def test_time_running_prelims_pull_towards_more_rigs():
    """Give the site office a real monthly cost and a long duration starts costing — the curve
    must move the proposal to (or past) the point where the office closing sooner pays for the
    extra mobilisations."""
    programme, model = _programme()
    lean = opt.optimise(programme, model)
    office = next(line for line in model.spread if line.key == "prelim_office")
    office.rate = 300_000.0                                    # $/month, deliberately heavy
    heavy = opt.optimise(programme, model)

    assert curve_cost(lean, lean.proposal_n) != curve_cost(heavy, heavy.proposal_n)
    assert heavy.proposal_n >= lean.proposal_n
    assert heavy.prelims_per_day > 0


def curve_cost(curve, n):
    return next(o.total_cost for o in curve.options if o.n == n)


def test_an_unrated_prelim_is_named_not_silently_zero():
    programme, model = _programme()
    curve = opt.optimise(programme, model)
    assert any("no rate yet" in n for n in curve.notes), \
        "the default prelims are zero-rated on purpose, and the curve says the term is understated"


def test_a_model_with_no_fixed_row_says_the_mob_term_is_missing():
    programme, model = _programme()
    model.basis_rows = [r for r in model.basis_rows if r.driver != "fixed"]
    curve = opt.optimise(programme, model)
    assert any("mobilisation" in n and "$0" in n for n in curve.notes)


def test_a_programme_that_fits_nothing_is_a_finding_not_a_price():
    programme, model = _programme(contract_period_months=0.5)
    curve = opt.optimise(programme, model)
    assert curve.proposal_n is None
    assert any("does not fit the time allowed" in n for n in curve.notes)


def test_no_programme_means_nothing_to_compare():
    model = default_model()
    empty = derive(Quantities(), model)
    curve = opt.optimise(empty, model)
    assert curve.options == [] and curve.proposal_n is None


# -- the surface -------------------------------------------------------------------------------------
def test_the_costing_payload_carries_the_curve(tmp_path, monkeypatch):
    """`get_costing` is the screen's one read, and the curve rides on it — a consequence of the
    same programme and model, never a second computation path."""
    from fastapi.testclient import TestClient

    from client_boq.tests._bqfixture import build_bill_workbook

    pytest.importorskip("openpyxl")
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    client = TestClient(app)
    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as handle:
        imported = client.post(
            "/client-boq/boq/import", data={"set_id": "technopole-gi"},
            files={"file": (path.name, handle.read(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert imported.status_code == 200, imported.text

    body = client.get("/client-boq/costing/technopole-gi").json()
    assert "optimiser" in body
    assert [o["n"] for o in body["optimiser"]["options"]] == list(range(1, 13))
    assert body["optimiser"]["proposal_n"] is not None
    assert body["optimiser"]["gft_ratio"] == 6.0
    assert body["optimiser"]["site_teams"] == 1.0
