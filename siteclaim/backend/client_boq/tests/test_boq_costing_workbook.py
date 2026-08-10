"""The deliverable: eight sheets that still calculate.

The rule these defend: **what leaves the app is a model, not a report.**

Every other workbook this repo writes emits dead numbers, which is right for a record of something
already decided. This one is the estimator's working model handed back — change a blue cell on
``01 Inputs`` and every rate on ``05 BQ Priced`` moves, in Excel, on a train, with the app switched
off. That is also the honest answer to "what if I want to do something the engine cannot".

``openpyxl`` writes formulas but never evaluates them, so nothing here can be proved by reading the
numbers back. The numbers are proved in the engine's own tests; this file proves the **wiring** — that
the sheets exist, that a rate really is a formula rather than a pasted value, and that every
cross-sheet reference points at a cell that exists.
"""

from __future__ import annotations

import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from client_boq.boq.assumptions import build as build_register
from client_boq.boq.buildup import build as build_buildup
from client_boq.boq.buildup import build_spread
from client_boq.boq.costing import price, propose_quantities
from client_boq.boq.costing_workbook import SHEETS, build_workbook
from client_boq.boq.model import default_model
from client_boq.boq.programme import derive
from client_boq.models import BillItem, ClientBill

DRILLING = "Drilling H or N size, vertically downwards, "


@pytest.fixture
def bill():
    def item(ref, description, qty, unit, **kwargs):
        return BillItem(bill_no=ref.split(".")[0], full_ref=ref, description=description,
                        qty=qty, unit=unit, **kwargs)

    return ClientBill(set_id="technopole-gi", rev=0, items=[
        item("2.1", "Establishment of rigs", None, "item", lump=True),
        item("2.2", "Moving rigs", 91, "nr"),
        item("2.3", "Standing time for rigs", 455, "h"),
        item("2.4", DRILLING + "material other than rock, boulder or artificial hard material",
             2300, "m"),
        item("2.5", DRILLING + "rock", 600, "m"),
        item("2.6", DRILLING + "artificial hard material or boulder", 100, "m"),
        item("4.1", "Moisture content determination test", 273, "nr"),
        item("3.9", "Chemical grouting of an abandoned adit", 5, "m3"),
    ])


@pytest.fixture
def parts(bill):
    model = default_model()
    # Stand-ins off for the workbook fixture: these tests are about how the SHEET renders a line
    # the model could not price, and a placeholder would put a number in the cell they assert is
    # empty. Placeholder rendering has its own tests.
    model.use_placeholders = False
    programme = derive(propose_quantities(bill).quantities(), model)
    spread = build_spread(programme, model)
    buildup = build_buildup(programme, model, spread)
    priced = price(bill, model, programme, buildup)
    register = build_register(programme, model, buildup, spread, billed_standing_hours=455.0)
    return model, programme, spread, buildup, priced, register


@pytest.fixture
def book(parts):
    model, programme, spread, buildup, priced, register = parts
    raw = build_workbook(model, programme, spread, buildup, priced, register,
                         contract_reference="ND/2025/04")
    return openpyxl.load_workbook(io.BytesIO(raw))


def _cells(ws):
    return {cell.coordinate: cell.value for row in ws.iter_rows() for cell in row
            if cell.value is not None}


def _formulas(ws):
    return {ref: value for ref, value in _cells(ws).items()
            if isinstance(value, str) and value.startswith("=")}


class TestTheShape:
    def test_all_eight_sheets_are_there_and_in_order(self, book):
        assert book.sheetnames == list(SHEETS)

    def test_the_readme_states_the_colour_convention_and_the_gate(self, book):
        text = " ".join(str(v) for v in _cells(book["00 README"]).values())
        assert "BLUE" in text and "a formula" in text
        assert "P90" in text and "POINT ESTIMATE" in text

    def test_the_inputs_sheet_carries_typed_values_not_formulas(self, book):
        # This is the one sheet somebody edits, so nothing on it may be derived.
        ws = book["01 Inputs"]
        assert not any(ref.startswith("C") for ref in _formulas(ws)), \
            "an input that is a formula is an input nobody can change"

    def test_every_production_band_reaches_the_inputs_sheet(self, book, parts):
        model = parts[0]
        labels = [str(v) for v in _cells(book["01 Inputs"]).values()]
        for band in model.bands.bands:
            assert band.label in labels


