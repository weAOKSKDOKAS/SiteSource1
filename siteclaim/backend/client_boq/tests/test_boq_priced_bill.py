"""The priced bill: reading the client's quantities, and turning a cost basis into a rate.

Two rules these defend.

**A mapping is proposed, never assumed.** The engine needs four numbers out of a bill whose item
numbering differs on every contract, so it reads the descriptions, proposes, and shows the words that
made it think so. An item it cannot place comes back **named** — because General Preambles ¶6 turns a
blank rate into work done for nothing for the life of the contract, and a silently dropped item is the
one way this product could actually cost somebody money.

**The last decision is the estimator's.** The rounded rate is a proposal; ``rate_to_submit`` is a
separate value they may overwrite with anything, and the amount follows whatever is in it.
"""

from __future__ import annotations

import pytest

from client_boq.boq.buildup import build
from client_boq.boq.costing import (
    ROLE_HARD,
    ROLE_HOLES,
    ROLE_ROCK,
    ROLE_SOIL,
    price,
    propose_pricing,
    propose_quantities,
)
from client_boq.boq.model import default_model
from client_boq.boq.programme import derive
from client_boq.models import BillItem, ClientBill

DRILLING = "Drilling H or N size, vertically downwards, "


def _bill(*items: BillItem) -> ClientBill:
    return ClientBill(set_id="technopole-gi", rev=0, items=list(items))


def _item(ref, description, qty, unit, **kwargs):
    return BillItem(bill_no=ref.split(".")[0], full_ref=ref, description=description,
                    qty=qty, unit=unit, **kwargs)


@pytest.fixture
def bill():
    """A faithful miniature of Bills 2 and 4, in the reference contract's own wording."""
    return _bill(
        _item("2.1", "Establishment of rigs", None, "item", lump=True),
        _item("2.2", "Moving rigs", 91, "nr"),
        _item("2.3", "Standing time for rigs", 455, "h"),
        _item("2.4", DRILLING + "material other than rock, boulder or artificial hard material",
              2300, "m"),
        _item("2.5", DRILLING + "rock", 600, "m"),
        _item("2.6", DRILLING + "artificial hard material or boulder", 100, "m"),
        _item("2.11", "Mazier sample taken from drillhole", 1138, "nr"),
        _item("2.15", "H or N size rock core", 160, "nr"),
        _item("4.1", "Moisture content determination test", 273, "nr"),
        _item("4.10", "Single stage UU triaxial, 76mm specimen", 136, "nr"),
        _item("9.1", "Pay for Safety item", 1, "item", pre_priced=True,
              client_rate=429810.0, client_amount=429810.0),
    )


@pytest.fixture
def model():
    return default_model()


@pytest.fixture
def priced(bill, model):
    quantities = propose_quantities(bill).quantities()
    programme = derive(quantities, model)
    return price(bill, model, programme, build(programme, model))


