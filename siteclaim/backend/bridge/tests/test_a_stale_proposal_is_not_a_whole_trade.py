"""The reported card: "Section 1 — General and Preliminaries (30 items)" over 145 bill lines.

`GET /route/proposal` joins rows PERSISTED by the last `/route/analyze` against units RECOMPUTED
from the CURRENT split, and nothing keeps the two in step — re-running the split (the operator's
"Re-run the split" button) rewrites `bridge_scopes` and touches `package_routes` not at all. A
stored key the new split no longer produces then missed the recomputed lookup and came back as
`section: None`.

`None` is the LEGITIMATE value for a whole-trade unit, so the contradiction was unreadable
downstream and every consumer took the generous reading:

* `Route.tsx` suppressed the package-key chip (so the one card that had lost its section was also
  the one card that did not say which package it was), dropped the section from its heading, titled
  the panel "Bill lines", and `itemsFor` listed the WHOLE trade — 145 lines under a caption
  claiming 30.
* `Sourcing.tsx::sourcingScope` built that sublet package from all 145 items instead of its own 30,
  while those same 30 also sat inside `ground_investigation:2`. One firm is asked to price the
  entire trade, and 30 bill lines are priced twice across two packages.
* `confirm_routes` validated only against the same stale table, so a route could be recorded for a
  package that no longer exists — and `sublet_packages` is read straight off those rows.

Two answers, because the wrong reading and the staleness are different problems:

**The key is the authority on its own section.** `route_units` builds it as `f"{trade}:{code}"`,
so the section never has to be inferred. A `trade:SECTION` key with no section is a contradiction
that can no longer be produced.

**Staleness is reported, and confirming is refused.** A proposal that predates the split is one to
re-run, not one to read carefully.
"""

import pytest
from fastapi.testclient import TestClient

from bridge import decisions, scope as scope_mod
from bridge.identity import bridge_conn
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

SET = "nd-2025-04"
# The real bill's shape: GI holding sections 1..6, 145 items, 30 of them in section 1.
SIZES = {"1": 30, "2": 28, "3": 14, "4": 28, "5": 4, "6": 41}


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _scope(sizes: dict[str, int]) -> ScopePackages:
    items = [SorItem(item_ref=f"{code}.{i}", description=f"item {code}.{i}", section=code)
             for code, n in sizes.items() for i in range(1, n + 1)]
    return ScopePackages(project_name="Contract No. ND/2025/04", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="Ground investigation", sor_items=items,
        sections=[SectionMeta(code=c, title=f"Bill {c}", item_count=n) for c, n in sizes.items()])])


def _save_split(scope: ScopePackages) -> None:
    conn = bridge_conn()
    try:
        scope_mod.save_scope_on(conn, SET, scope)
    finally:
        conn.close()


@pytest.fixture
def re_split(make_set, part_spec):
    """Analyse over sections 1..6, then re-run the split with section 1 gone.

    The operator action that produces this: a corrected bill selection, an addendum, or simply
    pressing "Re-run the split" — none of which touch `package_routes`.
    """
    make_set(SET, "Contract No. ND/2025/04",
             [part_spec(1, "BQ", "Bill of Quantities", "pricing")], review_approved=True)
    _save_split(_scope(SIZES))
    decisions.propose_routes(SET)
    _save_split(_scope({c: n for c, n in SIZES.items() if c != "1"}))
    return SET


# -- the section comes from the key ------------------------------------------------------------
@pytest.mark.parametrize("key,expected", [
    ("ground_investigation:1", "1"),
    ("ground_investigation:2", "2"),
    ("ground_investigation", None),
    ("", None),
    ("trade:", None),
])
def test_a_key_names_its_own_section(key, expected):
    assert decisions.section_of_key(key) == expected


def test_a_stale_row_keeps_its_section(re_split):
    """The whole defect in one assertion. `ground_investigation:1` is not in the current split, and
    it must still come back saying it is section 1 — not `None`, which reads as the whole trade."""
    body = decisions.stored_proposal(SET)
    row = next(p for p in body["packages"] if p["package_key"] == "ground_investigation:1")

    assert row["section"] == "1"


def test_every_surviving_row_is_unchanged(re_split):
    body = decisions.stored_proposal(SET)
    live = {p["package_key"]: p["section"] for p in body["packages"] if not p["stale"]}

    assert live == {f"ground_investigation:{c}": c for c in SIZES if c != "1"}


def test_a_whole_trade_unit_still_has_no_section(make_set, part_spec):
    """The value `None` legitimately means: this package is the whole trade. Deriving from the key
    must not invent a section where there genuinely is none."""
    make_set(SET, "Contract No. ND/2025/04",
             [part_spec(1, "BQ", "Bill", "pricing")], review_approved=True)
    _save_split(ScopePackages(project_name="ND", packages=[TradeWorkPackage(
        trade="joinery_fitting_out", scope_summary="Loose furniture",
        sor_items=[SorItem(item_ref="J1", description="benches")])]))
    decisions.propose_routes(SET)

    row = decisions.stored_proposal(SET)["packages"][0]
    assert row["package_key"] == "joinery_fitting_out"
    assert row["section"] is None and row["stale"] is False


