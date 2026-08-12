"""A cost routed "load onto 2.2b" reaches item 2.2b — or says loudly why it cannot.

THE LEAK. `UnbilledSweep.loadings()` has been computed since the sweep existed and DISPLAYED by two
endpoints, and `price_bill` had no loadings parameter — so an estimator could route a HK$210,000
platform cost onto 2.2b, satisfy the settle gate (the app's ONLY hard stop), and ship a tender that
omits it. Same defect class as the spread pool closed before it: the screen shows the money as
handled, and no rate carries it.

WHERE A LOADING MAY LAND, and the three refusals — each a flag, never a silent drop:

* a BUILT item — the cost drives the rate, so the loading joins the cost and reaches the rate;
* a CARRIED item — priced from the rate, not the cost, so the loading cannot reach it without
  silently rewriting a figure somebody carried on purpose → `loading_unapplied`;
* an UNPRICED item — a rate made of the loading alone would price the item's own work at nothing,
  with the unpriced flag switched off by the very money meant to sit on top of it →
  `loading_unapplied`, and the unpriced flag still fires;
* a CLIENT-PRICED item — GCT App C 2.2(vi) reinstates the client's figure at examination, so money
  loaded there is thrown away → `loading_unapplied`;
* a MISSING item — a revision renamed it and the routing was not moved → `loading_unapplied`.

And the sibling guard: the platform cost typed on the Site groups
(`HoleGroup.access_build_cost`), summed by `access_build_total()` — which had ZERO production
callers — now flags on the checks surface until the per-class rig-move basis carries it
(SMM S02 ¶2.08(h): access scaffolding is in the moving-rigs item coverage).
"""

from __future__ import annotations

import pytest

from client_boq.boq import checks as boq_checks
from client_boq.boq.pricing import price_bill
from client_boq.models import BillItem, ClientBill, ResourceLine, ScheduleItem

SET = "technopole-gi"


def _bill(*items: BillItem) -> ClientBill:
    return ClientBill(set_id=SET, rev=0, items=list(items))


def _item(ref, qty, unit="m", **kw):
    return BillItem(bill_no=ref.split(".")[0], full_ref=ref, description=ref, qty=qty,
                    unit=unit, **kw)


def _build_up(ref: str, amount: float) -> ScheduleItem:
    return ScheduleItem(item_id=ref, description=ref, category="direct", unit="sum",
                        lines=[ResourceLine(description=ref, inline_rate=amount, qty=1.0)])


class TestALoadingLandsOnABuiltItem:
    def test_the_loading_is_inside_the_cost_and_the_rate(self):
        bill = _bill(_item("2.2b", 11.0, "nr"))
        priced = price_bill(bill, {"2.2b": _build_up("2.2b", 110000.0)}, rates=[],
                            loadings={"2.2b": 210000.0})
        entry = priced.items[0]
        assert entry.loading == 210000.0
        assert entry.cost == pytest.approx(320000.0)
        assert entry.unit_rate == pytest.approx(320000.0 / 11.0, abs=0.01)
        assert priced.loading_total == 210000.0
        assert [f for f in priced.flags if f.kind == "loading_unapplied"] == []

    def test_the_tendered_total_moves_by_exactly_the_loading(self):
        bill = _bill(_item("2.2b", 11.0, "nr"))
        without = price_bill(bill, {"2.2b": _build_up("2.2b", 110000.0)}, rates=[])
        with_load = price_bill(bill, {"2.2b": _build_up("2.2b", 110000.0)}, rates=[],
                               loadings={"2.2b": 210000.0})
        assert with_load.tendered_total - without.tendered_total == pytest.approx(
            210000.0, abs=0.06)

    def test_no_loadings_prices_exactly_as_before(self):
        bill = _bill(_item("2.4", 2300.0))
        a = price_bill(bill, {"2.4": _build_up("2.4", 300000.0)}, rates=[])
        b = price_bill(bill, {"2.4": _build_up("2.4", 300000.0)}, rates=[], loadings={})
        assert a.model_dump() == b.model_dump()


