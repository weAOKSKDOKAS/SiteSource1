"""The per-class rig-move basis — Class A and Class B moves stop sharing one rate.

SMM S02 ¶2.06 measures "moving rigs in different Classes of site" as different items (TA1 split
2.2 into 2.2a × 80 and 2.2b × 11), and ¶2.08(h) puts access scaffolding in the moving-rigs item
coverage — yet the engine mapped BOTH items to the single pooled `setup_move` basis, so the class
distinction changed no arithmetic and the platform money typed on Site groups reached no rate.

The seam is ADDITIVE and opt-in, exactly as the plan requires: the class variants are DERIVED
(`class_variants`), present in `basis_index` so an item can be pointed at one, absent from
`basis_rows` so nothing changes until one is claimed. Pointing 2.2a/2.2b at them — through the
existing `/costing/item-basis` override, the one channel that leaves the pinned default proposal
untouched — is the whole act of switching the split on. When it is on:

* the set-up work-days PARTITION by the billed hole counts (80/11 — the bill's own numbers,
  because the divisor must match the claiming item's quantity for conservation to balance);
* the Class B row carries the platform builds, and only the Class B row;
* the Phase-1 `platform_cost_unconsumed` guard goes quiet BY CONSTRUCTION — the amount it is
  handed nets what the active wiring actually carries, not a stored boolean.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.boq.buildup import build, build_spread
from client_boq.boq.model import class_variants, default_model
from client_boq.boq.programme import Quantities, derive

BASE = "/client-boq"
SET = "technopole-gi"
TECHNOPOLE = Quantities(holes=91, soil_m=2300.0, rock_m=600.0, hard_m=100.0)
COUNTS = {"A": 80.0, "B": 11.0}


@pytest.fixture
def model():
    return default_model()


@pytest.fixture
def programme(model):
    return derive(TECHNOPOLE, model)


@pytest.fixture
def spread(programme, model):
    return build_spread(programme, model)


class TestTheVariantsAreDerivedNotStored:
    def test_a_setup_row_yields_exactly_its_two_class_variants(self, model):
        pooled = model.basis_index()["setup_move"]
        variants = class_variants(pooled)
        assert [v.key for v in variants] == ["setup_move_a", "setup_move_b"]
        assert [v.site_class for v in variants] == ["A", "B"]

    def test_a_variant_of_a_variant_is_nothing(self, model):
        variant = class_variants(model.basis_index()["setup_move"])[0]
        assert class_variants(variant) == []

    def test_the_index_carries_them_but_the_rows_do_not(self, model):
        assert "setup_move_a" in model.basis_index()
        assert "setup_move_b" in model.basis_index()
        assert all(row.key not in ("setup_move_a", "setup_move_b") for row in model.basis_rows), (
            "declared rows would be evaluated on every tender — the variants must stay opt-in")

    def test_a_non_setup_row_has_no_variants(self, model):
        assert class_variants(model.basis_index()["soil_drilling"]) == []


class TestTheSplitIsAPartition:
    def test_inactive_by_default_the_rows_are_exactly_as_before(self, programme, model, spread):
        rows = {r.key for r in build(programme, model, spread).rows}
        assert "setup_move" in rows
        assert "setup_move_a" not in rows and "setup_move_b" not in rows

    def test_active_the_class_quantities_sum_to_the_pooled_days(self, programme, model, spread):
        pooled = next(r for r in build(programme, model, spread).rows if r.key == "setup_move")
        split = build(programme, model, spread, active_keys={"setup_move_b"},
                      class_counts=COUNTS)
        keys = {r.key for r in split.rows}
        assert "setup_move" not in keys, "the pool is replaced, not doubled"
        row_a = next(r for r in split.rows if r.key == "setup_move_a")
        row_b = next(r for r in split.rows if r.key == "setup_move_b")
        assert row_a.quantity + row_b.quantity == pytest.approx(pooled.quantity)
        assert row_a.divisor == 80.0 and row_b.divisor == 11.0

    def test_claiming_one_variant_still_evaluates_both(self, programme, model, spread):
        """The class nobody pointed an item at still holds real work-days — it must appear (and
        flag on conservation as unclaimed) rather than vanish."""
        split = build(programme, model, spread, active_keys={"setup_move_a"},
                      class_counts=COUNTS)
        assert any(r.key == "setup_move_b" and r.total_cost > 0 for r in split.rows)

    def test_the_platform_lands_in_the_b_row_and_only_the_b_row(self, programme, model, spread):
        bare = build(programme, model, spread, active_keys={"setup_move_b"}, class_counts=COUNTS)
        loaded = build(programme, model, spread, active_keys={"setup_move_b"},
                       class_counts=COUNTS, platform_cost_b=210_000.0)
        bare_a = next(r for r in bare.rows if r.key == "setup_move_a")
        bare_b = next(r for r in bare.rows if r.key == "setup_move_b")
        row_a = next(r for r in loaded.rows if r.key == "setup_move_a")
        row_b = next(r for r in loaded.rows if r.key == "setup_move_b")
        assert row_a.total_cost == pytest.approx(bare_a.total_cost), "Class A is untouched"
        assert row_b.total_cost == pytest.approx(bare_b.total_cost + 210_000.0)
        assert "2.08(h)" in row_b.derivation
        assert row_b.cost_per_unit == pytest.approx(row_b.total_cost / 11.0)

    def test_the_platform_is_ignored_while_the_split_is_inactive(self, programme, model, spread):
        """Folding it into the pooled row would price Class A moves as if they needed platforms."""
        without = build(programme, model, spread)
        with_platform = build(programme, model, spread, platform_cost_b=210_000.0)
        assert without.total_direct_cost == pytest.approx(with_platform.total_direct_cost)

    def test_a_class_the_bill_does_not_count_is_unpriced_not_guessed(self, programme, model,
                                                                     spread):
        split = build(programme, model, spread, active_keys={"setup_move_b"},
                      class_counts={"A": 91.0})
        row_b = next(r for r in split.rows if r.key == "setup_move_b")
        assert row_b.cost_per_unit is None
        assert "left unpriced rather than guessed" in row_b.problem


class TestThroughTheEngine:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch) -> TestClient:
        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
        pytest.importorskip("openpyxl")
        from api import app

        return TestClient(app)

    def _import_bill(self, client, tmp_path):
        """Fixture revision 1 — the one carrying TA1's 2.2 → 2.2a (80) / 2.2b (11) split. The
        rev-0 workbook still bills one pooled 2.2 × 91, which is exactly the world where the
        per-class basis has nothing to claim."""
        from client_boq.tests._bqfixture import build_bill_workbook

        path = build_bill_workbook(tmp_path / "bq-1.xlsx", 1)
        with open(path, "rb") as fh:
            assert client.post(
                f"{BASE}/boq/import", data={"set_id": SET},
                files={"file": (path.name, fh.read(), "application/vnd.ms-excel")},
            ).status_code == 200

    def _platform_group(self, client, cost=120_000.0):
        assert client.post(
            f"{BASE}/site/group", headers={"X-CBOQ-Actor": "SW"},
            json={"set_id": SET, "group_id": "hillside",
                  "group": {"label": "Hillside", "stations": ["A1"], "access_class": "B",
                            "access_build_cost": cost}},
        ).status_code == 200

    def _point_at_class_bases(self, client):
        for ref, key in (("2.2a", "setup_move_a"), ("2.2b", "setup_move_b")):
            reply = client.post(f"{BASE}/costing/item-basis", headers={"X-CBOQ-Actor": "SW"},
                                json={"set_id": SET, "full_ref": ref, "basis_key": key})
            assert reply.status_code == 200, reply.text

    def test_the_two_moves_stop_sharing_one_rate(self, client, tmp_path):
        self._import_bill(client, tmp_path)
        self._platform_group(client)

        before = client.get(f"{BASE}/costing/{SET}").json()
        rows = {r["full_ref"]: r for r in before["priced"]["rows"]}
        assert rows["2.2a"]["cost_basis"] == rows["2.2b"]["cost_basis"], (
            "the default is the pinned pooled basis — identical per-move figure")

        self._point_at_class_bases(client)
        after = client.get(f"{BASE}/costing/{SET}").json()
        rows = {r["full_ref"]: r for r in after["priced"]["rows"]}
        assert rows["2.2b"]["cost_basis"] > rows["2.2a"]["cost_basis"], (
            "eleven Class B moves carry the platform; eighty Class A moves do not")

    def test_conservation_stays_clean_across_the_split(self, client, tmp_path):
        self._import_bill(client, tmp_path)
        self._point_at_class_bases(client)
        body = client.get(f"{BASE}/costing/{SET}").json()
        balanced = {b["key"]: b for b in body["conservation"]["bases"]}
        assert balanced["setup_move_a"]["claimed_qty"] == balanced["setup_move_a"]["divisor"] == 80
        assert balanced["setup_move_b"]["claimed_qty"] == balanced["setup_move_b"]["divisor"] == 11
        assert "setup_move" not in balanced

    def test_the_guard_goes_quiet_by_construction(self, client, tmp_path):
        self._import_bill(client, tmp_path)
        self._platform_group(client)
        assert client.get(f"{BASE}/boq/{SET}/checks").json()["counts"].get(
            "platform_cost_unconsumed") == 1, "typed and unconsumed — the Phase-1 guard fires"

        self._point_at_class_bases(client)
        body = client.get(f"{BASE}/boq/{SET}/checks").json()
        assert "platform_cost_unconsumed" not in body["counts"], (
            "the Class B basis now carries the platform — same guard, zero remainder")

    def test_a_platform_on_a_class_a_group_stays_flagged(self, client, tmp_path):
        """A Class A move must not carry a platform it does not need — money typed on an A group
        is NOT absorbed by the split, and the guard keeps naming it."""
        self._import_bill(client, tmp_path)
        assert client.post(
            f"{BASE}/site/group", headers={"X-CBOQ-Actor": "SW"},
            json={"set_id": SET, "group_id": "roadside",
                  "group": {"label": "Roadside", "stations": ["A2"], "access_class": "A",
                            "access_build_cost": 30_000.0}},
        ).status_code == 200
        self._point_at_class_bases(client)
        body = client.get(f"{BASE}/boq/{SET}/checks").json()
        flags = [f for f in body["flags"] if f["kind"] == "platform_cost_unconsumed"]
        assert len(flags) == 1 and "30,000.00" in flags[0]["message"]

    def test_a_sweep_load_onto_the_rig_move_item_also_nets_off(self, client, tmp_path):
        """The guard's own message offers the sweep as the interim route — money routed that way
        must count as handled, or the guard nags about a cost the estimator already placed."""
        self._import_bill(client, tmp_path)
        self._platform_group(client, cost=120_000.0)
        assert client.post(f"{BASE}/price/sweep", headers={"X-CBOQ-Actor": "SW"},
                           json={"set_id": SET, "key": "platforms", "label": "Platforms",
                                 "amount": 50_000.0, "route": "load",
                                 "target_ref": "2.2b"}).status_code == 200
        flags = [f for f in client.get(f"{BASE}/boq/{SET}/checks").json()["flags"]
                 if f["kind"] == "platform_cost_unconsumed"]
        assert len(flags) == 1 and "70,000.00" in flags[0]["message"]
