"""Node 43: one tender total from two engines, every gap and double-count named.

The offer's price was only the self-perform estimate; the awards Track A produced lived in React
state and died with the tab. This pins the seam: the award is persisted (a Layer-4 record), the
composition excludes sublet items from the self-perform sum BY CONSTRUCTION (a double-count is
impossible, not merely checked-for), a sublet package with no award is a NAMED gap — never quietly
carried at the estimate's numbers — and fork 5's normalisation questions ride on the payload so the
raw figure cannot read as settled.
"""

import pytest

from bridge import award, combine, decisions, scope as scope_mod
from bridge.identity import bridge_conn
from db import routing
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

SET = "nd-2025-04"


# -- the pure composition ----------------------------------------------------------------------
def _priced(**amounts):
    return [{"full_ref": ref, "amount": amount} for ref, amount in amounts.items()]


def _units(**items):
    return [{"package_key": key, "item_refs": refs} for key, refs in items.items()]


def test_the_two_sides_sum_and_the_sublet_items_are_excluded_by_construction():
    result = combine.compose(
        SET,
        priced_rows=_priced(**{"1.1": 1000.0, "2.1": 500.0, "2.2": 700.0, "3.1": 300.0}),
        units=_units(**{"gi:1": ["1.1"], "gi:2": ["2.1", "2.2"], "gi:3": ["3.1"]}),
        sublet_packages=["gi:2"], self_perform_packages=["gi:1", "gi:3"],
        awards=[{"package_key": "gi:2", "firm_id": "f1", "firm_name": "Sun Fat Drilling",
                 "total": 950.0}])

    assert result.self_perform_total == pytest.approx(1300.0)
    assert result.sublet_total == pytest.approx(950.0)
    assert result.combined_total == pytest.approx(2250.0)
    assert result.gaps == [] and result.double_counts == []
    # the displaced estimate is SHOWN beside the award, not added to it
    sublet_line = next(l for l in result.lines if l.package_key == "gi:2")
    assert sublet_line.displaced_estimate == pytest.approx(1200.0)
    assert result.displaced_estimate_total == pytest.approx(1200.0)


def test_a_sublet_package_with_no_award_is_a_named_gap_not_an_estimate_number():
    result = combine.compose(
        SET, priced_rows=_priced(**{"1.1": 1000.0, "2.1": 500.0}),
        units=_units(**{"gi:1": ["1.1"], "gi:2": ["2.1"]}),
        sublet_packages=["gi:2"], self_perform_packages=["gi:1"], awards=[])

    assert any("gi:2" in g and "NO recorded award" in g for g in result.gaps)
    assert result.sublet_total is None, "a column of pure gaps is not $0 of subcontract"
    assert result.combined_total == pytest.approx(1000.0), "the floor excludes the gap"
    assert any("floor" in n for n in result.notes)


def test_an_award_whose_package_is_no_longer_sublet_is_a_named_double_count():
    """A stale award beside the estimate's own pricing of the same items IS the double-count —
    named and not counted, with the way out stated."""
    result = combine.compose(
        SET, priced_rows=_priced(**{"1.1": 1000.0}),
        units=_units(**{"gi:1": ["1.1"]}),
        sublet_packages=[], self_perform_packages=["gi:1"],
        awards=[{"package_key": "gi:1", "firm_id": "f1", "firm_name": "Sun Fat", "total": 900.0}])

    assert len(result.double_counts) == 1
    assert "not counted" in result.double_counts[0]
    assert result.combined_total == pytest.approx(1000.0), "the estimate's side, once"


def test_an_award_with_no_total_is_a_gap_with_the_firm_named():
    result = combine.compose(
        SET, priced_rows=_priced(**{"2.1": 500.0}), units=_units(**{"gi:2": ["2.1"]}),
        sublet_packages=["gi:2"], self_perform_packages=[],
        awards=[{"package_key": "gi:2", "firm_id": "f1", "firm_name": "Sun Fat", "total": None}])

    assert any("no total recorded" in g and "Sun Fat" in g for g in result.gaps)
    assert result.combined_total == pytest.approx(0.0)


def test_unrouted_items_count_self_perform_by_default_and_are_named():
    result = combine.compose(
        SET, priced_rows=_priced(**{"1.1": 100.0, "9.9": 60.0}),
        units=_units(**{"gi:1": ["1.1"]}),
        sublet_packages=[], self_perform_packages=["gi:1"], awards=[])

    assert result.unrouted_items == 1
    assert result.self_perform_total == pytest.approx(160.0)
    assert any("no routed package" in n for n in result.notes)


def test_a_self_perform_package_with_unpriced_items_is_under_priced_and_says_so():
    result = combine.compose(
        SET, priced_rows=_priced(**{"1.1": 100.0, "1.2": None}),
        units=_units(**{"gi:1": ["1.1", "1.2"]}),
        sublet_packages=[], self_perform_packages=["gi:1"], awards=[])

    assert any("1.2" in g and "no amount" in g for g in result.gaps)


