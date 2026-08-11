"""Is every cost recovered exactly once? The join between the build-up and the priced bill.

THE DEFECT THIS CLOSES, probed on the shipped engine before any of it was written
(``DEMO_MODE=true``, ``model.default_model()``, a four-item bill carrying the four role quantities):

    build-up direct cost total : 11,896,017.70
    priced bill AMOUNT total   :  8,857,900.00
    priced.unpriced            : []
    priced.placeholders        : []

**HK$3,038,117.70 of cost reached no rate, and the engine reported the bill fully priced.** Eight of
eleven bases had no bill item claiming them at all — the site team, standing time, mobilisation,
setting out, sample tubes, core boxes, backfill grout — HK$5,264,157 between them. `PricedBQ` has no
way to notice: it iterates the BILL and asks each item for a basis, so a basis no item asks for is
never visited. `unbilled.py` exists to catch exactly this and cannot see it, because its sweep is a
hand-typed list that is never seeded from the build-up.

And the other direction, from the same probe: adding a second "material other than rock" item drawn
from another bill added **HK$720,000** to the tender for cost already fully recovered, because the
soil basis's divisor came from the FIRST matching item alone while both items priced off it.

THE LAW, and it is one line. ``price()`` computes ``row.direct_cost = item.qty * cost_per_unit`` and
``build()`` computes ``cost_per_unit = total_cost / divisor``, so:

    a basis is recovered exactly once when the quantities of the items claiming it sum to its divisor

Which is why the count of claimants is NOT the test — two items sharing a basis is normal and right
(rock and artificial hard material drill at one cost per metre, so the rock basis is divided by rock
PLUS hard metres and claimed by both). The SUM has to hold; the count never mattered.
"""

from __future__ import annotations

import pytest

from client_boq.boq import buildup as bb
from client_boq.boq import conservation as cons
from client_boq.boq import costing as bc
from client_boq.boq import model as bm
from client_boq.boq import programme as bp
from client_boq.models import BillItem, ClientBill


def _item(ref, description, unit, qty, *, bill_no="2", row=1):
    return BillItem(bill_no=bill_no, full_ref=ref, item_ref=ref, description=description,
                    unit=unit, qty=qty, row=row)


# The four items the quantity mapping recognises, so a real programme and real costs flow.
ROLE_ITEMS = [
    _item("2.2", "Moving rigs between investigation stations", "nr", 91.0, row=1),
    _item("2.4", "Rotary drilling, vertically downwards, material other than rock", "m", 1200.0, row=2),
    _item("2.5", "Rotary drilling, vertically downwards, rock", "m", 1000.0, row=3),
    _item("2.6", "Drilling through artificial hard material or boulder", "m", 120.0, row=4),
]


def _run(items):
    """The engine's own path, as ``router._costing`` runs it, plus the conservation join."""
    model = bm.default_model()
    bill = ClientBill(set_id="conservation-test", items=list(items))
    mapping = bc.propose_quantities(bill)
    item_mappings = bc.propose_pricing(bill, model)
    programme = bp.derive(mapping.quantities(), model)
    buildup = bb.build(programme, model, bb.build_spread(programme, model))
    priced = bc.price(bill, model, programme, buildup, item_mappings, submitted={})
    return bill, buildup, item_mappings, priced, cons.check(bill, buildup, item_mappings)


class TestCostThatReachesNoRate:
    def test_a_basis_no_item_claims_is_named_with_its_money(self):
        _bill, _bu, _ims, priced, report = _run(ROLE_ITEMS)

        assert not report.clean(), "the shipped engine does not conserve on this bill"
        assert report.unrecovered(), "bases with no claiming item must be named"
        # The engine's own report said nothing was wrong — that is the defect.
        assert priced.unpriced == [] and priced.placeholders == []

        by_key = {b.key: b for b in report.unrecovered()}
        assert "site_team" in by_key and "standing_time" in by_key
        assert by_key["site_team"].direct_cost > 0
        assert by_key["site_team"].recovered == 0.0

    def test_the_unrecovered_sentence_quotes_the_clause_that_makes_it_expensive(self):
        """Cost that reaches no rate is not saved. Under GP ¶6 it is given away for the life of a
        remeasured contract, and the message has to say so or the number reads as slack."""
        _b, _bu, _i, _p, report = _run(ROLE_ITEMS)
        worst = report.problems()[0]
        assert "NO bill item is priced from it" in worst
        assert "General Preambles ¶6" in worst
        assert "submits the work for nothing" in worst

    def test_the_headline_states_the_gap_against_the_whole(self):
        _b, _bu, _i, _p, report = _run(ROLE_ITEMS)
        assert "reaches no rate at all" in report.headline()
        assert f"{report.difference():,.2f}" in report.headline()

    def test_the_totals_are_the_arithmetic_they_claim_to_be(self):
        _b, _bu, _i, _p, report = _run(ROLE_ITEMS)
        assert report.direct_cost == pytest.approx(sum(b.direct_cost for b in report.bases), abs=0.01)
        assert report.recovered == pytest.approx(sum(b.recovered for b in report.bases), abs=0.01)
        assert report.difference() == pytest.approx(report.direct_cost - report.recovered, abs=0.01)


