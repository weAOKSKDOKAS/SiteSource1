"""Getting the spread there: three costs, three destinations, and one machine that cannot reach.

THE CASE THE BILL CANNOT SEE. PS 7.01B reads Class A as access "by road traffic **or** by manual
labour", so ONE bill item — one rate — pays for a rig the lorry delivered and for a rig six people
carried up a hillside. The class split the bill does draw (A against B) is about platforms, not
about how the rig got there. So an estimator who prices manhandling has nowhere obvious to put it,
and General Preambles ¶6 makes "nowhere" expensive: an item with no rate "shall be deemed to be
covered by the other rates".

So a group now records HOW the spread reaches it, separately from the class the bill pays against,
and the three costs go three different places:

* a **platform** stays Class B's alone (SMM S02 ¶2.08(h) — access scaffolding is in the moving-rigs
  item coverage), because a Class A move must not carry a platform it does not need;
* **portage** goes to whatever class the group is, INCLUDING Class A (¶2.03 measures moves per
  hole, ¶2.06 splits them by class, and carrying a rig to a hole is moving it) — this is the only
  place the road-or-manual difference can be priced;
* a **lift** goes nowhere, at any class, and that is the point. ¶2.08(h) covers scaffolding and a
  helicopter is not scaffolding; Class C is in the specification and not in the bill. Absorbing it
  would be this engine pricing an item the bill does not contain.

AND THE CONSTRAINT THAT IS NOT ABOUT MONEY AT ALL. A rig broken into man-carriable loads is a
smaller rig. If the schedule says 60 m and it reaches 30, no production rate and no rig count fixes
that — it is the wrong machine, and the check says so in those words. The limit is never defaulted:
a firm's fleet is not something this engine can know, so zero means unset and the check says it is
not checking rather than returning the empty list that reads as "fine".
"""

from __future__ import annotations

import pytest

from client_boq.boq.buildup import AccessCost, build, build_spread
from client_boq.boq.groups import (
    GroupPlan, HoleGroup, HoleShape, TRANSPORT_AIR, TRANSPORT_MANUAL, TRANSPORT_VEHICLE)
from client_boq.boq.model import default_model
from client_boq.boq.programme import Quantities, derive

COUNTS = {"A": 80.0, "B": 11.0}
ACTIVE = {"setup_move_b"}


@pytest.fixture
def model():
    return default_model()


@pytest.fixture
def programme(model):
    return derive(Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0), model)


@pytest.fixture
def spread(programme, model):
    return build_spread(programme, model)


def _rows(programme, model, spread, **kw):
    return {r.key: r for r in build(programme, model, spread, active_keys=ACTIVE,
                                    class_counts=COUNTS, **kw).rows}


class TestPortageReachesTheClassAMoveRate:
    def test_it_lands_on_class_a_which_a_platform_never_could(self, programme, model, spread):
        """The whole point. Class A is where the bill puts a hole reached on foot, so Class A is
        where the cost of reaching it on foot has to be priced."""
        bare = _rows(programme, model, spread, access_cost_by_class={})
        loaded = _rows(programme, model, spread,
                       access_cost_by_class={"A": AccessCost(portage=96_000.0)})
        assert loaded["setup_move_a"].total_cost == pytest.approx(
            bare["setup_move_a"].total_cost + 96_000.0)
        assert loaded["setup_move_b"].total_cost == pytest.approx(bare["setup_move_b"].total_cost)

    def test_the_rate_says_which_clause_put_it_there(self, programme, model, spread):
        row = _rows(programme, model, spread,
                    access_cost_by_class={"A": AccessCost(portage=96_000.0)})["setup_move_a"]
        assert "2.03" in row.derivation and "2.06" in row.derivation
        assert "carry the spread in" in row.derivation

    def test_a_platform_and_a_portage_on_one_class_are_both_named(self, programme, model, spread):
        """A merged number would price right and explain nothing, and the explanation is what
        somebody has to defend."""
        row = _rows(programme, model, spread, access_cost_by_class={
            "B": AccessCost(platform=210_000.0, portage=40_000.0)})["setup_move_b"]
        assert "210,000.00 platform" in row.derivation
        assert "40,000.00 to carry the spread" in row.derivation
        assert "2.08(h)" in row.derivation


class TestTheOldSingleFigureStillMeansWhatItMeant:
    def test_platform_cost_b_is_read_as_a_class_b_platform(self, programme, model, spread):
        old = _rows(programme, model, spread, platform_cost_b=210_000.0)
        new = _rows(programme, model, spread,
                    access_cost_by_class={"B": AccessCost(platform=210_000.0)})
        assert old["setup_move_b"].total_cost == pytest.approx(new["setup_move_b"].total_cost)
        assert old["setup_move_a"].total_cost == pytest.approx(new["setup_move_a"].total_cost)


