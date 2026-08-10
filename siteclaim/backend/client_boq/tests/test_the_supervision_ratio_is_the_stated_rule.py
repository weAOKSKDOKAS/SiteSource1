"""Supervision: TWO resources, counted two different ways — the site team and the GFT.

RE-ANCHORED IN THE OPEN. This file previously pinned a single resource: the SITE team scaled by
`ceil(rigs / site_team_supervises_rigs)` at the stated 6:1 rule. The human has since ruled that the
open question this file used to carry — *is "site team" the same resource as a GFT?* — is answered
**no**, and the two are separate:

* the **site team** (engineer + foreman + geologist + PM) manages a **site**. Its count is
  `site_count x site_team_per_site`, a coefficient with default 1, and it does **not** move with
  the rig count at all;
* the **GFT** manages **rigs**, at one per `gft_ratio` of them (the stated rule, default 6).

So the ratio mechanism this file pinned is still pinned — it has moved to the resource it was
always about. Every behaviour the old file asserted has a successor here: the default is still 6,
it is still an ordinary editable input, a zero still falls back to the rule, past six rigs still
buys a second one, the count still flows to the build-up and the workbook, and the register still
carries the row. What is NEW is the half the old shape could not express: the site team standing
still while the rig count runs 1 → 12, and the register row RESOLVING the question instead of
asking it.

THE BEHAVIOUR CHANGE, PINNED ON PURPOSE: site management stops multiplying with plant. On the
default spread at 3.909 exact rigs the site team used to be counted twice — $6,240 per contract-day
doubled to $12,480 — purely because a second rig group existed. It is now $6,240 whatever the rig
count, and the rig-driven cost has moved to a GFT line with its own rate.
"""

import math

import pytest

from client_boq.boq import assumptions as assum
from client_boq.boq.buildup import build, build_spread
from client_boq.boq.model import DEFAULT_INPUTS, RETIRED_INPUTS, default_model
from client_boq.boq.programme import Quantities, derive

TECHNOPOLE = Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0)


def _spread_for(months: float, ratio: float = None, *, sites: float = None,
                per_site: float = None):
    model = default_model()
    model.inputs["contract_period_months"] = months
    if ratio is not None:
        model.inputs["gft_ratio"] = ratio
    if sites is not None:
        model.inputs["site_count"] = sites
    if per_site is not None:
        model.inputs["site_team_per_site"] = per_site
    programme = derive(TECHNOPOLE, model)
    return programme, build_spread(programme, model), model


# -- the stated rule, on the resource it is about ----------------------------------------------
def test_the_default_ratio_is_six_and_belongs_to_the_gft():
    assert DEFAULT_INPUTS["gft_ratio"] == 6.0
    assert default_model().value("gft_ratio") == 6.0


def test_the_spread_reads_the_ratio_from_the_model():
    _, spread, _ = _spread_for(months=20)
    assert spread.gft_ratio == 6.0


def test_the_ratio_is_an_ordinary_input_not_a_hardcode():
    """Edit it per tender and the GFT count follows — the whole point of it being a model value."""
    programme, at_six, _ = _spread_for(months=8)
    _, at_three, _ = _spread_for(months=8, ratio=3.0)

    assert programme.rigs_exact == pytest.approx(3.909, abs=0.01)
    assert at_six.gfts_required == 1
    assert at_three.gfts_required == 2


def test_the_halving_the_rule_causes_is_pinned_on_the_gft():
    """3.909 rigs: two GFTs at 3:1, ONE at the stated 6:1 — the GFT cost halves with the ratio."""
    _, at_six, _ = _spread_for(months=8)
    _, at_three, _ = _spread_for(months=8, ratio=3.0)

    assert at_six.gfts_required == 1 and at_three.gfts_required == 2
    assert at_six.gft_cost_programme == pytest.approx(at_three.gft_cost_programme / 2)


def test_seven_exact_rigs_still_buy_a_second_gft():
    """The mechanism survives the split: past 6 rigs, ceil buys the second one."""
    model = default_model()
    model.inputs["contract_period_months"] = 4.4          # push rigs_exact past 6
    programme = derive(TECHNOPOLE, model)
    assert programme.rigs_exact > 6.0
    assert build_spread(programme, model).gfts_required == 2


def test_a_zero_or_missing_ratio_falls_back_to_the_stated_rule():
    model = default_model()
    model.inputs["gft_ratio"] = 0.0                       # nonsense in, rule out
    programme = derive(TECHNOPOLE, model)
    assert build_spread(programme, model).gft_ratio == 6.0


# -- what the old shape could not say ----------------------------------------------------------
def test_the_site_team_does_not_move_when_rigs_go_one_to_twelve():
    """The ruling, stated as arithmetic. The rig count is pushed from under 1 to over 12 by
    shortening the contract; the site team is the same number at both ends and everywhere between,
    while the GFT count climbs. Under the old conflation this assertion was false by construction."""
    counts = []
    for months in (24, 20, 16, 12, 8, 6, 4.4, 3, 2.2):
        programme, spread, _ = _spread_for(months=months)
        counts.append((programme.rigs_exact, spread.site_teams, spread.gfts_required))

    rigs = [c[0] for c in counts]
    assert rigs[0] < 2 and rigs[-1] > 12, "the sweep really does cross the whole range"
    assert {c[1] for c in counts} == {1.0}, "one site team, at every rig count"
    assert [c[2] for c in counts] == [math.ceil(r / 6.0) for r in rigs]
    assert counts[-1][2] > counts[0][2], "the GFT count DOES climb — the rule still bites"


