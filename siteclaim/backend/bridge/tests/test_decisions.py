"""Phase 6 — the fork is re-pointed: decisions are recorded, and NOTHING is seeded.

The procurement /route/confirm seeds one estimate_projects row per self-perform package. That is
the wrong destination for a client_boq tender: client_boq_estimates is keyed by set_id — ONE
estimate per tender — and that is correct. A main contractor submits one priced bill with a single
tendered total; every item on it is priced. The route decision changes only where each item's RATE
comes from, never which items appear. Seeding N estimates would create N documents where the
tender needs one.
"""

import pytest
from fastapi.testclient import TestClient

from bridge import decisions, scope as scope_mod
from bridge.identity import bridge_conn
from schemas.models import ScopePackages, SorItem, TradeWorkPackage


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _scope() -> ScopePackages:
    return ScopePackages(project_name="GE/2026/14", packages=[
        TradeWorkPackage(trade="foundation_substructure", scope_summary="Bored piling", sor_items=[
            SorItem(item_ref="G1", description="Bored piling", unit="m", qty=100.0, section="G"),
        ]),
        TradeWorkPackage(trade="electrical", scope_summary="LV distribution", sor_items=[
            SorItem(item_ref="E1", description="LV switchboard", unit="nr", qty=2.0, section="E"),
        ]),
    ])


@pytest.fixture
def proposed(make_set, part_spec):
    """An approved, scoped, analysed set — ready for a route decision."""
    def _build(*, approved: bool = True):
        make_set("ge-2026-14", "Contract No. GE/2026/14",
                 [part_spec(1, "SR", "Schedule of Rates", "pricing")],
                 review_approved=True)
        conn = bridge_conn()
        try:
            scope_mod.save_scope_on(conn, "ge-2026-14", _scope())
        finally:
            conn.close()
        decisions.propose_routes("ge-2026-14")
        if not approved:
            from client_boq import store as cb_store

            conn = bridge_conn()
            try:
                cb_store.set_review_approved(conn, "ge-2026-14", False)
            finally:
                conn.close()
        return "ge-2026-14"

    return _build


def _estimate_project_count(conn) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name='estimate_projects'"
    ).fetchone()
    if not row["n"]:
        return 0                      # the table was never even created
    return conn.execute("SELECT COUNT(*) AS n FROM estimate_projects").fetchone()["n"]


# -- the point of the phase ----------------------------------------------------------------------
def test_the_bridge_path_writes_no_row_to_estimate_projects(proposed):
    set_id = proposed()
    decisions.confirm_routes(set_id, {
        "foundation_substructure": "self_perform",     # the route that WOULD seed on the other path
        "electrical": "sublet",
    })

    conn = bridge_conn()
    try:
        assert _estimate_project_count(conn) == 0      # nothing seeded, by either engine
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name='client_boq_estimates'"
        ).fetchone()["n"] == 0 or conn.execute(
            "SELECT COUNT(*) AS n FROM client_boq_estimates"
        ).fetchone()["n"] == 0                          # ...and none on the client_boq side either
    finally:
        conn.close()


def test_the_procurement_confirm_endpoint_is_untouched():
    # Ruling 4: nothing to change. It seeds only when a scope is supplied, and the bridge never
    # calls it, so the standalone path keeps working exactly as it does today.
    import inspect

    import api

    assert "/route/confirm" in api.app.openapi()["paths"]
    source = inspect.getsource(api.post_route_confirm)
    assert "if req.scope is not None:" in source        # the conditional that makes seeding opt-in
    assert "_seed_estimate" in source                    # still seeds for the standalone path


# -- validation ----------------------------------------------------------------------------------
def test_decisions_persist_and_split_correctly(proposed):
    set_id = proposed()
    body = decisions.confirm_routes(set_id, {
        "foundation_substructure": "self_perform", "electrical": "sublet",
    })

    assert body["self_perform_packages"] == ["foundation_substructure"]
    assert body["sublet_packages"] == ["electrical"]
    assert body["run_ref"] == set_id == body["set_id"]

    conn = bridge_conn()
    try:
        stored = decisions.load_decisions(conn, set_id)
    finally:
        conn.close()
    assert {d["package_key"]: d["chosen_route"] for d in stored} == {
        "foundation_substructure": "self_perform", "electrical": "sublet",
    }


def test_an_unknown_route_is_rejected_before_anything_is_written(proposed):
    set_id = proposed()
    with pytest.raises(ValueError, match="unknown route"):
        decisions.confirm_routes(set_id, {
            "foundation_substructure": "self_perform",   # valid
            "electrical": "outsource_to_mars",           # not
        })

    conn = bridge_conn()
    try:
        assert decisions.load_decisions(conn, set_id) == []   # all-or-nothing
    finally:
        conn.close()


def test_a_decision_for_an_unproposed_package_is_rejected(proposed):
    # package_routes has no UNIQUE and silently updates zero rows for an unknown key. This table
    # would happily INSERT one, so it validates instead.
    set_id = proposed()
    with pytest.raises(ValueError, match="Unknown package_key"):
        decisions.confirm_routes(set_id, {"plumbing": "sublet"})

    conn = bridge_conn()
    try:
        assert decisions.load_decisions(conn, set_id) == []
    finally:
        conn.close()


