"""The two read-only endpoints the step chips depend on.

The spine specified every write and no reads, so a UI could not tell whether a proposal or a
decision existed without POSTing — which is a write and, live, a model call. These are pure reads,
and "not yet run" is a STATE: an empty result, never a 404.
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
def analysed(make_set, part_spec):
    """An approved set with a split and a proposal."""
    make_set("ge-2026-14", "Contract No. GE/2026/14",
             [part_spec(1, "SR", "Schedule of Rates", "pricing")], review_approved=True)
    conn = bridge_conn()
    try:
        scope_mod.save_scope_on(conn, "ge-2026-14", _scope())
    finally:
        conn.close()
    decisions.propose_routes("ge-2026-14")
    return "ge-2026-14"


# -- not yet run is a state, not an error ------------------------------------------------------
def test_an_unanalysed_set_reads_back_empty_not_404(client):
    resp = client.get("/bridge/never-touched/route/proposal")
    assert resp.status_code == 200                       # never a 404
    body = resp.json()
    assert body["packages"] == [] and body["run_ref"] == "never-touched"
    assert body["review_approved"] is False and body["has_split"] is False


def test_a_set_with_no_decisions_reads_back_empty_not_404(client):
    resp = client.get("/bridge/never-touched/route/decisions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["decisions"] == []
    assert body["self_perform_packages"] == [] and body["sublet_packages"] == []


def test_reading_decisions_does_not_create_the_table(make_set, part_spec):
    # A GET must not write. load_decisions is deliberately table-tolerant rather than calling
    # ensure_tables, so a read that lands before any decision leaves no DDL behind.
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "SR", "Schedule of Rates", "pricing")])
    decisions.stored_decisions("ge-2026-14")

    conn = bridge_conn()
    try:
        assert decisions._table_exists(conn, "bridge_route_decisions") is False
    finally:
        conn.close()


# -- reading back what was written --------------------------------------------------------------
def test_the_proposal_reads_back_with_its_section_headings(client, analysed):
    resp = client.get(f"/bridge/{analysed}/route/proposal")
    assert resp.status_code == 200
    body = resp.json()

    keys = {p["package_key"] for p in body["packages"]}
    assert keys == {"foundation_substructure", "electrical"}
    for pkg in body["packages"]:
        assert pkg["recommended_route"] in ("self_perform", "sublet")
        assert pkg["chosen_route"] is None               # advisory until a human decides
        assert "section" in pkg and "section_title" in pkg   # recovered from the split
    assert body["review_approved"] is True and body["has_split"] is True
    assert body["open_queries"] == 0


def test_reading_the_proposal_never_re_runs_the_analysis(client, analysed, monkeypatch):
    # The chips read this on every render. If it re-proposed, it would rewrite package_routes and,
    # live, call the model.
    from db import routing

    def _boom(*_a, **_k):
        raise AssertionError("the read re-ran the analysis")

    monkeypatch.setattr(routing, "write_proposal", _boom)
    monkeypatch.setattr("pipeline.routing.recommend.recommend_routes", _boom)

    assert client.get(f"/bridge/{analysed}/route/proposal").status_code == 200


def test_decisions_read_back_in_the_same_shape_confirm_returns(client, analysed):
    confirmed = decisions.confirm_routes(analysed, {
        "foundation_substructure": "self_perform", "electrical": "sublet",
    })
    read = client.get(f"/bridge/{analysed}/route/decisions").json()

    assert read["self_perform_packages"] == confirmed["self_perform_packages"]
    assert read["sublet_packages"] == confirmed["sublet_packages"]
    assert {d["package_key"]: d["chosen_route"] for d in read["decisions"]} == {
        "foundation_substructure": "self_perform", "electrical": "sublet",
    }


def test_a_confirmed_route_shows_on_the_proposal_read_as_still_advisory(client, analysed):
    # The bridge records decisions in its OWN table and is not the writer of package_routes'
    # chosen_route, so the proposal read keeps showing the recommendation as advisory.
    decisions.confirm_routes(analysed, {"electrical": "sublet"})
    body = client.get(f"/bridge/{analysed}/route/proposal").json()

    assert all(p["chosen_route"] is None for p in body["packages"])
    assert client.get(f"/bridge/{analysed}/route/decisions").json()["sublet_packages"] == ["electrical"]


def test_open_queries_ride_on_the_proposal_read(client, analysed):
    from client_boq import store as cb_store
    from client_boq.models import RFIItem

    conn = bridge_conn()
    try:
        cb_store.save_rfi(conn, analysed, RFIItem(rfi_id="q1", question="Which standard?"))
    finally:
        conn.close()

    assert client.get(f"/bridge/{analysed}/route/proposal").json()["open_queries"] == 1


def test_an_unapproved_set_still_reads_its_proposal(make_set, part_spec, client):
    # The gate refuses to PRODUCE a proposal; reading one back is not gated — a chip has to be able
    # to say "waits on the register" without being refused the information to say it.
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "SR", "Schedule of Rates", "pricing")])
    body = client.get("/bridge/ge-2026-14/route/proposal").json()
    assert body["review_approved"] is False and body["packages"] == []
