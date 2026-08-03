"""Phase 5 — routing sits BEHIND the review gate, and both forks inherit it.

You cannot decide self-perform vs sublet without knowing the contract terms, and you should not
send an RFQ on terms nobody has read. One gate, one place.

An OPEN QUERY is deliberately not a gate: client_boq's locked decision 8 is that an unanswered
question does not stop pricing, because the submission deadline does not move because the client
has not replied. The count is shown; it never refuses.
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
            SorItem(item_ref="G1", description="Bored piling 600mm", unit="m", qty=100.0, section="G"),
        ]),
        TradeWorkPackage(trade="electrical", scope_summary="LV distribution", sor_items=[
            SorItem(item_ref="E1", description="LV switchboard", unit="nr", qty=2.0, section="E"),
        ]),
    ])


@pytest.fixture
def routable(make_set, part_spec):
    """A set with a persisted scope split. Review approval is left to each test."""
    def _build(*, approved: bool, open_queries: int = 0):
        make_set("ge-2026-14", "Contract No. GE/2026/14",
                 [part_spec(1, "SR", "Schedule of Rates", "pricing")],
                 review_approved=approved)
        conn = bridge_conn()
        try:
            scope_mod.save_scope_on(conn, "ge-2026-14", _scope())
            if open_queries:
                from client_boq import store as cb_store
                from client_boq.models import RFIItem

                for i in range(open_queries):
                    cb_store.save_rfi(conn, "ge-2026-14", RFIItem(
                        rfi_id=f"q{i}", question="Which standard governs the piling tolerance?",
                    ))
        finally:
            conn.close()
        return "ge-2026-14"

    return _build


@pytest.fixture
def seeded_firms(monkeypatch, tmp_path):
    """A real firm register in the test DB, so package_signal has something to count."""
    import os

    from db import seed

    seed.build_database(os.environ["SITESOURCE_DB"])
    return True


# -- the gate ----------------------------------------------------------------------------------
def test_an_unapproved_review_refuses_and_names_the_gate(routable):
    set_id = routable(approved=False)
    with pytest.raises(decisions.ReviewNotApproved) as exc:
        decisions.propose_routes(set_id)

    message = str(exc.value)
    assert "not approved" in message
    assert "/client-boq/review/approve" in message          # says exactly how to clear it
    assert "should not send an RFQ on terms nobody has read" in message  # and why the gate exists


def test_a_set_with_no_review_row_at_all_is_also_refused(make_set, part_spec):
    # review_is_approved returns False for a missing row, and "never reviewed" must be refused
    # exactly like "reviewed and not approved".
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "SR", "Schedule of Rates", "pricing")])
    with pytest.raises(decisions.ReviewNotApproved):
        decisions.propose_routes("ge-2026-14")


def test_an_approved_review_yields_a_proposal(routable, seeded_firms):
    set_id = routable(approved=True)
    body = decisions.propose_routes(set_id)

    assert body["run_ref"] == set_id == body["set_id"]        # set_id IS the run_ref
    keys = {p["package_key"] for p in body["packages"]}
    assert keys == {"foundation_substructure", "electrical"}  # one unit per package, unsplit
    for pkg in body["packages"]:
        assert pkg["recommended_route"] in ("self_perform", "sublet")
        assert pkg["chosen_route"] is None                    # advisory until a human decides
    assert body["open_queries"] == 0


def test_the_proposal_is_persisted_under_the_set_id_as_run_ref(routable, seeded_firms):
    from db import routing

    set_id = routable(approved=True)
    decisions.propose_routes(set_id)

    conn = bridge_conn()
    try:
        stored = routing.read_proposal(conn, set_id)
    finally:
        conn.close()
    assert {p["package_key"] for p in stored} == {"foundation_substructure", "electrical"}


def test_the_signal_is_read_from_the_firm_register(routable, seeded_firms):
    set_id = routable(approved=True)
    body = decisions.propose_routes(set_id)

    electrical = next(p for p in body["packages"] if p["package_key"] == "electrical")
    assert electrical["signals"]["trade"] == "electrical"
    assert electrical["signals"]["trade_firm_count"] > 0      # real coverage data behind the advice


def test_without_a_firm_register_the_signal_degrades_loudly(routable):
    # The test DB has no `firms` table. A recommendation made with no coverage data must never be
    # mistakable for one made with it.
    set_id = routable(approved=True)
    notes: list[str] = []

    body = decisions.propose_routes(set_id, on_error=notes.append)

    assert all(p["signals"] == {} for p in body["packages"])
    assert any("no firm register" in n and "deterministic fallback" in n for n in notes)
    assert body["packages"]                                    # it still proposes, it does not fail


# -- an open query never blocks ------------------------------------------------------------------
def test_open_queries_are_visible_but_never_refuse(routable, seeded_firms):
    set_id = routable(approved=True, open_queries=3)
    notes: list[str] = []

    body = decisions.propose_routes(set_id, on_error=notes.append)

    assert body["open_queries"] == 3                           # visible
    assert len(body["packages"]) == 2                           # and it routed anyway
    assert any("not blocking" in n for n in notes)


# -- prerequisites ------------------------------------------------------------------------------
def test_without_a_scope_split_it_says_so(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "SR", "Schedule of Rates", "pricing")],
             review_approved=True)
    with pytest.raises(LookupError, match="No scope split stored"):
        decisions.propose_routes("ge-2026-14")


# -- the endpoint --------------------------------------------------------------------------------
def test_the_analyze_endpoint_409s_until_the_review_is_approved(client, routable):
    set_id = routable(approved=False)
    resp = client.post(f"/bridge/{set_id}/route/analyze")

    assert resp.status_code == 409
    assert "/client-boq/review/approve" in resp.json()["detail"]


def test_the_analyze_endpoint_returns_the_proposal_once_approved(client, routable, seeded_firms):
    set_id = routable(approved=True, open_queries=1)
    resp = client.post(f"/bridge/{set_id}/route/analyze")

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_ref"] == set_id
    assert {p["package_key"] for p in body["packages"]} == {"foundation_substructure", "electrical"}
    assert body["open_queries"] == 1                           # carried, never a refusal
    assert isinstance(body["notes"], list)


def test_the_analyze_endpoint_404s_without_a_scope(client, make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "SR", "Schedule of Rates", "pricing")],
             review_approved=True)
    resp = client.post("/bridge/ge-2026-14/route/analyze")
    assert resp.status_code == 404 and "scope" in resp.json()["detail"]


def test_the_existing_procurement_analyze_is_untouched(client):
    # The bridge adds a path; it does not change the standalone one.
    import api

    assert "/route/analyze" in api.app.openapi()["paths"]
    assert "/bridge/{set_id}/route/analyze" in api.app.openapi()["paths"]