def test_no_routing_at_all_is_simply_the_priced_bill():
    result = combine.compose(SET, priced_rows=_priced(**{"1.1": 100.0}), units=[],
                             sublet_packages=[], self_perform_packages=[], awards=[])
    assert result.routed is False
    assert result.combined_total == pytest.approx(100.0)
    assert any("whole bill reads self-perform" in n for n in result.notes)


def test_fork_fives_questions_ride_on_every_payload():
    result = combine.compose(SET, priced_rows=[], units=[], sublet_packages=[],
                             self_perform_packages=[], awards=[])
    joined = " ".join(result.open_questions)
    for word in ("GST", "Mobilisation", "Preliminaries"):
        assert word in joined


def test_the_letter_price_difference_is_named_never_rewritten():
    result = combine.compose(
        SET, priced_rows=_priced(**{"1.1": 1000.0}), units=_units(**{"gi:1": ["1.1"]}),
        sublet_packages=[], self_perform_packages=["gi:1"], awards=[], letter_price=800.0)
    assert any("+200.00" in n and "nothing rewrites the letter" in n for n in result.notes)


# -- the award store ---------------------------------------------------------------------------------
def _route(sublet=("gi:2",), self_perform=("gi:1",)):
    """Stand a confirmed routing up through the real stores."""
    from client_boq import store as cb_store

    conn = bridge_conn()
    try:
        cb_store.upsert_document_set(conn, set_id=SET, name="ND/2025/04", slug=SET,
                                     status="reviewed")
        cb_store.set_review_approved(conn, SET, True)
        routing.write_proposal(conn, SET, [
            {"package_key": key, "trade": key.split(":")[0], "recommended_route": "sublet"}
            for key in (*sublet, *self_perform)])
    finally:
        conn.close()
    decisions.confirm_routes(SET, {**{k: "sublet" for k in sublet},
                                   **{k: "self_perform" for k in self_perform}})


def test_an_award_is_recorded_for_a_sublet_package():
    _route()
    record = award.record_award(SET, "gi:2", "f1", "Sun Fat Drilling", 950_000.0,
                                decided_by="R. Lam")
    assert record["firm_name"] == "Sun Fat Drilling" and record["total"] == 950_000.0
    assert award.load_awards(SET)[0]["package_key"] == "gi:2"


def test_re_awarding_replaces_in_place():
    _route()
    award.record_award(SET, "gi:2", "f1", "Sun Fat", 950_000.0)
    award.record_award(SET, "gi:2", "f2", "Golden Base", 920_000.0)
    records = award.load_awards(SET)
    assert len(records) == 1 and records[0]["firm_id"] == "f2"


def test_a_self_perform_package_refuses_an_award():
    """The double-count front door: the estimate prices that side."""
    _route()
    with pytest.raises(ValueError, match="SELF-PERFORM"):
        award.record_award(SET, "gi:1", "f1", "Sun Fat", 100.0)


def test_an_unrouted_package_refuses_an_award():
    _route()
    with pytest.raises(ValueError, match="no confirmed sublet route"):
        award.record_award(SET, "gi:9", "f1", "Sun Fat", 100.0)


def test_clearing_an_award_is_idempotent():
    _route()
    award.record_award(SET, "gi:2", "f1", "Sun Fat", 1.0)
    assert award.clear_award(SET, "gi:2") is True
    assert award.clear_award(SET, "gi:2") is False
    assert award.load_awards(SET) == []


# -- the loader end to end ---------------------------------------------------------------------------
def test_combined_pricing_reads_the_real_stores(tmp_path, monkeypatch):
    """Route two packages, award one, and the combined read composes the persisted split with the
    persisted award — no React state anywhere."""
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    _route()
    conn = bridge_conn()
    try:
        scope_mod.save_scope_on(conn, SET, ScopePackages(project_name="ND/2025/04", packages=[
            TradeWorkPackage(trade="gi", scope_summary="GI", sor_items=[
                SorItem(item_ref="1.1", description="prelims", section="1"),
                SorItem(item_ref="2.1", description="drilling", section="2"),
            ], sections=[SectionMeta(code="1", title="Bill 1", item_count=1),
                         SectionMeta(code="2", title="Bill 2", item_count=1)]),
        ]))
    finally:
        conn.close()
    award.record_award(SET, "gi:2", "f1", "Sun Fat Drilling", 777.0)

    result = combine.combined_pricing(SET)
    sublet = next(l for l in result.lines if l.package_key == "gi:2")

    assert sublet.amount == 777.0 and sublet.firm_name == "Sun Fat Drilling"
    assert result.sublet_total == pytest.approx(777.0)
    assert any("no priced bill" in n for n in result.notes), \
        "no bill imported: the self-perform side says so instead of pretending"


def test_the_endpoint_serves_the_composition(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    client = TestClient(app)
    _route()
    award.record_award(SET, "gi:2", "f1", "Sun Fat", 500.0)

    body = client.get(f"/bridge/{SET}/combined-pricing").json()
    assert body["sublet_total"] == 500.0
    assert body["open_questions"], "fork 5 rides on the wire"

    posted = client.post(f"/bridge/{SET}/award", json={
        "package_key": "gi:1", "firm_id": "f9"})
    assert posted.status_code == 400 and "SELF-PERFORM" in posted.json()["detail"]