class TestCostRecoveredTwice:
    def test_a_second_item_on_a_basis_whose_divisor_excludes_it_is_caught(self):
        """The soil basis is divided by the soil metres of ONE item. A second item priced from it
        recovers the same cost again — the tender goes up for money nobody spends."""
        extra = _item("3.4", "Environmental borehole drilling, material other than rock",
                      "m", 600.0, bill_no="3", row=5)
        _b, _bu, _i, _p, report = _run([*ROLE_ITEMS, extra])

        over = [b for b in report.miscounted() if b.key == "soil_drilling"]
        assert over, "a basis claimed beyond its divisor must be reported"
        basis = over[0]
        assert basis.claimed_by == ["2.4", "3.4"]
        assert basis.claimed_qty == pytest.approx(1800.0)
        assert basis.divisor == pytest.approx(1200.0)
        assert basis.difference() < 0, "negative difference means over-recovered"
        assert "recovered TWICE" in basis.problem()

    def test_the_tender_total_rises_for_the_same_underlying_cost(self):
        """The proof the over-recovery is real money and not a bookkeeping artefact."""
        extra = _item("3.4", "Environmental borehole drilling, material other than rock",
                      "m", 600.0, bill_no="3", row=5)
        _b1, bu1, _i1, priced_one, _r1 = _run(ROLE_ITEMS)
        _b2, bu2, _i2, priced_two, _r2 = _run([*ROLE_ITEMS, extra])

        assert bu1.total_direct_cost == pytest.approx(bu2.total_direct_cost), (
            "the underlying cost is identical — the same holes, the same metres")
        assert priced_two.total > priced_one.total


class TestWhatIsNotADefect:
    def test_two_items_sharing_a_basis_balance_when_the_divisor_spans_both(self):
        """Rock and artificial hard material drill at one cost per metre, so ¶2.13's rock basis is
        divided by rock PLUS hard metres and claimed by both items. It sums to exactly one recovery,
        and a rule that counted claimants instead of summing quantities would flag it wrongly —
        which is why this test exists beside the over-recovery one above."""
        _b, _bu, item_mappings, _p, report = _run(ROLE_ITEMS)

        claimants = [m.full_ref for m in item_mappings if getattr(m, "basis_key", "") == "rock_drilling"]
        assert sorted(claimants) == ["2.5", "2.6"], "two items really do share this basis"

        rock = next(b for b in report.bases if b.key == "rock_drilling")
        assert rock.claimed_qty == pytest.approx(1120.0)
        assert rock.divisor == pytest.approx(1120.0)
        assert rock.clean(), "the sum holds, so this is correct pricing and must not be flagged"
        assert rock.problem() == ""

    def test_a_balanced_basis_contributes_no_problem(self):
        _b, _bu, _i, _p, report = _run(ROLE_ITEMS)
        balanced = [b.key for b in report.bases if b.claimed_by and b.clean()]
        assert "soil_drilling" in balanced and "setup_move" in balanced
        for key in balanced:
            assert not any(key in problem for problem in report.problems()
                           if "NO bill item" not in problem)


