"""Prompt A — the golden end-to-end scenario + self-perform rate precedent.

One confirm-routing on the golden case walks the WHOLE product: two trades route to SUBLET
(two leveling sections + two awards, with the risk catch in the mechanical section) and two
route to SELF-PERFORM (their routed estimates open with real rate precedent from the baked
demo benchmark corpus, keyed to the same item_refs). All offline under the DEMO autouse
fixture; the corpus is provenance='demo' and never leaks into live coverage.
"""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import benchmark, seed, store

client = TestClient(app)

# The two self-perform packages — item_refs match fixtures/cases/clean/scope_packages.json,
# so their routed estimates Tier-1 match the golden corpus line for line.
_FIRE_PACKAGE = {
    "trade": "Fire Services",
    "scope_summary": "Sprinkler installation, fire detection and alarm, hydrants and hose reels.",
    "sor_items": [
        {"item_ref": "F-01", "description": "Sprinkler heads and pipework", "unit": "no", "qty": 1240.0},
        {"item_ref": "F-02", "description": "Fire detection and alarm devices", "unit": "no", "qty": 410.0},
        {"item_ref": "F-03", "description": "Hydrants and hose reels", "unit": "no", "qty": 36.0},
    ],
    "source_refs": ["schedule_of_rates.pdf"],
}
_JOINERY_PACKAGE = {
    "trade": "Joinery & Fitting-out",
    "scope_summary": "Demountable partitions, suspended ceilings, doors and ironmongery, bespoke joinery.",
    "sor_items": [
        {"item_ref": "J-01", "description": "Demountable partitions", "unit": "m2", "qty": 920.0},
        {"item_ref": "J-02", "description": "Suspended ceilings", "unit": "m2", "qty": 3100.0},
        {"item_ref": "J-03", "description": "Doors and ironmongery", "unit": "no", "qty": 145.0},
        {"item_ref": "J-04", "description": "Bespoke joinery — reception and tea rooms", "unit": "item", "qty": 1.0},
    ],
    "source_refs": ["schedule_of_rates.pdf"],
}


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    """A temp demo DB (carrying the golden corpus) so estimate writes never touch the committed one."""
    db = tmp_path / "demo.db"
    seed.build_database(db, profile="demo")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


def test_golden_case_yields_two_sections_and_two_awards_with_the_risk_catch():
    case = client.get("/demo/golden").json()
    assert case["hero_trade"] == "electrical"
    assert {r["trade"] for r in case["replies"]} == {"electrical", "mechanical_plumbing"}
    assert set(case["rationale_fixtures"]) == {"electrical", "mechanical_plumbing"}

    sections = client.post("/level-all", json={"replies": case["replies"]}).json()["sections"]
    assert {s["trade"] for s in sections} == {"electrical", "mechanical_plumbing"}

    flat = [b for s in sections for b in s["levelled"]]
    recs = {
        s["trade"]: s["recommendation"]
        for s in client.post(
            "/recommend-all", json={"levelled": flat, "demo_fixtures": case["rationale_fixtures"]}
        ).json()["sections"]
    }
    # two awards, each on its own trade; the risk catch lands inside the golden path
    assert recs["electrical"]["recommended_firm_id"] == "F-EL-02"          # clean cheapest
    assert recs["mechanical_plumbing"]["recommended_firm_id"] == "F-MP-01"  # not the cheapest
    pacific = next(r for r in recs["mechanical_plumbing"]["ranked"] if r["firm_id"] == "F-MP-03")
    assert pacific["recommended_against"]  # cheapest but flagged — recommended against despite price


def _rate_suggestions_for(package):
    body = client.post(
        "/estimate/from-package", json={"package": package, "run_ref": f"golden-{package['trade']}"}
    ).json()
    return body, client.get(f"/estimate/{body['id']}/rate-suggestions").json()


def test_fire_self_perform_estimate_has_matching_rate_precedent(demo_db):
    body, rates = _rate_suggestions_for(_FIRE_PACKAGE)
    assert body["trade"] == "fire_services" and body["priced_item_count"] == 0  # nothing pre-priced
    assert rates["corpus_empty"] is False
    by_ref = {s["item_ref"]: s for s in rates["suggestions"]}
    assert set(by_ref) == {"F-01", "F-02", "F-03"}
    # every line has real precedent whose ref matches the estimate line (Tier-1 exact)
    for ref, s in by_ref.items():
        assert s["tier"] == 1 and s["matched_ref"] == ref and s["rate_median"] is not None
    # exactly one line over-ran on rate — the "over-ran on rate" warning
    warned = {ref for ref, s in by_ref.items() if s["rate_warnings"]}
    assert warned == {"F-02"}
    assert by_ref["F-02"]["rate_warnings"][0]["reason_code"] == "access_restriction"


def test_joinery_self_perform_estimate_has_matching_rate_precedent(demo_db):
    body, rates = _rate_suggestions_for(_JOINERY_PACKAGE)
    assert body["trade"] == "joinery_fitting_out" and body["priced_item_count"] == 0
    assert rates["corpus_empty"] is False
    by_ref = {s["item_ref"]: s for s in rates["suggestions"]}
    assert set(by_ref) == {"J-01", "J-02", "J-03", "J-04"}
    for ref, s in by_ref.items():
        assert s["tier"] == 1 and s["matched_ref"] == ref and s["rate_median"] is not None
    warned = {ref for ref, s in by_ref.items() if s["rate_warnings"]}
    assert warned == {"J-04"}
    assert by_ref["J-04"]["rate_warnings"][0]["reason_code"] == "rate_reprice"


def test_golden_corpus_is_demo_provenance_and_never_counts_in_live(tmp_path):
    demo_path, live_path = tmp_path / "demo.db", tmp_path / "live.db"
    seed.build_database(demo_path, profile="demo")
    seed.build_database(live_path, profile="live")
    demo, live = store.get_connection(demo_path), store.get_connection(live_path)
    try:
        by_trade = {p["trade"]: p for p in benchmark.list_projects(demo)
                    if p["trade"] in ("fire_services", "joinery_fitting_out")}
        assert set(by_trade) == {"fire_services", "joinery_fitting_out"}
        assert all(p["provenance"] == "demo" for p in by_trade.values())
        # demo corpus never counts in live coverage — summary sums provenance='live' only
        assert benchmark.summary(demo)["projects"] == 0
        # the clean live profile carries no golden corpus at all
        live_trades = {p["trade"] for p in benchmark.list_projects(live)}
        assert not ({"fire_services", "joinery_fitting_out"} & live_trades)
        assert benchmark.summary(live)["projects"] == 0
    finally:
        demo.close()
        live.close()
