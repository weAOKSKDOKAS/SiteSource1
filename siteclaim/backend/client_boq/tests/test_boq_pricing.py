"""The costing model: a condition mix becomes shifts, shifts become a unit rate, and the guards.

The rule these defend: **the assumption is the estimate, so it must reconcile to the client's
quantity and it must be visible in the arithmetic that follows.**

Every figure asserted here is computed by hand in the test, never by calling the code that is under
test — the house rule for arithmetic tests. The worked example is the reference tender's Bill 2
item 2.4, 2,300 m of drilling in material other than rock:

    1,800 m at 12 m/shift  =  150.00 shifts   x 8 h = 1,200.00 h  x 850 = 1,020,000
      300 m at  8 m/shift  =   37.50 shifts   x 8 h =   300.00 h  x 850 =   255,000
      200 m at  6 m/shift  =   33.33 shifts   x 8 h =   266.64 h  x 850 =   226,644
                                220.83 shifts x 3,200 (rig)              =   706,656
                                                                  total = 2,208,300

The bill says 2,300 m and one rate. It does not say which holes those metres come from — the
Method of Measurement slices drilling by material, hole size, depth stage (20 m bands from existing
ground level) and class of site, and the client's quantity surveyor summed all of it. Pricing runs
that backwards, and the mix it runs backwards to is a judgement about ground nobody has drilled.
"""

from __future__ import annotations

import pytest

from client_boq.boq import checks, pricing, production
from client_boq.boq.reader import read_workbook
from client_boq.models import ConditionShare, ItemAssumption, RateRow, ResourceLine, SpreadLine
from client_boq.tests._bqfixture import build_bill_workbook

pytest.importorskip("openpyxl")

CREW, RIG = 850.0, 3200.0
RATES = [
    RateRow(rate_id="LAB-03", code="LAB-03", category="labour", description="Drilling crew",
            unit="h", rate=CREW),
    RateRow(rate_id="PLT-11", code="PLT-11", category="plant", description="Rotary rig",
            unit="shift", rate=RIG),
]


@pytest.fixture(scope="module")
def bill(tmp_path_factory):
    root = tmp_path_factory.mktemp("boqprice")
    return read_workbook(build_bill_workbook(root / "bq-0.xlsx", 0), set_id="t", rev=0)


def _mix(*shares: tuple[str, float, float]) -> ItemAssumption:
    return ItemAssumption(
        full_ref="2.4",
        basis="hole schedule from GI/201-205; rock share from the 14 logs in Site Information",
        conditions=[ConditionShare(label=label, qty=qty, output=output,
                                   crew_ref="LAB-03", plant_ref="PLT-11")
                    for label, qty, output in shares],
    )


FULL_MIX = ("soil, 0-20m, Class A", 1800.0, 12.0), ("soil, 0-20m, Class B", 300.0, 8.0), \
           ("soil, 20-40m, Class A", 200.0, 6.0)


class TestTheMixMustReconcile:
    """The client's quantity is fixed — GCT 6 makes altering the bill a disqualification risk — so a
    mix that disagrees with it is an error in the mix, not something to scale away."""

    def test_a_mix_that_does_not_add_up_is_refused(self, bill):
        short = _mix(("soil", 1800.0, 12.0))                      # 1,800 against the bill's 2,300
        with pytest.raises(production.AssumptionMismatch) as exc:
            production.expand(short, bill.index()["2.4"])
        assert "1,800" in str(exc.value) and "2,300" in str(exc.value)

    def test_it_is_not_quietly_scaled_to_fit(self, bill):
        with pytest.raises(production.AssumptionMismatch) as exc:
            production.expand(_mix(("soil", 1800.0, 12.0)), bill.index()["2.4"])
        assert "not scaled to fit" in str(exc.value)

    def test_a_lump_item_has_no_quantity_to_reconcile(self, bill):
        assumption = ItemAssumption(full_ref="1.5", conditions=[])
        production.check(assumption, bill.index()["1.5"])          # must not raise

    def test_a_condition_with_no_output_rate_is_named_not_treated_as_instant(self, bill):
        mix = _mix(("soil, 0-20m, Class A", 2100.0, 12.0), ("rock", 200.0, 0.0))
        assert production.unpriced_conditions(mix) == ["rock"]