def test_the_site_team_follows_sites_and_the_coefficient_instead():
    """What it does move with. Two sites is two teams; a half coefficient is half a team, NOT
    rounded up — half a team is a team shared with another contract, and rounding would invent a
    second one nobody employs."""
    _, one_site, _ = _spread_for(months=20)
    _, two_sites, _ = _spread_for(months=20, sites=2.0)
    _, shared, _ = _spread_for(months=20, per_site=0.5)

    assert one_site.site_teams == 1.0
    assert two_sites.site_teams == 2.0
    assert shared.site_teams == 0.5, "a coefficient, not a headcount"
    assert two_sites.site_team_cost_programme == pytest.approx(
        one_site.site_team_cost_programme * 2)


def test_both_resources_reach_the_buildup_as_their_own_rows():
    programme, spread, model = _spread_for(months=8)
    rows = build(programme, model, spread).index()

    team, gft = rows["site_team"], rows["gft"]
    assert team.quantity == pytest.approx(spread.site_teams
                                          * programme.work_days_available_per_rig)
    assert gft.quantity == pytest.approx(spread.gfts_required
                                         * programme.work_days_available_per_rig)
    assert "does not move with the rig count" in team.derivation
    assert "GFT" in gft.label


def test_the_gft_row_says_so_loudly_when_it_has_no_rate():
    """The GFT ships at rate 0 — it is your cost, not a market figure. A resource that is REQUIRED
    and prices at nothing must say so rather than quietly contributing zero."""
    programme, spread, model = _spread_for(months=8)
    buildup = build(programme, model, spread)

    assert spread.cost_per_gft_day == 0.0, "the seeded default: not guessed"
    row = buildup.index()["gft"]
    assert "no rate" in row.problem and "prices at nothing" in row.problem
    assert any("GFT" in p for p in buildup.problems)


# -- the question is answered on the register, not asked -----------------------------------------
def test_the_register_resolves_the_gft_question_instead_of_asking_it():
    model = default_model()
    programme = derive(TECHNOPOLE, model)
    spread = build_spread(programme, model)
    register = assum.build(programme, model, build(programme, model, spread), spread)
    rows = {r.key: r for r in register.rows}

    ratio = rows["supervision_ratio"]
    assert "RESOLVED" in ratio.basis
    assert "NOT the same resource" in ratio.basis
    assert "6 rigs per 1 GFT" in ratio.basis
    assert "?" not in ratio.basis, "it is a statement now, not an open question"
    assert not ratio.derived, "still a judgement a human can verdict"

    assert rows["site_teams"].derived and "does not move" in rows["site_teams"].basis
    assert rows["gfts"].derived
    assert rows["site_team_per_site"].value == "1"
    assert rows["site_count"].value == "1"
    assert "not entered" in rows["gft_rate"].value


# -- the retired input cannot bring the old behaviour back ----------------------------------------
def test_the_retired_input_changes_nothing_and_is_reported():
    """A model saved before the split still carries `site_team_supervises_rigs`. It must be inert —
    not read by anything — and it must be SAID, because a knob that silently stopped working is
    worse than one that was removed."""
    assert "site_team_supervises_rigs" not in DEFAULT_INPUTS
    assert "site_team_supervises_rigs" in RETIRED_INPUTS

    model = default_model()
    model.inputs["contract_period_months"] = 8
    programme = derive(TECHNOPOLE, model)
    clean = build_spread(programme, model)

    stale = default_model()
    stale.inputs["contract_period_months"] = 8
    stale.inputs["site_team_supervises_rigs"] = 3.0       # the old halving value
    stale_spread = build_spread(derive(TECHNOPOLE, stale), stale)

    assert stale_spread.site_teams == clean.site_teams
    assert stale_spread.gfts_required == clean.gfts_required
    assert stale_spread.site_team_cost_programme == clean.site_team_cost_programme
    assert stale.usable(), "inert, so it does not stop the model pricing"

    register = assum.build(derive(TECHNOPOLE, stale), stale,
                           build(derive(TECHNOPOLE, stale), stale, stale_spread), stale_spread)
    row = next(r for r in register.rows if r.key == "retired_site_team_supervises_rigs")
    assert "not read" in row.value and "gft_ratio" in row.basis
    assert row.outstanding, "blank until a person has looked at it"


def test_the_workbook_prints_both_counts_from_the_model():
    """The one-way spine: the sheet shows the model's values, never its own."""
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
    printed = {r[0].value: r[1].value for r in inputs.iter_rows(min_col=2, max_col=3)}
    assert printed["One GFT supervises"] == 6.0
    assert printed["Number of sites"] == 1.0
    assert printed["Site teams per site"] == 1.0
    assert "One site team supervises" not in printed, "the retired input is not printed as live"

    rates = book["03 Resource Rates"]
    labels = [row[0].value for row in rates.iter_rows(min_col=2, max_col=2)]
    assert "B2 — COST PER GFT-DAY" in labels
    assert "Site teams carried" in labels and "GFTs required" in labels
    assert "GFT cost — full programme" in labels
