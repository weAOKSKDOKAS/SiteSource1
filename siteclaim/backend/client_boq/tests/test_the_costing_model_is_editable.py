"""The costing model is a thing a person can edit, and the app says what every knob IS.

`CostingModel.inputs` is a bare `dict[str, float]`, which is right for the engine and useless for a
human: a key and a number say nothing about what the number means, what it is measured in, or
whether 0.1 is ten percent or a tenth of a metre. The workbook knew all of that and kept it inside
the writer, where nothing else could reach it — so a screen would have needed a second copy, and
the two would have drifted the first time an input was added.

`model.INPUT_SPECS` is that knowledge, declared once. The workbook reads it; the API serves it; the
Library screen renders from it. These tests are the anti-drift guard: an input with no spec, or a
spec naming an input that does not exist, is a failure here rather than a knob that silently
becomes invisible on both surfaces.
"""

import pytest
from fastapi.testclient import TestClient

from api import app
from client_boq.boq import model as boq_model
from client_boq.boq.model import (
    DEFAULT_INPUTS,
    INPUT_BLOCKS,
    INPUT_SPEC_INDEX,
    INPUT_SPECS,
    RETIRED_INPUTS,
    default_model,
    specs_in,
)

BASE = "/client-boq"


@pytest.fixture()
def client():
    return TestClient(app)


class TestEveryInputIsDeclared:
    def test_every_default_input_has_a_spec(self):
        """A knob nobody declared is a knob nobody can find. It would be absent from the workbook
        AND from the screen, and the only sign would be a number that never moves."""
        undeclared = sorted(set(DEFAULT_INPUTS) - set(INPUT_SPEC_INDEX))
        assert not undeclared, f"inputs with no InputSpec: {undeclared}"

    def test_every_spec_names_a_real_input(self):
        """The other direction. A spec for a key that does not exist renders an editable row that
        writes into nothing — the same silent-zero class `problems()` already guards against."""
        phantom = sorted(set(INPUT_SPEC_INDEX) - set(DEFAULT_INPUTS))
        assert not phantom, f"specs naming inputs that do not exist: {phantom}"

    def test_a_retired_input_is_deliberately_not_declared(self):
        """Retirement is the one legitimate way to be in neither list: nothing reads it, so it has
        no spec, and it is not in the defaults either. It is reported instead."""
        for key in RETIRED_INPUTS:
            assert key not in DEFAULT_INPUTS
            assert key not in INPUT_SPEC_INDEX

    def test_every_spec_sits_in_a_declared_block(self):
        stray = sorted({s.block for s in INPUT_SPECS} - set(INPUT_BLOCKS))
        assert not stray, f"specs in blocks the screen will never render: {stray}"

    def test_every_block_has_at_least_one_spec(self):
        empty = [b for b in INPUT_BLOCKS if not specs_in(b)]
        assert not empty, f"blocks that would render as an empty heading: {empty}"

    def test_the_1a_inputs_are_declared_and_the_gft_ratio_is_marked_key(self):
        for key in ("site_count", "site_team_per_site", "gft_ratio"):
            assert key in INPUT_SPEC_INDEX
            assert INPUT_SPEC_INDEX[key].block == "ORGANISATION"
        assert INPUT_SPEC_INDEX["gft_ratio"].key_assumption
        assert "does not move with the rig count" in INPUT_SPEC_INDEX["gft_ratio"].note

    def test_a_percentage_input_is_marked_so_it_is_not_shown_as_a_tenth(self):
        assert INPUT_SPEC_INDEX["margin"].percent
        assert INPUT_SPEC_INDEX["nec_fee"].percent
        assert not INPUT_SPEC_INDEX["contract_period_months"].percent
        # The stored value is a fraction either way. `percent` is about display, never storage.
        assert DEFAULT_INPUTS["margin"] == 0.10


class TestTheWorkbookReadsTheSameDeclarations:
    def test_the_sheet_prints_every_declared_input_with_its_declared_label(self):
        import io

        openpyxl = pytest.importorskip("openpyxl")
        from client_boq.boq import assumptions as assum
        from client_boq.boq.buildup import build, build_spread
        from client_boq.boq.costing import PricedBQ
        from client_boq.boq.costing_workbook import build_workbook
        from client_boq.boq.programme import Quantities, derive

        model = default_model()
        programme = derive(Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0), model)
        spread = build_spread(programme, model)
        buildup = build(programme, model, spread)
        register = assum.build(programme, model, buildup, spread)
        data = build_workbook(model, programme, spread, buildup, PricedBQ(), register)

        sheet = openpyxl.load_workbook(io.BytesIO(data))["01 Inputs"]
        printed = {row[0].value: row[1].value for row in sheet.iter_rows(min_col=2, max_col=3)}
        for spec in INPUT_SPECS:
            assert spec.label in printed, f"{spec.key!r} is declared but the sheet never prints it"
            assert printed[spec.label] == pytest.approx(model.value(spec.key))