class TestTheThreeRefusals:
    def test_a_loading_on_a_carried_rate_is_flagged_not_silently_lost(self):
        bill = _bill(_item("2.2b", 11.0, "nr"))
        priced = price_bill(bill, {}, rates=[], carried={"2.2b": 5000.0},
                            loadings={"2.2b": 210000.0})
        entry = priced.items[0]
        assert entry.loading == 0.0, "a carried rate cannot carry it, so it must not claim to"
        assert entry.amount == pytest.approx(55000.0), "the carried rate itself is untouched"
        flags = [f for f in priced.flags if f.kind == "loading_unapplied"]
        assert len(flags) == 1 and "carried rate" in flags[0].message

    def test_a_loading_on_an_unpriced_item_does_not_switch_off_the_unpriced_flag(self):
        """The nastiest shape: the loading alone would give the item a rate, the unpriced flag
        would stop firing, and the item's own work would be priced at nothing — silently."""
        bill = _bill(_item("2.2b", 11.0, "nr"))
        priced = price_bill(bill, {}, rates=[], loadings={"2.2b": 210000.0})
        entry = priced.items[0]
        assert entry.unit_rate is None and entry.amount == 0.0
        kinds = sorted(f.kind for f in priced.flags)
        assert "loading_unapplied" in kinds, "the routed money must be named"
        assert "unpriced_item" in kinds, "and the item is still unpriced"

    def test_a_loading_on_a_client_priced_item_is_refused_with_the_clause(self):
        bill = _bill(_item("9.1", 1.0, "item", lump=True, pre_priced=True,
                           client_rate=429810.0, client_amount=429810.0))
        priced = price_bill(bill, {}, rates=[], loadings={"9.1": 50000.0})
        entry = priced.items[0]
        assert entry.amount == 429810.0, "the client's figure is untouched"
        flags = [f for f in priced.flags if f.kind == "loading_unapplied"]
        assert len(flags) == 1 and "2.2(vi)" in flags[0].message

    def test_a_loading_on_an_item_the_bill_no_longer_has_is_named(self):
        """Class 2 — written under one identity, read under another. A revision renamed the item
        and the routing was not moved with it."""
        bill = _bill(_item("2.4", 2300.0))
        priced = price_bill(bill, {"2.4": _build_up("2.4", 300000.0)}, rates=[],
                            loadings={"2.2x": 75000.0})
        flags = [f for f in priced.flags if f.kind == "loading_unapplied"]
        assert len(flags) == 1
        assert "2.2x" in flags[0].message and "no item" in flags[0].message
        assert priced.loading_total == 0.0

    def test_a_zero_loading_raises_no_flag(self):
        bill = _bill(_item("2.4", 2300.0))
        priced = price_bill(bill, {"2.4": _build_up("2.4", 300000.0)}, rates=[],
                            loadings={"2.4": 0.0, "gone": 0.0})
        assert [f for f in priced.flags if f.kind == "loading_unapplied"] == []


class TestThePlatformCostGuard:
    def test_a_typed_platform_cost_nobody_consumes_is_flagged_with_the_clause(self):
        flags = boq_checks.platform_cost_unconsumed(120000.0)
        assert len(flags) == 1
        assert "120,000.00" in flags[0].message
        assert "2.08(h)" in flags[0].message
        assert flags[0].kind == "platform_cost_unconsumed"

    def test_no_platform_cost_is_quiet(self):
        assert boq_checks.platform_cost_unconsumed(0.0) == []


class TestTheGuardReachesTheChecksSurface:
    """Through the endpoint, because the flag has a data dependency the pure module cannot see."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
        pytest.importorskip("openpyxl")
        from api import app

        return TestClient(app)

    def test_platform_money_typed_on_a_group_reaches_the_checks(self, client, tmp_path):
        from client_boq.tests._bqfixture import build_bill_workbook

        path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
        with open(path, "rb") as fh:
            assert client.post(
                "/client-boq/boq/import", data={"set_id": SET},
                files={"file": (path.name, fh.read(), "application/vnd.ms-excel")},
            ).status_code == 200
        assert client.post(
            "/client-boq/site/group", headers={"X-CBOQ-Actor": "SW"},
            json={"set_id": SET, "group_id": "hillside",
                  "group": {"label": "Hillside", "stations": ["A1"], "access_class": "B",
                            "access_build_cost": 120000.0}},
        ).status_code == 200
        body = client.get(f"/client-boq/boq/{SET}/checks").json()
        assert body["counts"].get("platform_cost_unconsumed") == 1

    def test_a_routed_loading_reaches_the_priced_bill_end_to_end(self, client, tmp_path):
        from client_boq.tests._bqfixture import build_bill_workbook
        from client_boq.models import ResourceLine, ScheduleItem

        path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
        with open(path, "rb") as fh:
            client.post("/client-boq/boq/import", data={"set_id": SET},
                        files={"file": (path.name, fh.read(), "application/vnd.ms-excel")})
        ref = next(i["full_ref"] for i in client.get(f"/client-boq/boq/{SET}").json()["items"]
                   if not i["is_parent"] and not i["pre_priced"] and i["qty"])
        build = ScheduleItem(item_id=ref, description=ref, category="direct", unit="sum",
                             lines=[ResourceLine(description=ref, inline_rate=100000.0, qty=1.0)])
        assert client.post("/client-boq/boq/rate", headers={"X-CBOQ-Actor": "SW"},
                           json={"set_id": SET, "full_ref": ref,
                                 "build_up": build.model_dump()}).status_code == 200
        assert client.post("/client-boq/price/sweep", headers={"X-CBOQ-Actor": "SW"},
                           json={"set_id": SET, "key": "platforms", "label": "Class B platforms",
                                 "amount": 50000.0, "route": "load",
                                 "target_ref": ref}).status_code == 200
        body = client.get(f"/client-boq/boq/{SET}/priced").json()
        entry = next(i for i in body["items"] if i["full_ref"] == ref)
        assert entry["loading"] == 50000.0
        assert body["loading_total"] == 50000.0