class TestReadingTheQuantitiesOutOfTheBill:
    def test_the_four_quantities_are_found(self, bill):
        mapping = propose_quantities(bill)
        assert mapping.matches[ROLE_HOLES].value == 91
        assert mapping.matches[ROLE_SOIL].value == 2300
        assert mapping.matches[ROLE_ROCK].value == 600
        assert mapping.matches[ROLE_HARD].value == 100

    def test_hard_material_is_not_swallowed_by_the_rock_pattern(self, bill):
        # "artificial hard material or boulder" is matched first — the rock item's own wording would
        # otherwise claim it, and the two would silently price the same.
        mapping = propose_quantities(bill)
        assert mapping.matches[ROLE_HARD].full_ref == "2.6"
        assert mapping.matches[ROLE_ROCK].full_ref == "2.5"

    def test_soil_is_not_claimed_by_the_rock_pattern_either(self, bill):
        # The soil item's own description contains the word "rock".
        assert propose_quantities(bill).matches[ROLE_SOIL].full_ref == "2.4"

    def test_every_match_says_what_made_it_think_so(self, bill):
        assert all(m.why for m in propose_quantities(bill).matches.values())

    def test_nothing_arrives_confirmed(self, bill):
        assert all(not m.confirmed for m in propose_quantities(bill).matches.values())

    def test_a_role_with_no_candidate_is_named(self):
        thin = _bill(_item("2.4", DRILLING + "material other than rock", 2300, "m"))
        mapping = propose_quantities(thin)
        assert set(mapping.unmatched_roles) == {ROLE_HOLES, ROLE_ROCK, ROLE_HARD}
        assert any("number of drillholes" in p for p in mapping.problems())

    def test_the_quantities_feed_the_production_model(self, bill):
        quantities = propose_quantities(bill).quantities()
        assert quantities.total_m == 3000.0 and quantities.holes == 91

    def test_a_heading_with_no_quantity_is_summed_from_its_children(self):
        """The real bill's shape, and it is not an edge case.

        ND/2025/04 item 2.2 reads "Moving rigs" and carries no quantity at all; the numbers are on
        2.2a "in Class A of site" (80) and 2.2b "in Class B of site" (11), whose own descriptions
        never mention a rig. Matching only leaves finds nothing, and matching the parent finds an
        empty row — so 91 holes went missing entirely until this summed them.
        """
        real = _bill(
            BillItem(bill_no="2", full_ref="2.2", item_ref="2.2", description="Moving rigs",
                     is_parent=True, heading_path=["SECTION 2 - GROUND INVESTIGATION", "Rigs"]),
            BillItem(bill_no="2", full_ref="2.2a", item_ref="2.2", sub_ref="a",
                     description="in Class A of site", qty=80, unit="nr",
                     heading_path=["SECTION 2 - GROUND INVESTIGATION", "Rigs"]),
            BillItem(bill_no="2", full_ref="2.2b", item_ref="2.2", sub_ref="b",
                     description="in Class B of site", qty=11, unit="nr",
                     heading_path=["SECTION 2 - GROUND INVESTIGATION", "Rigs"]),
            # The trap this walked into: a plain string prefix of "2.2" also matches 2.20 and 2.21,
            # which on the real bill turned 91 holes into 528 with nothing looking wrong.
            _item("2.20", "Extra over for excavation in rock", 17, "nr"),
            _item("2.21", "Extra over for artificial hard material", 17, "nr"),
            _item("2.4", DRILLING + "material other than rock", 2300, "m"),
        )
        match = propose_quantities(real).matches[ROLE_HOLES]
        assert match.value == 91, "80 + 11, and nothing from 2.20 or 2.21"
        assert match.contributing == ["2.2a", "2.2b"]

    def test_that_sum_shows_its_working(self):
        real = _bill(
            BillItem(bill_no="2", full_ref="2.2", item_ref="2.2", description="Moving rigs",
                     is_parent=True),
            BillItem(bill_no="2", full_ref="2.2a", item_ref="2.2", sub_ref="a",
                     description="in Class A of site", qty=80, unit="nr"),
            BillItem(bill_no="2", full_ref="2.2b", item_ref="2.2", sub_ref="b",
                     description="in Class B of site", qty=11, unit="nr"),
        )
        why = propose_quantities(real).matches[ROLE_HOLES].why
        # "91" is a number somebody has to be able to check, so the arithmetic is on screen.
        assert "2.2a (80)" in why and "2.2b (11)" in why and "= 91" in why

    def test_a_heading_whose_children_are_all_empty_is_not_claimed(self):
        empty = _bill(
            BillItem(bill_no="2", full_ref="2.2", item_ref="2.2", description="Moving rigs",
                     is_parent=True),
            BillItem(bill_no="2", full_ref="2.2a", item_ref="2.2", sub_ref="a",
                     description="in Class A of site", unit="nr"),
        )
        assert ROLE_HOLES in propose_quantities(empty).unmatched_roles


