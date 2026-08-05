"""Preliminaries: the resources a client bills as their own items, and the rate typed by hand.

The rule these defend: **one number, many lines.**

An estimator does not price a hundred preliminary lines one at a time. They write down what is
standing on site — an office, a car, a store — and each bill line falls out of that list times its
own duration (`docs/client_boq/how_an_estimator_works.md` Stage 6, which splits preliminaries by how
they behave over time rather than by what they are). The app's job is that arithmetic, and saying
out loud which resource and which duration produced each rate.

Measured on the reference ND/2025/04 tender before this existed: **102 of 164 lines had no cost
basis**, 61 of them in Bill 1 — and the app offered no way to supply one. `price()` returned on a
line with no basis *before* it read the submitted rates, so every number anyone entered was
discarded in silence.
"""

from __future__ import annotations

import pytest

from client_boq.boq.buildup import build
from client_boq.boq.costing import price, propose_pricing, propose_quantities
from client_boq.boq.model import default_model
from client_boq.boq.programme import derive
from client_boq.models import BillItem, ClientBill

DRILLING = "Drilling H or N size, vertically downwards, "


def _item(ref, description, qty, unit, **kwargs):
    return BillItem(bill_no=ref.split(".")[0], full_ref=ref, description=description,
                    qty=qty, unit=unit, **kwargs)


def _bill(*items: BillItem) -> ClientBill:
    return ClientBill(set_id="technopole-gi", rev=0, items=list(items))


def _price(bill, model, submitted=None):
    quantities = propose_quantities(bill).quantities()
    programme = derive(quantities, model)
    return price(bill, model, programme, build(programme, model), submitted=submitted)


@pytest.fixture
def bill():
    """Bill 1 lines from the reference tender, in its own wording, plus one drilling item."""
    return _bill(
        # On the real bill this line reads "Taking over" under a parent heading that supplies
        # "Temporary accommodation for the Contractor", and `full_description()` joins the two.
        # Spelled out here because a fixture that drops the heading tests a bill nobody issues.
        _item("1.1", "Taking over of temporary accommodation for the Contractor", None, "item",
              lump=True),
        # Likewise "Servicing" sits under the accommodation heading — it is the monthly running of
        # the same office, which is why one resource prices it and the one-off lines above.
        _item("1.2", "Servicing of temporary accommodation for the Contractor", 28, "mth"),
        _item("1.11", "air-conditioned environmentally-friendly petrol private car", 122, "nr-wk"),
        _item("1.19", "Servicing of core and sample store for the Project Manager", 87, "wk"),
        _item("1.30", "Third party insurance", None, "item", lump=True),
        _item("2.4", DRILLING + "material other than rock, boulder or artificial hard material",
              2300, "m"),
    )


@pytest.fixture
def rated():
    """A model with the estimator's own numbers in it — the one-off act this design asks for."""
    model = default_model()
    index = model.prelim_index()
    index["prelim_office"].rate = 8000.0              # $/month
    index["prelim_vehicle"].rate = 3500.0              # $/week
    index["prelim_store"].rate = 2500.0                # $/week
    return model


class TestTheDoubleCountGuard:
    def test_a_preliminary_never_reaches_a_drilling_day_cost(self):
        """The whole reason preliminaries get their own charge kind.

        ``cost_per_contract_day`` is the SITE TEAM — engineer, foreman, geologist, project manager,
        HK$6,240 on the reference model. If the site office joined it, every metre drilled would
        carry the office inside its rate, and the office would be billed AGAIN on the Bill 1 line
        the client asked for it on. Deriving preliminaries from that number was the first design
        this work tried, and this test is why it is not the design that shipped.
        """
        model = default_model()
        before = (model.cost_per_rig_day(), model.cost_per_contract_day())
        for resource in model.prelims():
            resource.rate = 9999.0
        assert (model.cost_per_rig_day(), model.cost_per_contract_day()) == before

    def test_the_preliminaries_ship_unrated(self):
        """Outputs and all-in rates are the two things nobody else in the market has. A plausible
        invented figure would price a tender without anybody deciding anything."""
        assert default_model().prelims(), "the resources exist"
        assert all(r.rate == 0.0 for r in default_model().prelims())