class TestALiftIsNotAbsorbedAnywhere:
    def test_the_buildup_has_no_channel_for_it_at_all(self):
        """Structural, like a proposal with no status field: if the arithmetic cannot carry it,
        no future wiring can quietly start carrying it."""
        assert set(AccessCost.model_fields) == {"platform", "portage"}

    def test_the_flag_names_the_four_places_it_can_go(self):
        from client_boq.boq import checks

        flags = checks.air_lift_has_no_item(180_000.0, holes=3)
        assert len(flags) == 1 and flags[0].kind == "air_lift_unbilled"
        message = flags[0].message
        assert "180,000.00" in message and "3 hole(s)" in message
        for route in ("query", "load", "spread", "accept"):
            assert route in message.lower()
        assert "Class C" in message

    def test_nothing_typed_is_no_flag(self):
        from client_boq.boq import checks

        assert checks.air_lift_has_no_item(0.0) == []
        assert checks.portage_cost_unconsumed(0.0) == []


class TestTheRigMustReachTheBottom:
    def _plan(self, transport: str, depths: list[float]) -> GroupPlan:
        return GroupPlan(groups=[HoleGroup(
            label="hillside", transport=transport,
            stations=[f"BH{i}" for i in range(len(depths))],
            shapes=[HoleShape(station=f"BH{i}", soil_m=d, rock_m=0.0)
                    for i, d in enumerate(depths)])])

    def test_a_hole_deeper_than_the_rig_reaches_is_named(self):
        problems = self._plan(TRANSPORT_MANUAL, [12.0, 45.0, 61.0]).reach(30.0)
        assert len(problems) == 1
        assert "2 hole(s) go deeper than the 30 m" in problems[0]
        assert "deepest 61 m" in problems[0]
        assert "BH1, BH2" in problems[0]

    def test_it_says_wrong_machine_not_slower(self):
        """The sentence is the point — every other constraint here is about duration, and an
        estimator who reads this as 'allow more days' has mis-priced the hole."""
        problems = self._plan(TRANSPORT_AIR, [80.0]).reach(30.0)
        assert "wrong machine for those holes, not a slower one" in problems[0]

    def test_a_driven_group_is_not_checked_at_all(self):
        assert self._plan(TRANSPORT_VEHICLE, [80.0]).reach(30.0) == []

    def test_an_undecided_group_is_not_checked_either(self):
        assert self._plan("", [80.0]).reach(30.0) == []

    def test_within_reach_is_silence(self):
        assert self._plan(TRANSPORT_MANUAL, [12.0, 28.0]).reach(30.0) == []


class TestAnUnsetLimitSaysSoRatherThanPassing:
    def test_carried_groups_with_no_limit_report_that_nothing_was_checked(self):
        """An empty list here would be indistinguishable from 'checked, and every hole is fine' —
        the failure this codebase calls absence-reads-as-health."""
        plan = GroupPlan(groups=[HoleGroup(label="hill", transport=TRANSPORT_MANUAL,
                                           stations=["BH1"],
                                           shapes=[HoleShape(station="BH1", soil_m=90.0)])])
        problems = plan.reach(0.0)
        assert len(problems) == 1
        assert "no depth limit is set" in problems[0]
        assert "nothing has been checked" in problems[0]
        assert "Deepest a carried-in rig will drill" in problems[0]

    def test_no_carried_groups_and_no_limit_is_genuine_silence(self):
        """Nothing to check is not the same as not checking, and it must not nag."""
        plan = GroupPlan(groups=[HoleGroup(label="road", transport=TRANSPORT_VEHICLE,
                                           stations=["BH1"])])
        assert plan.reach(0.0) == []

    def test_the_default_is_unset_and_deliberately_not_a_plausible_number(self):
        assert default_model().value("portable_rig_max_depth_m", -1.0) == 0.0


class TestATypoIsRefusedRatherThanStored:
    """`transport` decides where three costs land and whether the depth limit is checked. A value
    this engine does not know, stored quietly, would read on every screen as a judgement."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
        from api import app
        return TestClient(app)

    def test_an_unknown_way_of_getting_there_is_a_422(self, client):
        reply = client.post("/client-boq/site/group", json={
            "set_id": "technopole-gi", "group_id": "g1",
            "group": {"label": "hill", "stations": ["BH1"], "transport": "teleport"}})
        assert reply.status_code == 422
        detail = reply.json()["detail"]
        assert "teleport" in detail and "Nothing was written" in detail
        for known in ("vehicle", "manual", "air"):
            assert known in detail

    def test_blank_is_allowed_because_nobody_has_decided_yet(self, client):
        assert client.post("/client-boq/site/group", json={
            "set_id": "technopole-gi", "group_id": "g2",
            "group": {"label": "road", "stations": ["BH2"], "transport": ""},
        }).status_code == 200

    def test_a_known_one_round_trips_with_its_costs(self, client):
        assert client.post("/client-boq/site/group", json={
            "set_id": "technopole-gi", "group_id": "g3",
            "group": {"label": "hill", "stations": ["BH3"], "transport": "manual",
                      "access_labour_cost": 96_000.0, "access_air_cost": 12_000.0},
        }).status_code == 200
        groups = client.get("/client-boq/site/technopole-gi/groups").json()["groups"]
        row = next(g for g in groups if g["label"] == "hill")
        assert row["transport"] == "manual"
        assert row["access_labour_cost"] == pytest.approx(96_000.0)
        assert row["access_air_cost"] == pytest.approx(12_000.0)