class TestProposingACostBasis:
    def test_each_kind_of_item_finds_its_basis(self, bill, model):
        found = {m.full_ref: m.basis_key or m.lab_key for m in propose_pricing(bill, model)}
        assert found["2.4"] == "soil_drilling"
        assert found["2.5"] == "rock_drilling"
        assert found["2.2"] == "setup_move"
        assert found["2.3"] == "standing_time"
        assert found["2.1"] == "mobilise"
        assert found["2.11"] == "soil_tubes"
        assert found["4.1"] == "lab_moisture"
        assert found["4.10"] == "lab_uu"

    def test_obstruction_drilling_is_priced_at_the_rock_rate(self, bill, model):
        hard = next(m for m in propose_pricing(bill, model) if m.full_ref == "2.6")
        assert hard.basis_key == "rock_drilling"
        assert "rock rate" in hard.why

    def test_the_clients_own_priced_item_is_left_alone(self, bill, model):
        client = next(m for m in propose_pricing(bill, model) if m.full_ref == "9.1")
        assert not client.mapped and "not yours to touch" in client.why

    def test_an_item_nothing_recognises_is_named_with_the_consequence(self, model):
        odd = _bill(_item("3.9", "Chemical grouting of an abandoned adit", 5, "m3"))
        mapping = propose_pricing(odd, model)[0]
        assert not mapping.mapped
        assert "General Preambles" in mapping.why and "for nothing" in mapping.why

    def test_nothing_arrives_confirmed(self, bill, model):
        assert all(not m.confirmed for m in propose_pricing(bill, model))


class TestTheRateLadder:
    def test_a_rate_is_the_cost_basis_times_the_selling_factor(self, priced):
        row = priced.index()["2.4"]
        assert row.rate_raw == pytest.approx(row.cost_basis * row.selling_factor)
        assert row.selling_factor == pytest.approx(1.15 * 1.05 / 0.9)

    def test_the_rounding_ladder_is_the_templates(self, model):
        assert model.round_rate(1234.56) == 1200      # ≥1,000 → nearest 100
        assert model.round_rate(456.7) == 460         # ≥100 → nearest 10
        assert model.round_rate(65.4) == 65           # else whole dollars

    def test_the_amount_follows_the_rate_actually_submitted(self, priced):
        row = priced.index()["2.4"]
        assert row.amount == pytest.approx(2300 * row.rate_to_submit)

    def test_the_estimator_may_overwrite_the_proposal(self, bill, model):
        quantities = propose_quantities(bill).quantities()
        programme = derive(quantities, model)
        result = price(bill, model, programme, build(programme, model),
                       submitted={"2.4": 999.0})
        row = result.index()["2.4"]
        assert row.rate_to_submit == 999.0 and row.overridden
        assert row.amount == pytest.approx(2300 * 999.0)
        assert row.rate_rounded != 999.0, "the proposal stays visible beside it"

    def test_a_lump_items_amount_is_its_rate(self, priced):
        row = priced.index()["2.1"]
        assert row.lump and row.amount == pytest.approx(row.rate_to_submit)

    def test_the_clients_rate_passes_through_untouched(self, priced):
        row = priced.index()["9.1"]
        assert row.source == "client" and row.rate_to_submit == 429810.0
        assert row.amount == 429810.0

    def test_the_total_is_the_sum_of_the_amounts(self, priced):
        assert priced.total == pytest.approx(sum(r.amount or 0.0 for r in priced.rows))


class TestNothingDisappearsQuietly:
    def test_an_unmapped_item_is_reported_with_what_silence_costs(self, model):
        # Stand-ins off: this is about what the model refuses to DERIVE. With them on the line is
        # reported provisional instead of red, which is a different question tested elsewhere.
        model.use_placeholders = False
        odd = _bill(_item("3.9", "Chemical grouting", 5, "m3"),
                    _item("2.2", "Moving rigs", 91, "nr"),
                    _item("2.4", DRILLING + "material other than rock", 2300, "m"))
        quantities = propose_quantities(odd).quantities()
        programme = derive(quantities, model)
        result = price(odd, model, programme, build(programme, model))
        row = result.index()["3.9"]
        assert row.source == "unpriced" and row.rate_to_submit is None
        assert "for the life of the contract" in row.note
        assert "3.9" in result.unpriced
        assert any("no cost basis" in p for p in result.problems)

    def test_one_unpriceable_item_does_not_stop_the_rest(self, model):
        odd = _bill(_item("3.9", "Chemical grouting", 5, "m3"),
                    _item("2.2", "Moving rigs", 91, "nr"),
                    _item("2.4", DRILLING + "material other than rock", 2300, "m"))
        quantities = propose_quantities(odd).quantities()
        programme = derive(quantities, model)
        result = price(odd, model, programme, build(programme, model))
        assert result.index()["2.4"].rate_to_submit is not None
