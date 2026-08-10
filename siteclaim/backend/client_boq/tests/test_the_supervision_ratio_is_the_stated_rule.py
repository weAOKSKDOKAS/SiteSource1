"""The supervision ratio: 6 rigs per 1 team, as stated — a documented default, not a hardcode.

The template carried 3.0 and `buildup.py` fell back to 3.0 twice more. The stated rule is **6 rigs
per 1 GFT**, so 6.0 is now the default everywhere the ratio can be read — and it remains an
ordinary model input (`site_team_supervises_rigs`), edited per tender like anything else.

THE BEHAVIOUR CHANGE, PINNED ON PURPOSE: at 6:1 the team count HALVES for any job between 3 and 6
exact rigs. On the default spread that removes ~$6,240 per contract-day of supervision from every
such estimate. That shift is what moving to the stated rule MEANS, and these tests pin it so it
reads as a decision rather than a drift.

THE OPEN QUESTION, surfaced not guessed: is "site team" the same resource as a GFT? The SITE TEAM
spread block is engineer + foreman + geologist + PM; if the 6:1 rule counts GFTs only, the ratio
and the block's membership are two different judgements. The assumptions register carries this as a
low-confidence row for a human to answer.
"""

import pytest

from client_boq.boq import assumptions as assum
from client_boq.boq.buildup import build, build_spread
from client_boq.boq.model import DEFAULT_INPUTS, default_model
from client_boq.boq.programme import Quantities, derive

TECHNOPOLE = Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0)


def _spread_for(months: float, ratio: float = None):
    model = default_model()
    model.inputs["contract_period_months"] = months
    if ratio is not None:
        model.inputs["site_team_supervises_rigs"] = ratio
    programme = derive(TECHNOPOLE, model)
    return programme, build_spread(programme, model), model


# -- the default is the stated rule ------------------------------------------------------------
def test_the_default_ratio_is_six():
    assert DEFAULT_INPUTS["site_team_supervises_rigs"] == 6.0
    assert default_model().value("site_team_supervises_rigs") == 6.0


def test_the_spread_reads_the_ratio_from_the_model():
    programme, spread, _ = _spread_for(months=20)
    assert spread.site_team_supervises == 6.0


def test_the_ratio_is_an_ordinary_input_not_a_hardcode():
    """Edit it per tender and the team count follows — the whole point of it being a model value."""
    programme, spread_at_6, _ = _spread_for(months=8)
    _, spread_at_3, _ = _spread_for(months=8, ratio=3.0)

    assert programme.rigs_exact == pytest.approx(3.909, abs=0.01)
    assert spread_at_6.site_teams_required == 1
    assert spread_at_3.site_teams_required == 2


def test_the_halving_the_rule_change_causes_is_pinned():
    """3.909 rigs: two teams at 3:1, ONE team at the stated 6:1 — the supervision cost halves.
    This is the intended consequence of adopting the stated rule, pinned so it cannot read as an
    accident later."""
    _, at_six, model = _spread_for(months=8)
    _, at_three, _ = _spread_for(months=8, ratio=3.0)

    assert at_six.site_teams_required == 1 and at_three.site_teams_required == 2
    assert at_six.site_team_cost_programme == pytest.approx(
        at_three.site_team_cost_programme / 2)


def test_seven_exact_rigs_still_buy_a_second_team():
    """The mechanism survives the new default: past 6 rigs, ceil buys the second team."""
    model = default_model()
    model.inputs["contract_period_months"] = 4.4          # push rigs_exact past 6
    programme = derive(TECHNOPOLE, model)
    assert programme.rigs_exact > 6.0
    assert build_spread(programme, model).site_teams_required == 2


def test_a_zero_or_missing_ratio_falls_back_to_the_stated_rule():
    model = default_model()
    model.inputs["site_team_supervises_rigs"] = 0.0       # nonsense in, rule out
    programme = derive(TECHNOPOLE, model)
    assert build_spread(programme, model).site_team_supervises == 6.0


# -- the open question is surfaced, not guessed ------------------------------------------------------
def test_the_register_carries_the_gft_question_for_a_human():
    model = default_model()
    programme = derive(TECHNOPOLE, model)
    spread = build_spread(programme, model)
    register = assum.build(programme, model, build(programme, model, spread), spread)

    row = next(r for r in register.rows if r.key == "supervision_ratio")
    assert row.confidence == "Low"
    assert not row.derived, "a judgement a human can verdict, not a derived fact"
    assert "is 'site team' the same resource as a GFT?" in row.basis
    assert "6 rigs per 1 GFT" in row.basis
    assert "3:1" in row.basis and "halves" in row.basis, "the change itself is disclosed on the row"


def test_the_workbook_prints_the_ratio_from_the_model():
    """The one-way spine: the sheet shows the model's value, never its own."""
    import io

    openpyxl = pytest.importorskip("openpyxl")
    from client_boq.boq.costing_workbook import build_workbook
    from client_boq.boq.costing import PricedBQ

    model = default_model()
    programme = derive(TECHNOPOLE, model)
    spread = build_spread(programme, model)
    buildup = build(programme, model, spread)
    register = assum.build(programme, model, buildup, spread)
    data = build_workbook(model, programme, spread, buildup, PricedBQ(), register)

    book = openpyxl.load_workbook(io.BytesIO(data))
    inputs = book["01 Inputs"]
    row = next(r for r in inputs.iter_rows(min_col=2, max_col=3)
               if r[0].value == "One site team supervises")
    assert row[1].value == 6.0