class TestOneNumberManyLines:
    def test_a_monthly_resource_prices_a_line_billed_in_months(self, bill, rated):
        row = _price(bill, rated).index()["1.2"]
        assert row.source == "prelim"
        assert row.cost_basis == pytest.approx(8000.0)
        assert "8,000" in row.working and "28 mth" in row.working

    def test_a_weekly_resource_converts_onto_a_weekly_line(self, bill, rated):
        """122 ``nr-wk`` of car. The ``nr-`` prefix counts how many are running and the quantity
        already carries that, so the rate is one car for one week — not one car for 122 weeks."""
        row = _price(bill, rated).index()["1.11"]
        assert row.cost_basis == pytest.approx(3500.0)
        assert row.amount == pytest.approx(122 * row.rate_to_submit)

    def test_a_monthly_rate_on_a_weekly_line_converts_by_days(self):
        model = default_model()
        model.prelim_index()["prelim_office"].rate = 4500.0        # $/month
        office = model.prelim_index()["prelim_office"]
        assert model.prelim_rate_for(office, "mth") == pytest.approx(4500.0)
        assert model.prelim_rate_for(office, "wk") == pytest.approx(4500.0 * 7 / 30.4375)
        # A month against cubic metres is a mapping mistake; inventing a conversion would bury it.
        assert model.prelim_rate_for(office, "m3") is None

    def test_a_preliminary_is_a_cost_and_is_marked_up(self, bill, rated):
        row = _price(bill, rated).index()["1.19"]
        assert row.rate_raw == pytest.approx(2500.0 * row.selling_factor)
        assert row.selling_factor > 1.0

    def test_one_edit_moves_every_line_that_uses_it(self, bill, rated):
        """The point of the whole design: the estimator changes one number, not nine."""
        before = _price(bill, rated).index()["1.11"].amount
        rated.prelim_index()["prelim_vehicle"].rate = 7000.0
        assert _price(bill, rated).index()["1.11"].amount == pytest.approx(before * 2)


class TestWhatItRefusesToGuess:
    """What the model will not DERIVE, with the stand-ins switched off.

    Placeholders are a separate question — they fill a line the model could not reach, and they do
    not change what it was willing to work out. Leaving them on here would test the fallback
    instead of the refusal, and the refusal is the part that matters.
    """

    @pytest.fixture(autouse=True)
    def _no_placeholders(self, rated):
        rated.use_placeholders = False

    def test_a_one_off_matched_to_a_monthly_resource_asks_for_a_lump(self, bill, rated):
        """"Taking over" IS the site office — its one-off end, billed as ``item``. A monthly rate
        cannot produce a lump, and guessing a number of months would be inventing the judgement."""
        row = _price(bill, rated).index()["1.1"]
        assert row.source == "unpriced"
        assert row.behaviour == "fixed"
        assert "one-off end of" in row.note
        assert "1.01A" in row.note, "and say why it cannot be front-loaded, while we are here"

    def test_an_unrated_resource_names_itself_rather_than_saying_nothing(self, bill):
        """The difference between 102 unknowns and one number to go and find."""
        bare = default_model()
        bare.use_placeholders = False
        row = _price(bill, bare).index()["1.2"]
        assert row.source == "unpriced"
        assert "Site accommodation" in row.note
        assert "$/month" in row.note

    def test_an_item_nothing_recognises_still_says_what_silence_costs(self, bill, rated):
        row = _price(bill, rated).index()["1.30"]
        assert row.source == "unpriced"
        assert "General Preambles" in row.note


class TestBehaviourComesFromTheUnit:
    def test_the_three_behaviours(self, bill, rated):
        by_ref = _price(bill, rated).index()
        assert by_ref["1.2"].behaviour == "time"        # mth
        assert by_ref["1.11"].behaviour == "time"       # nr-wk
        assert by_ref["1.19"].behaviour == "time"       # wk
        assert by_ref["1.1"].behaviour == "fixed"       # item
        assert by_ref["2.4"].behaviour == "measured"    # m