class TestItStillCalculates:
    def test_the_programme_is_derived_from_the_quantities(self, book):
        formulas = " ".join(_formulas(book["02 Production"]).values())
        assert "MATCH(" in formulas, "the band is looked up, not pasted"
        assert "INDEX(" in formulas
        assert "ROUNDUP(" in formulas, "core boxes round up"
        assert "PI()" in formulas, "the grout volume is a cylinder"

    def test_the_convergence_check_is_a_live_formula_with_the_models_thresholds(self, book, parts):
        model = parts[0]
        formulas = " ".join(_formulas(book["02 Production"]).values())
        assert "DIVERGENT" in formulas and "converged" in formulas
        assert str(model.method.divergent_threshold) in formulas

    def test_each_day_cost_is_a_sum_of_its_own_lines(self, book):
        # RE-ANCHORED IN THE OPEN, from two subtotals to three. The count was never the subject:
        # this test is about each day-cost being a live SUM over its OWN block rather than a typed
        # figure or a shared range. The site-team/GFT split made supervision two resources, so
        # there are now three blocks — A per rig-day, B per contract-day (the site team), B2 per
        # GFT-day. It is written against the model's own charge classes so a fourth would be
        # counted rather than break it.
        from client_boq.boq.model import CHARGE_GFT, CHARGE_RIG_DAY, CHARGE_CONTRACT_DAY

        formulas = list(_formulas(book["03 Resource Rates"]).values())
        expected = len({CHARGE_RIG_DAY, CHARGE_CONTRACT_DAY, CHARGE_GFT})
        assert sum(1 for f in formulas if f.startswith("=SUM(E")) == expected, \
            "one subtotal per day-cost block, each summing only its own rows"

    def test_a_resource_line_reads_its_rate_from_the_inputs_sheet(self, book):
        formulas = " ".join(_formulas(book["03 Resource Rates"]).values())
        assert "'01 Inputs'!" in formulas

    def test_the_selling_factor_is_the_product_of_the_chain(self, book):
        ws = book["04 Item Buildup"]
        combined = [f for f in _formulas(ws).values() if f.count("F") >= 2 and "*" in f]
        assert combined, "the combined factor multiplies the individual steps"

    def test_a_margin_taken_on_selling_price_is_written_as_such(self, book):
        formulas = list(_formulas(book["04 Item Buildup"]).values())
        assert any("=1/(1-" in f for f in formulas), "10% margin is 1/(1-0.1), not 1.1"
        assert any(f.startswith("=1+") for f in formulas), "and a loading is 1 + v"

    def test_a_rate_is_a_formula_all_the_way_down(self, book):
        ws = book["05 BQ Priced"]
        formulas = _formulas(ws)
        # Find the soil drilling row by its description, then walk its columns.
        row = next(cell.row for r in ws.iter_rows() for cell in r
                   if cell.value == "2.4")
        assert formulas[f"G{row}"].startswith("=IF(ISNUMBER(")     # direct cost
        assert formulas[f"H{row}"].startswith("='04 Item Buildup'")  # selling factor
        assert formulas[f"I{row}"] == f"=F{row}*H{row}"             # raw rate
        assert "ROUND(" in formulas[f"J{row}"]                       # rounded proposal
        assert formulas[f"L{row}"].startswith("=IF(ISNUMBER(")      # amount

    def test_the_cost_basis_links_back_to_the_buildup(self, book):
        ws = book["05 BQ Priced"]
        row = next(cell.row for r in ws.iter_rows() for cell in r if cell.value == "2.4")
        assert _formulas(ws)[f"F{row}"].startswith("='04 Item Buildup'")

    def test_the_bill_total_sums_the_amount_column(self, book):
        assert any(f.startswith("=SUM(L") for f in _formulas(book["05 BQ Priced"]).values())