def test_an_empty_confirmation_is_refused(proposed):
    set_id = proposed()
    with pytest.raises(ValueError, match="at least one package"):
        decisions.confirm_routes(set_id, {})


def test_confirming_before_any_proposal_says_so(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "SR", "Schedule of Rates", "pricing")],
             review_approved=True)
    with pytest.raises(LookupError, match="No route proposal"):
        decisions.confirm_routes("ge-2026-14", {"electrical": "sublet"})


def test_redeciding_a_package_updates_in_place(proposed):
    set_id = proposed()
    decisions.confirm_routes(set_id, {"electrical": "sublet"})
    body = decisions.confirm_routes(set_id, {"electrical": "self_perform"})

    assert body["self_perform_packages"] == ["electrical"] and body["sublet_packages"] == []
    conn = bridge_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM bridge_route_decisions WHERE set_id = ?", (set_id,)
        ).fetchone()["n"]
        assert n == 1                                     # UNIQUE(set_id, package_key) holds
    finally:
        conn.close()


def test_confirming_is_behind_the_same_review_gate(proposed):
    # A gate that only covered the advisory step would be bypassed by posting straight here.
    set_id = proposed(approved=False)
    with pytest.raises(decisions.ReviewNotApproved):
        decisions.confirm_routes(set_id, {"electrical": "sublet"})


def test_the_bridge_does_not_write_package_routes_chosen_route(proposed):
    # /route/confirm keeps its role as the sole writer of chosen_route; the bridge records its
    # decisions in its OWN table so the two never contend for that column.
    from db import routing

    set_id = proposed()
    decisions.confirm_routes(set_id, {"electrical": "sublet"})

    conn = bridge_conn()
    try:
        assert all(p["chosen_route"] is None for p in routing.read_proposal(conn, set_id))
    finally:
        conn.close()


# -- the endpoint ---------------------------------------------------------------------------------
def test_the_confirm_endpoint_returns_the_splits(client, proposed):
    set_id = proposed()
    resp = client.post(f"/bridge/{set_id}/route/confirm", json={"decisions": [
        {"package_key": "foundation_substructure", "chosen_route": "self_perform"},
        {"package_key": "electrical", "chosen_route": "sublet"},
    ]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["self_perform_packages"] == ["foundation_substructure"]
    assert body["sublet_packages"] == ["electrical"]


def test_the_confirm_endpoint_maps_its_errors(client, proposed):
    set_id = proposed()

    bad_route = client.post(f"/bridge/{set_id}/route/confirm", json={"decisions": [
        {"package_key": "electrical", "chosen_route": "nope"}]})
    assert bad_route.status_code == 400

    bad_key = client.post(f"/bridge/{set_id}/route/confirm", json={"decisions": [
        {"package_key": "plumbing", "chosen_route": "sublet"}]})
    assert bad_key.status_code == 400 and "Unknown package_key" in bad_key.json()["detail"]

    no_proposal = client.post("/bridge/never-analysed/route/confirm", json={"decisions": [
        {"package_key": "electrical", "chosen_route": "sublet"}]})
    assert no_proposal.status_code == 409   # unreviewed set is refused at the gate first


# -- the whole spine ------------------------------------------------------------------------------
def test_one_tender_travels_the_whole_spine(client, make_set, part_spec, monkeypatch, tmp_path):
    """Approved review -> bill confirmation -> scope split -> route proposal -> route decision."""
    import fitz

    from bridge import parts as parts_mod

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 80), "SECTION G: PILING", fontsize=11)
    page.insert_text((60, 96), "G1 Bored piling 600mm m 100", fontsize=11)
    bill = tmp_path / "bill.pdf"
    doc.save(str(bill))
    doc.close()

    make_set("ge-2026-14", "Contract No. GE/2026/14", [
        part_spec(1, "SR", "Schedule of Rates", "pricing"),
        part_spec(2, "PS", "Particular Specification", "specifications"),
    ], pdf_paths={"01-sr": str(bill)}, review_approved=True)

    # 1. the human confirms which part is the priced bill
    confirmed = client.post("/bridge/ge-2026-14/bq-part", json={"part_ids": ["01-sr"]})
    assert confirmed.status_code == 200 and confirmed.json()["confirmed"] == ["01-sr"]

    # 2. the split (Layer 2 stubbed — offline)
    monkeypatch.setattr(scope_mod, "ingest_tender", lambda *a, **k: _scope())
    assert client.post("/bridge/ge-2026-14/scope").status_code == 200

    # 3. the proposal, behind the review gate
    proposal = client.post("/bridge/ge-2026-14/route/analyze")
    assert proposal.status_code == 200
    keys = [p["package_key"] for p in proposal.json()["packages"]]

    # 4. the decision — and nothing seeded
    confirm = client.post("/bridge/ge-2026-14/route/confirm", json={"decisions": [
        {"package_key": k, "chosen_route": "self_perform"} for k in keys]})
    assert confirm.status_code == 200
    assert sorted(confirm.json()["self_perform_packages"]) == sorted(keys)

    conn = bridge_conn()
    try:
        assert _estimate_project_count(conn) == 0
    finally:
        conn.close()
    assert parts_mod.bq_candidates("ge-2026-14")["confirmed"] == ["01-sr"]