class TestATypedRate:
    def test_a_rate_typed_on_a_line_with_no_basis_reaches_the_total(self, bill, rated):
        priced = _price(bill, rated, submitted={"1.30": 180000.0})
        row = priced.index()["1.30"]
        assert row.source == "typed"
        assert row.rate_to_submit == 180000.0
        assert row.amount == 180000.0
        assert "1.30" not in priced.unpriced, "it has a rate now; it is not outstanding"

    def test_a_typed_rate_is_not_marked_up_again(self, bill, rated):
        """It is a SELLING rate — the estimator has already made the commercial call. Multiplying
        it by the factor would add margin on top of margin, on the lines nobody re-checks."""
        row = _price(bill, rated, submitted={"1.30": 180000.0}).index()["1.30"]
        assert row.amount == pytest.approx(180000.0)
        assert row.amount != pytest.approx(180000.0 * row.selling_factor)

    def test_lines_left_alone_are_still_reported_outstanding(self, bill, rated):
        """Pricing one line must not quietly clear the rest. With stand-ins on they are reported
        as provisional instead of red — a different word for the same "not done yet"."""
        priced = _price(bill, rated, submitted={"1.30": 180000.0})
        assert "1.1" in priced.placeholders
        assert priced.provisional is True

        rated.use_placeholders = False
        assert "1.1" in _price(bill, rated, submitted={"1.30": 180000.0}).unpriced

    def test_a_built_rate_is_still_marked_up(self, bill, rated):
        """The regression guard: this must not have loosened the normal path."""
        row = _price(bill, rated).index()["2.4"]
        assert row.source == "built"
        assert row.rate_raw == pytest.approx(row.cost_basis * row.selling_factor)


class TestTheProposal:
    def test_a_preliminary_is_matched_by_the_words_and_says_which(self, bill):
        mapping = {m.full_ref: m for m in propose_pricing(bill, default_model())}
        assert mapping["1.11"].prelim_key == "prelim_vehicle"
        assert "Site vehicle" in mapping["1.11"].why
        assert mapping["2.4"].basis_key, "drilling still wins over any preliminary"


class TestPlaceholders:
    """A stand-in so a bill reads end to end while the real numbers are being found.

    The danger this carries is the whole product's danger in miniature: a number nobody chose
    passing as one somebody did. So a placeholder is keyed on the SHAPE of a line rather than its
    wording — it claims nothing about what the line is — it never beats a rate a person typed, its
    money is counted separately, and everything that prints the total says how much of it was
    invented.
    """

    @pytest.fixture
    def unreachable(self):
        return _bill(
            _item("1.30", "Third party insurance", None, "item", lump=True),
            _item("6.4", "Standpipe", 2451, "nr-wk"),
            _item("2.7", "maximum depth not exceeding 3.00m", 142, "m3"),
        )

    def test_every_line_gets_one_and_the_total_is_provisional(self, unreachable):
        priced = _price(unreachable, default_model())
        assert priced.unpriced == []
        assert len(priced.placeholders) == 3
        assert priced.provisional is True
        assert all(r.source == "placeholder" for r in priced.rows)

    def test_the_money_nobody_chose_is_separable(self, unreachable):
        """The number that makes the total safe to look at."""
        priced = _price(unreachable, default_model())
        assert priced.placeholder_total == pytest.approx(priced.total)
        assert priced.placeholder_total > 0

    def test_turning_them_off_shows_the_bill_as_it_stands(self, unreachable):
        model = default_model()
        model.use_placeholders = False
        priced = _price(unreachable, model)
        assert len(priced.unpriced) == 3
        assert priced.placeholders == [] and priced.provisional is False
        assert priced.total == 0.0

    def test_a_typed_rate_always_wins(self, unreachable):
        """The worst bug this could have: a stand-in overwriting somebody's decision."""
        priced = _price(unreachable, default_model(), submitted={"1.30": 180000.0})
        assert priced.index()["1.30"].source == "typed"
        assert "1.30" not in priced.placeholders

    def test_a_derived_rate_always_wins(self, bill, rated):
        """Drilling is priced from the build-up; a placeholder must never reach it."""
        assert _price(bill, rated).index()["2.4"].source == "built"

    def test_it_keys_on_the_unit_so_it_works_on_any_bill(self):
        """Not on the wording. Insert a different tender tomorrow and it fills in the same way."""
        model = default_model()
        assert model.placeholder_for("m3").unit == "m3"
        assert model.placeholder_for("nr-wk").unit == "nr-wk"
        # A unit nobody anticipated still gets the catch-all rather than falling through to a
        # blank, which would look exactly like a decision to price it at nothing.
        assert model.placeholder_for("furlong").unit == ""
        assert model.placeholder_for("").unit == ""

    def test_a_per_week_stand_in_is_sized_against_real_quantities(self):
        """The reference bill carries 2,451 `nr-wk` of standpipe reading. A plausible-sounding
        $3,000/week makes that ONE line HK$7.35M and drowns the priced work — a stand-in whose
        total swamps the bill is worse than a red line, because red is honest."""
        model = default_model()
        assert model.placeholder_for("nr-wk").rate < 500

    def test_the_reason_a_line_could_not_be_priced_survives(self, bill, rated):
        """The explanation is worth more than the stand-in, so the warning goes in FRONT of it."""
        row = _price(bill, rated).index()["1.1"]
        assert row.source == "placeholder"
        assert row.note.startswith("PROVISIONAL")
        assert "one-off end of" in row.note, "the reason must not be thrown away"