class TestTheRateToSubmitIsTheEstimators:
    def test_it_is_a_value_and_not_a_formula(self, book):
        ws = book["05 BQ Priced"]
        row = next(cell.row for r in ws.iter_rows() for cell in r if cell.value == "2.4")
        submitted = ws[f"K{row}"].value
        assert isinstance(submitted, (int, float)), \
            "column K has to be typeable — a formula there would take the last decision away"

    def test_the_rounded_proposal_stays_beside_it(self, book):
        ws = book["05 BQ Priced"]
        row = next(cell.row for r in ws.iter_rows() for cell in r if cell.value == "2.4")
        assert "ROUND(" in ws[f"J{row}"].value

    def test_the_amount_follows_the_submitted_rate_not_the_proposal(self, book):
        ws = book["05 BQ Priced"]
        row = next(cell.row for r in ws.iter_rows() for cell in r if cell.value == "2.4")
        assert f"K{row}" in ws[f"L{row}"].value and f"J{row}" not in ws[f"L{row}"].value


class TestNothingDisappearsQuietly:
    def test_an_item_with_no_cost_basis_is_marked_on_the_sheet(self, book):
        ws = book["05 BQ Priced"]
        row = next(cell.row for r in ws.iter_rows() for cell in r if cell.value == "3.9")
        assert ws[f"K{row}"].value == "NO RATE"
        assert "for the life of the contract" in str(ws[f"M{row}"].value)

    def test_the_register_gate_is_a_live_countblank(self, book):
        formulas = " ".join(_formulas(book["06 Assumptions Register"]).values())
        assert "COUNTBLANK(" in formulas
        assert "NOT CLEARED" in formulas and "CLEARED" in formulas

    def test_the_register_arrives_with_every_status_blank(self, book, parts):
        register = parts[5]
        assert register.gate() == "NOT CLEARED"
        assert len(register.outstanding()) == len(register.rows)

    def test_low_confidence_assumptions_are_flagged_on_the_sheet(self, book, parts):
        register = parts[5]
        assert {r.key for r in register.low_confidence()} >= {
            "residual_site_factor", "supervision_allocation", "laboratory", "item_coverage"}

    def test_the_empirical_sheet_carries_the_findings_that_shaped_the_model(self, book):
        text = " ".join(str(v) for v in _cells(book["07 Empirical Basis"]).values())
        assert "does not decay with depth" in text
        assert "typhoon season was the fastest" in text
        assert "negative intercept" in text


class TestEveryReferencePointsSomewhere:
    def test_no_formula_points_at_a_sheet_that_is_not_in_the_book(self, book):
        names = set(book.sheetnames)
        for sheet in book.worksheets:
            for formula in _formulas(sheet).values():
                for name in names:
                    formula = formula.replace(f"'{name}'!", "")
                assert "'" not in formula, f"{sheet.title}: {formula} names a sheet that is absent"

    def test_no_formula_was_left_pointing_at_nothing(self, book):
        for sheet in book.worksheets:
            for ref, formula in _formulas(sheet).items():
                assert formula != "=0", f"{sheet.title}!{ref} lost the cell it meant to reference"


class TestTheModelDrivesTheSheets:
    def test_a_deleted_resource_leaves_the_workbook(self, bill):
        model = default_model()
        model.spread = [l for l in model.spread if l.key != "drill_rig"]
        programme = derive(propose_quantities(bill).quantities(), model)
        spread = build_spread(programme, model)
        buildup = build_buildup(programme, model, spread)
        raw = build_workbook(model, programme, spread, buildup,
                             price(bill, model, programme, buildup),
                             build_register(programme, model, buildup, spread))
        book = openpyxl.load_workbook(io.BytesIO(raw))
        labels = [str(v) for v in _cells(book["03 Resource Rates"]).values()]
        assert "Drill rig" not in labels

    def test_an_added_band_appears_on_the_inputs_sheet(self, bill):
        from client_boq.boq.empirical import Band
        model = default_model()
        model.bands.bands.append(Band(label="a band somebody added", lower=0.20, rate=9.9,
                                      holes=40, calibration_depth_m=33.0))
        programme = derive(propose_quantities(bill).quantities(), model)
        spread = build_spread(programme, model)
        buildup = build_buildup(programme, model, spread)
        raw = build_workbook(model, programme, spread, buildup,
                             price(bill, model, programme, buildup),
                             build_register(programme, model, buildup, spread))
        book = openpyxl.load_workbook(io.BytesIO(raw))
        assert "a band somebody added" in [str(v) for v in _cells(book["01 Inputs"]).values()]