# -- the staleness is reported -------------------------------------------------------------------
def test_the_stale_package_is_named(re_split):
    body = decisions.stored_proposal(SET)

    assert body["stale_packages"] == ["ground_investigation:1"]
    assert any("not in the current scope split" in n for n in body["notes"])
    assert any("Re-run the routing analysis" in n for n in body["notes"])


def test_each_row_says_whether_it_is_stale(re_split):
    rows = {p["package_key"]: p["stale"] for p in decisions.stored_proposal(SET)["packages"]}

    assert rows["ground_investigation:1"] is True
    assert all(v is False for k, v in rows.items() if k != "ground_investigation:1")


def test_a_proposal_read_straight_after_the_analysis_is_not_stale(make_set, part_spec):
    """A fresh analysis recomputes both sides from the same split — a false alarm here would teach
    the operator to click through the real one."""
    make_set(SET, "ND/2025/04", [part_spec(1, "BQ", "Bill", "pricing")], review_approved=True)
    _save_split(_scope(SIZES))
    decisions.propose_routes(SET)

    body = decisions.stored_proposal(SET)
    assert body["stale_packages"] == [] and body["notes"] == []
    assert all(p["stale"] is False for p in body["packages"])


def test_a_set_with_no_split_reports_nothing_stale(client):
    """No split is not a disagreement with one. A set reviewed from loose uploads has no split at
    all, and gating on that would be a gate on a state that is not wrong."""
    body = client.get(f"/bridge/never-touched/route/proposal").json()

    assert body["stale_packages"] == [] and body["notes"] == []
    assert body["has_split"] is False


# -- confirming a stale package is refused ----------------------------------------------------------
def test_confirming_a_package_the_split_no_longer_produces_is_refused(re_split, client):
    resp = client.post(f"/bridge/{SET}/route/confirm", json={
        "decisions": [{"package_key": "ground_investigation:1", "chosen_route": "sublet"}]})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    # RE-ANCHORED: this pinned "route/analyze" — the exact defect the brief opens with, an API
    # call on an estimator's screen. The refusal still names the package and still says what to
    # do; it now says it in the user's words.
    assert "ground_investigation:1" in detail
    assert "not in the current split" in detail
    assert "Re-propose the routing" in detail


def test_confirming_a_surviving_package_still_works(re_split, client):
    resp = client.post(f"/bridge/{SET}/route/confirm", json={
        "decisions": [{"package_key": "ground_investigation:2", "chosen_route": "sublet"}]})

    assert resp.status_code == 200
    assert resp.json()["sublet_packages"] == ["ground_investigation:2"]


def test_re_analysing_clears_the_refusal(re_split, client):
    """The refusal names the action that clears it, and the action clears it."""
    decisions.propose_routes(SET)
    body = decisions.stored_proposal(SET)
    assert body["stale_packages"] == []

    resp = client.post(f"/bridge/{SET}/route/confirm", json={
        "decisions": [{"package_key": "ground_investigation:2", "chosen_route": "sublet"}]})
    assert resp.status_code == 200


def test_an_unknown_package_is_still_refused_with_its_own_message(re_split, client):
    """Two different wrongs: a key nobody proposed, and a key the split dropped. Collapsing them
    into one sentence would send the operator to re-analyse when the payload is simply wrong."""
    resp = client.post(f"/bridge/{SET}/route/confirm", json={
        "decisions": [{"package_key": "not_a_trade:9", "chosen_route": "sublet"}]})

    assert resp.status_code == 400
    assert "this proposal does not have" in resp.json()["detail"]
    assert "Re-propose" not in resp.json()["detail"], (
        "a wrong payload must not send the operator to re-analyse")


def test_a_set_with_no_split_can_still_confirm(make_set, part_spec, client):
    """The proposal can be built from a scope that was never persisted as a bridge split — refusing
    there would gate on the absence of a comparison, not on a disagreement."""
    from db import routing
    from bridge.identity import run_ref_for

    make_set(SET, "ND/2025/04", [part_spec(1, "BQ", "Bill", "pricing")], review_approved=True)
    conn = bridge_conn()
    try:
        routing.write_proposal(conn, run_ref_for(SET), [
            {"package_key": "ground_investigation:2", "trade": "ground_investigation",
             "recommended_route": "sublet"}])
    finally:
        conn.close()

    resp = client.post(f"/bridge/{SET}/route/confirm", json={
        "decisions": [{"package_key": "ground_investigation:2", "chosen_route": "sublet"}]})
    assert resp.status_code == 200