class TestASubItemInheritsItsParent:
    """The rig-move item, priced at nothing.

    ``2.2 Moving rigs`` is a heading with no quantity; the money is on ``2.2a "in Class A of site"``
    and ``2.2b "in Class B of site"``. ``heading_path`` stops at the section heading and does not
    include the parent item's own words, so matching on the sub-item's text looked for "moving
    rigs" inside "in Class A of site", found nothing, and left every rig move unpriced.

    Measured on the reference tender: **100 moves — 91 in Bill 2 and 9 in Bill 3 — priced at zero,
    HK$3.8M of real work.** The quantity mapper already knew to look up the tree; this side did not,
    and the two disagreeing about the same item is exactly the failure the app exists to prevent.
    """

    @pytest.fixture
    def parented(self):
        parent = _item("2.2", "Moving rigs", None, "", is_parent=True)
        parent.heading_path = ["SECTION 2 - GROUND INVESTIGATION", "Rigs"]
        children = []
        for sub, qty in (("a", 80), ("b", 11)):
            child = _item(f"2.2{sub}", f"in Class {sub.upper()} of site", qty, "nr")
            child.item_ref, child.sub_ref = "2.2", sub
            child.heading_path = ["SECTION 2 - GROUND INVESTIGATION", "Rigs"]
            children.append(child)
        # The metres matter: `setup_move` is set-up work-days × day-cost ÷ holes, and a bill with
        # no drilling has no programme, so the rate would be a legitimate zero and the test would
        # pass while proving nothing.
        return _bill(
            parent, *children,
            _item("2.4", DRILLING + "material other than rock, boulder or artificial hard material",
                  2300, "m"),
            _item("2.5", DRILLING + "rock", 600, "m"),
        )

    def test_the_rig_moves_are_priced(self, parented):
        mapping = {m.full_ref: m for m in propose_pricing(parented, default_model())}
        assert mapping["2.2a"].basis_key == "setup_move"
        assert mapping["2.2b"].basis_key == "setup_move"

    def test_they_reach_the_total(self, parented):
        priced = _price(parented, default_model())
        assert priced.index()["2.2a"].source == "built"
        assert priced.index()["2.2a"].amount and priced.index()["2.2a"].amount > 0
        assert "2.2a" not in priced.unpriced

    def test_the_sub_item_s_own_words_are_kept_not_replaced(self, parented):
        """Prepended, not substituted — a pattern keying on "Class A" must still work."""
        import re
        from client_boq.boq.costing import propose_pricing as _pp

        mapping = {m.full_ref: m for m in _pp(parented, default_model())}
        assert mapping["2.2a"].description == "in Class A of site"
        assert re.search(r"class a", mapping["2.2a"].description, re.I)

    def test_a_top_level_item_is_unaffected(self, bill):
        """Only a sub-item borrows. An ordinary item must read exactly as it did before."""
        mapping = {m.full_ref: m for m in propose_pricing(bill, default_model())}
        assert mapping["2.4"].basis_key == "soil_drilling"
