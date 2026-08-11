"""The sweep pool, from the routing decision to the rate that carries it.

`price_bill` has taken a `spread=` argument since it was written. `_allocate` behind it is written
and tested. `PricedItem.spread` is carried per item and `RateTrace` has a node for it. And nothing in
production ever constructed a `SpreadLine` — the one type the argument wants — so `spread=None` at
both call sites, every share 0.0, and the trace's `spread_share` was a literal `0.0` beside a
`spread_total` read from the real sweep and then discarded, because `trace.py` guards the node on
`if spread_share:`.

The costs concerned are not marginal. The contract names them and orders them into the rates:

    PP 11/2A (site uniform), NTT C2 (Subcontractor Management Plan), NTT C25 (Pay for Safety to
    subcontractors) — "There shall be no measurement or separate payment."
    Particular Preamble 4A — "Any item missed out from the item coverage shall not be measured."

So the estimator routes the cost to SPREAD, the screen shows the pool, and the money reaches nothing.
That is this codebase's recurring shape: the number was right and the population was never checked.

The last test here is the other half of it. Allocation is pro rata on build-up value, so a pool with
no built item lands nowhere at all — and `spread_total` still reports it. The guard makes that loud
instead of letting the pool read as handled.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.boq import checks as boq_checks
from client_boq.boq.pricing import price_bill
from client_boq.boq.unbilled import (
    ROUTE_ACCEPT,
    ROUTE_LOAD,
    ROUTE_QUERY,
    ROUTE_SPREAD,
    UnbilledCost,
    UnbilledSweep,
)
from client_boq.models import BillItem, ClientBill, ResourceLine, ScheduleItem
from client_boq.tests._bqfixture import build_bill_workbook

BASE = "/client-boq"
SET = "technopole-gi"

UNIFORM = "site uniform (PP 11/2A — no measurement or separate payment)"


def _bill() -> ClientBill:
    return ClientBill(set_id=SET, rev=0, items=[
        BillItem(bill_no="2", full_ref="2.4", description="Drilling, soil", qty=2000.0, unit="m"),
        BillItem(bill_no="2", full_ref="2.5", description="Drilling, rock", qty=500.0, unit="m"),
        BillItem(bill_no="9", full_ref="9.1", description="Pay for Safety", qty=1.0, unit="item",
                 lump=True, pre_priced=True, client_rate=429810.0, client_amount=429810.0),
    ])


def _build_up(ref: str, amount: float) -> ScheduleItem:
    """A one-line direct build-up at an inline rate — the smallest thing `build_cost` will price.

    It has to be `direct`: `build_cost` skips every other category, so an `indirect`/`lump` item
    produces no activity, no build-up cost, and therefore nothing for the pool to land on.
    """
    return ScheduleItem(item_id=ref, description=ref, category="direct", unit="sum",
                        lines=[ResourceLine(description=ref, inline_rate=amount, qty=1.0)])


class TestARoutedCostBecomesASpreadLine:
    def test_a_spread_cost_arrives_as_the_line_the_pricing_engine_takes(self):
        sweep = UnbilledSweep(set_id=SET, costs=[
            UnbilledCost(key="uniform", label=UNIFORM, amount=18000.0, route=ROUTE_SPREAD,
                         source="PP 11/2A", decided_by="SW"),
        ])
        lines = sweep.spread_lines()
        assert [(line.label, line.amount) for line in lines] == [(UNIFORM, 18000.0)]
        assert lines[0].reason == "PP 11/2A", "the clause travels with the money"

    def test_the_lines_total_what_the_sweep_says_the_pool_is(self):
        sweep = UnbilledSweep(set_id=SET, costs=[
            UnbilledCost(key="a", label="a", amount=18000.0, route=ROUTE_SPREAD, decided_by="SW"),
            UnbilledCost(key="b", label="b", amount=4250.5, route=ROUTE_SPREAD, decided_by="SW"),
        ])
        assert sum(line.amount for line in sweep.spread_lines()) == sweep.spread_total()

    def test_only_the_spread_route_is_in_the_pool(self):
        sweep = UnbilledSweep(set_id=SET, costs=[
            UnbilledCost(key="s", label="s", amount=100.0, route=ROUTE_SPREAD, decided_by="SW"),
            UnbilledCost(key="l", label="l", amount=200.0, route=ROUTE_LOAD, target_ref="2.4",
                         decided_by="SW"),
            UnbilledCost(key="a", label="a", amount=300.0, route=ROUTE_ACCEPT, reason="risk",
                         decided_by="SW"),
        ])
        assert [line.label for line in sweep.spread_lines()] == ["s"]

    def test_a_queried_cost_with_no_number_is_not_given_one(self):
        # The query exists because nobody knows the amount. Inventing one to tidy the pool is the
        # opposite of what it is for.
        sweep = UnbilledSweep(set_id=SET, costs=[
            UnbilledCost(key="q", label="q", amount=None, route=ROUTE_QUERY, reason="asked",
                         decided_by="SW"),
        ])
        assert sweep.spread_lines() == []

    def test_a_spread_cost_whose_amount_is_still_unknown_is_not_spread_as_zero(self):
        sweep = UnbilledSweep(set_id=SET, costs=[
            UnbilledCost(key="s", label="s", amount=None, route=ROUTE_SPREAD, decided_by="SW"),
        ])
        assert sweep.spread_lines() == []


class TestThePoolReachesTheRates:
    @pytest.fixture
    def priced(self):
        sweep = UnbilledSweep(set_id=SET, costs=[
            UnbilledCost(key="uniform", label=UNIFORM, amount=20000.0, route=ROUTE_SPREAD,
                         source="PP 11/2A", decided_by="SW"),
        ])
        return price_bill(
            _bill(),
            {"2.4": _build_up("2.4", 300000.0), "2.5": _build_up("2.5", 100000.0)},
            rates=[], spread=sweep.spread_lines(),
        )

    def test_every_penny_of_the_pool_lands_on_an_item(self, priced):
        assert priced.spread_total == 20000.0
        assert sum(entry.spread for entry in priced.items) == pytest.approx(20000.0, abs=0.005)

    def test_it_lands_pro_rata_on_build_up_value(self, priced):
        share = {entry.full_ref: entry.spread for entry in priced.items}
        assert share["2.4"] == pytest.approx(15000.0, abs=0.01)
        assert share["2.5"] == pytest.approx(5000.0, abs=0.01)

    def test_a_pre_priced_item_carries_none_of_it(self, priced):
        # GCT App C 2.2(vi) reinstates the client's own figure at examination, so loading it would
        # be money spread onto a rate that is going to be thrown away.
        entry = next(e for e in priced.items if e.full_ref == "9.1")
        assert entry.spread == 0.0

    def test_the_pool_is_inside_the_unit_rate_not_beside_it(self, priced):
        entry = next(e for e in priced.items if e.full_ref == "2.4")
        assert entry.cost == pytest.approx(315000.0, abs=0.01)
        assert entry.unit_rate == pytest.approx(315000.0 / 2000.0, abs=0.01)

    def test_without_the_pool_the_tendered_total_is_short_by_exactly_it(self):
        build_ups = {"2.4": _build_up("2.4", 300000.0), "2.5": _build_up("2.5", 100000.0)}
        without = price_bill(_bill(), build_ups, rates=[])
        with_pool = price_bill(_bill(), build_ups, rates=[], spread=UnbilledSweep(costs=[
            UnbilledCost(key="u", label=UNIFORM, amount=20000.0, route=ROUTE_SPREAD,
                         decided_by="SW")]).spread_lines())
        assert with_pool.tendered_total - without.tendered_total == pytest.approx(20000.0, abs=0.02)


class TestAPoolThatLandsNowhereIsSaidSo:
    def test_a_pool_with_no_built_item_to_land_on_is_flagged(self):
        bill = _bill()
        priced = price_bill(bill, {}, rates=[], spread=UnbilledSweep(costs=[
            UnbilledCost(key="u", label=UNIFORM, amount=20000.0, route=ROUTE_SPREAD,
                         decided_by="SW")]).spread_lines())
        # The pool is reported and reaches nothing: the exact shape the guard exists for.
        assert priced.spread_total == 20000.0
        assert sum(e.spread for e in priced.items) == 0.0

        flags = boq_checks.run_checks(priced, bill)
        unallocated = [f for f in flags if f.kind == "spread_unallocated"]
        assert len(unallocated) == 1
        assert "20,000.00" in unallocated[0].message
        assert "no item in this bill has a build-up" in unallocated[0].message

    def test_a_fully_landed_pool_is_quiet(self):
        bill = _bill()
        priced = price_bill(bill, {"2.4": _build_up("2.4", 300000.0)}, rates=[],
                            spread=UnbilledSweep(costs=[
                                UnbilledCost(key="u", label=UNIFORM, amount=20000.0,
                                             route=ROUTE_SPREAD, decided_by="SW")]).spread_lines())
        assert [f for f in boq_checks.run_checks(priced, bill)
                if f.kind == "spread_unallocated"] == []

    def test_no_pool_at_all_is_not_a_flag(self):
        bill = _bill()
        priced = price_bill(bill, {"2.4": _build_up("2.4", 300000.0)}, rates=[])
        assert [f for f in boq_checks.run_checks(priced, bill)
                if f.kind == "spread_unallocated"] == []


# ---------------------------------------------------------------------------
# The same thing through the HTTP surface, which is where it was actually broken.
# ---------------------------------------------------------------------------
pytest.importorskip("openpyxl")


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


@pytest.fixture
def imported(client, tmp_path):
    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as handle:
        response = client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": (path.name, handle.read(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert response.status_code == 200, response.text
    return response.json()


def _a_priceable_ref(client) -> str:
    body = client.get(f"{BASE}/boq/{SET}").json()
    return next(i["full_ref"] for i in body["items"]
                if not i["is_parent"] and not i["pre_priced"] and i["qty"])


def _sweep_and_build(client, ref: str, *, pool: float = 20000.0, cost: float = 400000.0):
    assert client.post(f"{BASE}/price/sweep", headers={"X-CBOQ-Actor": "SW"}, json={
        "set_id": SET, "key": "uniform", "label": UNIFORM, "source": "PP 11/2A",
        "amount": pool, "route": "spread"}).status_code == 200
    assert client.post(f"{BASE}/boq/rate", headers={"X-CBOQ-Actor": "SW"}, json={
        "set_id": SET, "full_ref": ref,
        "build_up": _build_up(ref, cost).model_dump()}).status_code == 200


class TestTheHTTPSurfaceCarriesThePool:
    def test_the_priced_bill_now_carries_the_spread_lines(self, client, imported):
        ref = _a_priceable_ref(client)
        _sweep_and_build(client, ref)
        body = client.get(f"{BASE}/boq/{SET}/priced").json()
        assert body["spread_total"] == 20000.0
        assert [line["label"] for line in body["spread"]] == [UNIFORM]
        entry = next(i for i in body["items"] if i["full_ref"] == ref)
        assert entry["spread"] == pytest.approx(20000.0, abs=0.01)

    def test_the_trace_shows_the_share_instead_of_a_hard_coded_zero(self, client, imported):
        ref = _a_priceable_ref(client)
        _sweep_and_build(client, ref)
        trace = client.get(f"{BASE}/price/{SET}/trace/{ref}").json()["trace"]
        text = repr(trace)
        assert "spread share" in text, "trace.py hides the node when the share is falsy"
        assert "20000.0" in text or "20,000.00" in text

    def test_the_checks_endpoint_says_when_the_pool_reaches_nothing(self, client, imported):
        assert client.post(f"{BASE}/price/sweep", headers={"X-CBOQ-Actor": "SW"}, json={
            "set_id": SET, "key": "uniform", "label": UNIFORM, "amount": 20000.0,
            "route": "spread"}).status_code == 200
        body = client.get(f"{BASE}/boq/{SET}/checks").json()
        assert body["counts"].get("spread_unallocated") == 1

    def test_an_unswept_tender_prices_exactly_as_before(self, client, imported):
        # The closure must not move a number on a tender nobody has swept: an empty sweep is where
        # every tender starts.
        ref = _a_priceable_ref(client)
        assert client.post(f"{BASE}/boq/rate", headers={"X-CBOQ-Actor": "SW"}, json={
            "set_id": SET, "full_ref": ref,
            "build_up": _build_up(ref, 400000.0).model_dump()}).status_code == 200
        body = client.get(f"{BASE}/boq/{SET}/priced").json()
        assert body["spread_total"] == 0.0 and body["spread"] == []
        assert all(i["spread"] == 0.0 for i in body["items"])
        assert client.get(f"{BASE}/boq/{SET}/checks").json()["counts"].get(
            "spread_unallocated") is None