class TestTheMixBecomesResources:
    def test_shifts_are_quantity_over_output(self, bill):
        assert production.shifts_for(_mix(*FULL_MIX)) == [
            ("soil, 0-20m, Class A", 150.0),
            ("soil, 0-20m, Class B", 37.5),
            ("soil, 20-40m, Class A", 33.33),
        ]

    def test_the_blended_output_is_the_number_to_argue_with(self, bill):
        # 2,300 m over 220.83 shifts = 10.4152... m a shift. If nothing on site has ever beaten 9,
        # the mix is wrong before any rate is looked up.
        assert production.weighted_output(_mix(*FULL_MIX)) == 10.42

    def test_each_condition_keeps_its_own_line_so_the_trace_stays_legible(self, bill):
        lines = production.expand(_mix(*FULL_MIX), bill.index()["2.4"]).lines
        assert len(lines) == 6                                    # crew + plant per condition
        assert lines[0].qty == 1200.0 and lines[0].unit == "h"
        assert lines[1].qty == 150.0 and lines[1].unit == "shift"
        assert "1,800 m at 12 per shift" in lines[0].description


class TestTheUnitRate:
    def test_build_up_then_margin_then_divide(self, bill):
        build_up = production.expand(_mix(*FULL_MIX), bill.index()["2.4"])
        priced = pricing.price_bill(bill, {"2.4": build_up}, rates=RATES, margin_pct=15.0)
        entry = next(i for i in priced.items if i.full_ref == "2.4")

        assert entry.build_up == 2_208_300.00                     # hand-computed in the docstring
        assert entry.cost == 2_208_300.00                         # no spread pool in this case
        # cost x 1.15 = 2,539,545.00 ; over 2,300 m = 1,104.15 a metre
        assert entry.unit_rate == 1104.15
        assert entry.amount == 2_539_545.00                       # 2,300 x 1,104.15
        assert entry.rate_source == pricing.RATE_BUILT

    def test_the_extension_is_quantity_times_the_rounded_rate(self, bill):
        build_up = production.expand(_mix(*FULL_MIX), bill.index()["2.4"])
        priced = pricing.price_bill(bill, {"2.4": build_up}, rates=RATES, margin_pct=15.0)
        entry = next(i for i in priced.items if i.full_ref == "2.4")
        assert entry.amount == round(entry.qty * entry.unit_rate, 2)

    def test_changing_one_output_figure_moves_the_rate(self, bill):
        item = bill.index()["2.4"]
        slower = ("soil, 0-20m, Class A", 1800.0, 10.0), ("soil, 0-20m, Class B", 300.0, 8.0), \
                 ("soil, 20-40m, Class A", 200.0, 6.0)
        base = pricing.price_bill(bill, {"2.4": production.expand(_mix(*FULL_MIX), item)},
                                  rates=RATES, margin_pct=15.0)
        moved = pricing.price_bill(bill, {"2.4": production.expand(_mix(*slower), item)},
                                   rates=RATES, margin_pct=15.0)
        first = next(i for i in base.items if i.full_ref == "2.4").unit_rate
        second = next(i for i in moved.items if i.full_ref == "2.4").unit_rate
        # 180 m/shift → 30 extra shifts: 30 x 8 x 850 + 30 x 3,200 = 300,000, x 1.15, over 2,300
        assert round(second - first, 2) == 150.0


class TestLumpItems:
    def test_a_lump_item_prices_its_build_up_and_carries_no_rate(self, bill):
        build_up = production.expand(ItemAssumption(full_ref="1.5", conditions=[]),
                                     bill.index()["1.5"])
        build_up.lines.append(ResourceLine(description="traffic management crew",
                                          resource_ref="LAB-03", qty=100.0, unit="h"))
        priced = pricing.price_bill(bill, {"1.5": build_up}, rates=RATES, margin_pct=15.0)
        entry = next(i for i in priced.items if i.full_ref == "1.5")
        # SMM Corrigendum 1/2007 Part III 3: for an "item", the amount inserted IS the rate, and the
        # rate column prints "-".
        assert entry.unit_rate is None
        assert entry.amount == round(100.0 * CREW * 1.15, 2) == 97_750.00