class TestItReportsAndNeverRepairs:
    def test_the_check_changes_nothing_it_is_given(self):
        """Every repair here is a commercial decision wearing arithmetic — which basis belongs in
        which item, or in the spread, or not in this contract at all. Silently pro-rating would
        produce a total that looks right for a reason nobody chose."""
        bill, buildup, item_mappings, priced, _r = _run(ROLE_ITEMS)
        before_rows = [(r.key, r.total_cost, r.cost_per_unit) for r in buildup.rows]
        before_total = priced.total
        before_amounts = [(r.full_ref, r.amount) for r in priced.rows]

        cons.check(bill, buildup, item_mappings)
        cons.check(bill, buildup, item_mappings)

        assert [(r.key, r.total_cost, r.cost_per_unit) for r in buildup.rows] == before_rows
        assert priced.total == before_total
        assert [(r.full_ref, r.amount) for r in priced.rows] == before_amounts

    def test_it_is_pure_and_repeatable(self):
        bill, buildup, item_mappings, _p, first = _run(ROLE_ITEMS)
        second = cons.check(bill, buildup, item_mappings)
        assert first.model_dump() == second.model_dump()


class TestTheEdges:
    def test_an_empty_bill_conserves_nothing_and_says_so_rather_than_passing(self):
        """No items means no basis is claimed — every cost is unrecovered. A check that returned
        'clean' on an empty bill would pass the one case where nothing at all is priced."""
        model = bm.default_model()
        bill = ClientBill(set_id="empty", items=[])
        programme = bp.derive(bc.propose_quantities(bill).quantities(), model)
        buildup = bb.build(programme, model, bb.build_spread(programme, model))
        report = cons.check(bill, buildup, [])
        assert report.recovered == 0.0
        if report.direct_cost:
            assert not report.clean()

    def test_a_basis_that_can_form_no_rate_and_costs_nothing_raises_no_alarm(self):
        """A thin bill (soil metres only) leaves rock, standing time, setting out and the rest with
        a zero divisor AND a zero cost. `buildup` already notes why no rate could form; there is no
        money at stake, so this must stay quiet about them — a check that cried about every empty
        basis would be ignored by the time it saw a real one.

        `unformable` is deliberately only for a basis that carries cost and can still form no rate."""
        model = bm.default_model()
        only_soil = [_item("2.4", "Rotary drilling, vertically downwards, material other than rock",
                           "m", 1200.0, row=1)]
        bill = ClientBill(set_id="thin", items=only_soil)
        programme = bp.derive(bc.propose_quantities(bill).quantities(), model)
        buildup = bb.build(programme, model, bb.build_spread(programme, model))
        report = cons.check(bill, buildup, bc.propose_pricing(bill, model))

        zero_cost_no_rate = [r.key for r in buildup.rows
                             if r.cost_per_unit is None and not r.total_cost]
        assert zero_cost_no_rate, "this bill really does leave bases unable to form a rate"
        assert not set(report.unformable) & set(zero_cost_no_rate), (
            "no cost, no alarm — `buildup` already carries the reason on the row")
        for key in zero_cost_no_rate:
            basis = next(b for b in report.bases if b.key == key)
            assert basis.clean(), "a basis with no cost and no claimant balances at zero"

    def test_but_real_cost_with_no_claimant_is_still_caught_on_that_same_thin_bill(self):
        """The other half: mobilisation costs money on any bill, and nothing here claims it."""
        model = bm.default_model()
        only_soil = [_item("2.4", "Rotary drilling, vertically downwards, material other than rock",
                           "m", 1200.0, row=1)]
        bill = ClientBill(set_id="thin", items=only_soil)
        programme = bp.derive(bc.propose_quantities(bill).quantities(), model)
        buildup = bb.build(programme, model, bb.build_spread(programme, model))
        report = cons.check(bill, buildup, bc.propose_pricing(bill, model))

        mobilise = next(b for b in report.bases if b.key == "mobilise")
        assert mobilise.direct_cost > 0 and mobilise.claimed_by == []
        assert mobilise in report.unrecovered()
        assert "General Preambles ¶6" in mobilise.problem()

    def test_the_tolerance_is_tight_enough_to_catch_real_money(self):
        assert cons.TOLERANCE <= 1.0, (
            "the failures this catches are in the millions; a generous tolerance is how a real "
            "leak learns to hide")


def test_the_costing_payload_carries_the_check_so_no_total_is_shown_without_it():
    """It is computed on `router._costing`, the single path every screen and the workbook go
    through — so a total cannot reach a person without this having been asked."""
    import inspect

    from client_boq import router

    source = inspect.getsource(router._costing)
    assert "boq_conservation.check(" in source
    assert '"conservation"' in source