class TestTheLibraryModelIsServedAndSaved:
    def test_the_get_carries_the_declarations_the_screen_renders_from(self, client):
        body = client.get(f"{BASE}/costing/model").json()
        assert body["usable"] is True and body["problems"] == []
        assert body["input_blocks"] == list(INPUT_BLOCKS)
        assert {s["key"] for s in body["input_specs"]} == set(INPUT_SPEC_INDEX)
        # The three day-costs plus the two things that are not day-costs, each said in words.
        assert set(body["charge_labels"]) == {"rig_day", "contract_day", "gft", "prelim", "none"}
        assert "per site" in body["charge_labels"]["contract_day"]
        assert "gft_ratio" in body["charge_labels"]["gft"]

    def test_a_seeded_library_carries_no_retired_inputs(self, client):
        assert client.get(f"{BASE}/costing/model").json()["retired"] == []

    def test_saving_the_library_model_changes_what_the_next_read_returns(self, client):
        body = client.get(f"{BASE}/costing/model").json()
        model = body["model"]
        model["inputs"]["gft_ratio"] = 4.0

        saved = client.put(f"{BASE}/costing/model", json={"model": model})
        assert saved.status_code == 200, saved.text
        assert saved.json()["problems"] == []

        again = client.get(f"{BASE}/costing/model").json()
        assert again["model"]["inputs"]["gft_ratio"] == 4.0

        model["inputs"]["gft_ratio"] = 6.0        # put it back; the store is shared in this suite
        client.put(f"{BASE}/costing/model", json={"model": model})

    def test_a_stale_input_saved_onto_the_library_comes_back_named_and_inert(self, client):
        body = client.get(f"{BASE}/costing/model").json()
        model = body["model"]
        model["inputs"]["site_team_supervises_rigs"] = 3.0
        client.put(f"{BASE}/costing/model", json={"model": model})

        again = client.get(f"{BASE}/costing/model").json()
        retired = {r["key"]: r for r in again["retired"]}
        assert "site_team_supervises_rigs" in retired
        assert retired["site_team_supervises_rigs"]["value"] == 3.0
        assert "gft_ratio" in retired["site_team_supervises_rigs"]["why"]
        assert again["usable"] is True, "inert, so it does not stop the model pricing"

        del model["inputs"]["site_team_supervises_rigs"]
        client.put(f"{BASE}/costing/model", json={"model": model})
        assert client.get(f"{BASE}/costing/model").json()["retired"] == []

    def test_the_two_model_endpoints_are_different_things(self, client):
        """The library's model and a tender's are separate writes on purpose: one changes every
        future tender, the other changes exactly one and rewrites nothing else."""
        paths = client.get("/openapi.json").json()["paths"]
        assert "put" in paths[f"{BASE}/costing/model"]
        assert "put" in paths[f"{BASE}/costing/{{set_id}}/model"]
        assert "delete" in paths[f"{BASE}/costing/{{set_id}}/model"]


class TestTheDeclarationsTravelWithATenderToo:
    def test_the_helper_returns_the_same_shape_for_any_model(self):
        """The tender payload and the library payload are built by ONE function, so a screen that
        can render one can render the other. Two builders would have drifted."""
        from client_boq.router import _model_declarations

        declared = _model_declarations(default_model())
        assert set(declared) == {"input_blocks", "input_specs", "charge_labels", "retired"}
        assert len(declared["input_specs"]) == len(INPUT_SPECS)

    def test_a_model_carrying_a_retired_key_reports_it_through_the_helper(self):
        from client_boq.router import _model_declarations

        model = default_model()
        model.inputs["site_team_supervises_rigs"] = 6.0
        reported = _model_declarations(model)["retired"]
        assert [r["key"] for r in reported] == ["site_team_supervises_rigs"]
        assert reported[0]["value"] == 6.0


def test_the_charge_labels_cover_every_charge_the_model_can_carry():
    """A spread line whose charge has no label would render under a blank heading."""
    from client_boq.router import _model_declarations

    labels = _model_declarations(default_model())["charge_labels"]
    assert set(boq_model.CHARGES) <= set(labels), "a charge class with nothing to call it"
    for line in default_model().spread:
        assert line.charge in labels