class TestTheSpreadPool:
    """Particular Preamble 4A: "Any item missed out from the item coverage shall not be measured."
    Costs with no bill line are ordered into the rates by name — site uniform (PP 11/2A), the
    Subcontractor Management Plan (NTT C2), Pay for Safety to subcontractors (NTT C25)."""

    def test_it_is_allocated_pro_rata_on_value_and_lands_on_the_item(self, bill):
        item = bill.index()["2.4"]
        priced = pricing.price_bill(
            bill, {"2.4": production.expand(_mix(*FULL_MIX), item)}, rates=RATES, margin_pct=0.0,
            spread=[SpreadLine(label="site uniform", amount=120_000.0, reason="PP 11 / para 2A")])
        entry = next(i for i in priced.items if i.full_ref == "2.4")
        assert entry.spread == 120_000.0                          # the only priced item takes it all
        assert entry.cost == 2_328_300.00
        assert entry.unit_rate == 1012.30                         # 2,328,300 / 2,300

    def test_the_residue_lands_on_a_named_item_rather_than_vanishing(self, bill):
        item = bill.index()["2.4"]
        priced = pricing.price_bill(
            bill, {"2.4": production.expand(_mix(*FULL_MIX), item)}, rates=RATES,
            spread=[SpreadLine(label="odd pennies", amount=1_000.03, reason="")])
        assert priced.spread_residue_ref == "2.4"
        assert round(sum(i.spread for i in priced.items), 2) == priced.spread_total == 1_000.03

    def test_no_pool_means_no_allocation(self, bill):
        item = bill.index()["2.4"]
        priced = pricing.price_bill(bill, {"2.4": production.expand(_mix(*FULL_MIX), item)},
                                    rates=RATES)
        assert priced.spread_total == 0.0 and priced.spread_residue_ref == ""


class TestTheRollUp:
    def test_totals_add_up_from_page_to_bill_to_A(self, bill):
        item = bill.index()["2.4"]
        priced = pricing.price_bill(bill, {"2.4": production.expand(_mix(*FULL_MIX), item)},
                                    rates=RATES, margin_pct=15.0)
        assert priced.bill_totals["2"] == 2_539_545.00
        # Bill 9 arrives priced by the client: 77,760 + 10,800 + 173,000.
        assert priced.bill_totals["9"] == 261_560.00
        assert priced.tendered_total == round(sum(priced.bill_totals.values()), 2)

    def test_a_pre_priced_item_is_carried_through_untouched(self, bill):
        priced = pricing.price_bill(bill, {}, rates=RATES, margin_pct=99.0)
        entry = next(i for i in priced.items if i.full_ref == "9.1")
        assert entry.unit_rate == 4860.0 and entry.amount == 77_760.0
        assert entry.rate_source == pricing.RATE_CLIENT

    def test_a_parent_is_not_priced(self, tmp_path):
        rev1 = read_workbook(build_bill_workbook(tmp_path / "bq-1.xlsx", 1), set_id="t", rev=1)
        priced = pricing.price_bill(rev1, {}, rates=RATES)
        assert "2.2" not in {i.full_ref for i in priced.items}
        assert {"2.2a", "2.2b"} <= {i.full_ref for i in priced.items}


class TestTheGuards:
    def test_an_unpriced_item_is_named_and_told_what_it_costs(self, bill):
        priced = pricing.price_bill(bill, {}, rates=RATES)
        flags = checks.unpriced_items(priced, bill)
        assert "1.5" in {f.item_id for f in flags}
        assert "General Preambles 6" in flags[0].message
        # Never fires on an item the client priced — those are not ours to rate.
        assert "9.1" not in {f.item_id for f in flags}

    def test_the_client_inserted_sums_are_checked_against_what_was_issued(self, bill):
        assert checks.provisional_sums_intact(
            bill, {"B": 4_342_620.0, "D": 1_550_000.0, "E": 609_370.0}) == []
        flags = checks.provisional_sums_intact(bill, {"B": 9_999_999.0})
        assert flags and "App C 2.5" in flags[0].message

    def test_an_omitted_fee_percentage_is_corrected_to_the_minimum_against_you(self):
        flags = checks.fee_percentage_in_range(None, 5.0, 30.0)
        assert flags and "corrects an omitted one to the minimum" in flags[0].message
        assert checks.fee_percentage_in_range(12.0, 5.0, 30.0) == []
        assert checks.fee_percentage_in_range(45.0, 5.0, 30.0)

    def test_extension_and_casting_are_clean_on_a_bill_the_code_priced(self, bill):
        item = bill.index()["2.4"]
        priced = pricing.price_bill(bill, {"2.4": production.expand(_mix(*FULL_MIX), item)},
                                    rates=RATES, margin_pct=15.0)
        assert checks.extension_errors(priced) == []
        assert checks.casting_errors(priced) == []

    def test_a_tampered_extension_is_caught(self, bill):
        item = bill.index()["2.4"]
        priced = pricing.price_bill(bill, {"2.4": production.expand(_mix(*FULL_MIX), item)},
                                    rates=RATES, margin_pct=15.0)
        next(i for i in priced.items if i.full_ref == "2.4").amount += 1000.0
        flags = checks.extension_errors(priced)
        assert flags and "2.4" == flags[0].item_id
        assert "the rate itself can never be changed" in flags[0].message

    def test_erratic_pricing_stays_quiet_without_enough_comparable_items(self, bill):
        priced = pricing.price_bill(bill, {}, rates=RATES)
        assert checks.erratic_pricing(priced, bill) == []
