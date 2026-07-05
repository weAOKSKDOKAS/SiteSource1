"""Firm-browse endpoints (Gap B) — real-provenance only, filters, pagination, offline.

The browse must reproduce the coverage 140/46 population exactly: illustrative demo firms and
partner-archive firms never leak in. Pure DB reads — run under the DEMO autouse fixture.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed

client = TestClient(app)


@pytest.fixture
def demo_db(tmp_path, monkeypatch):
    # The demo profile carries real (public_register) + 16 illustrative firms — the browse
    # must expose only the real ones.
    db = tmp_path / "firms.db"
    seed.build_database(db, profile="demo")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


def _all_ids(**params) -> set[str]:
    """Collect firm ids across every /firms page for the given filters."""
    ids: set[str] = set()
    offset = 0
    while True:
        body = client.get("/firms", params={**params, "limit": 100, "offset": offset}).json()
        ids |= {f["firm_id"] for f in body["items"]}
        offset += 100
        if offset >= body["total"]:
            break
    return ids


def test_firms_routes_registered():
    paths = {r.path for r in app.routes}
    assert {"/firms", "/firms/{firm_id}"} <= paths


def test_firms_are_real_provenance_only(demo_db):
    illustrative = {r[0] for r in sqlite3.connect(demo_db).execute(
        "SELECT firm_id FROM firms WHERE provenance != 'public_register'")}
    real = {r[0] for r in sqlite3.connect(demo_db).execute(
        "SELECT firm_id FROM firms WHERE provenance = 'public_register'")}
    assert illustrative and real  # both present in the demo profile

    body = client.get("/firms", params={"limit": 100}).json()
    assert body["total"] == len(real)                 # exactly the real population (coverage 140)
    assert client.get("/coverage").json()["total_firms"] == body["total"]
    listed = _all_ids()
    assert listed == real                             # every real firm, no illustrative leak
    assert listed.isdisjoint(illustrative)


def test_name_search_filters(demo_db):
    body = client.get("/firms", params={"q": "engineering", "limit": 100}).json()
    assert body["total"] >= 1
    assert all("engineering" in f["name"].lower() for f in body["items"])


def test_trade_filter(demo_db):
    trade = client.get("/coverage").json()["trades"][0]
    body = client.get("/firms", params={"trade": trade, "limit": 100}).json()
    assert body["total"] >= 1
    assert all(trade in f["trades"] for f in body["items"])


def test_pagination_limit_and_offset(demo_db):
    total = client.get("/firms").json()["total"]
    p1 = client.get("/firms", params={"limit": 10, "offset": 0}).json()
    p2 = client.get("/firms", params={"limit": 10, "offset": 10}).json()
    assert p1["limit"] == 10 and len(p1["items"]) == 10 and p1["total"] == total
    ids1 = {f["firm_id"] for f in p1["items"]}
    ids2 = {f["firm_id"] for f in p2["items"]}
    assert ids1.isdisjoint(ids2)                       # distinct pages
    # a bogus page size falls back to the default 25
    assert client.get("/firms", params={"limit": 7}).json()["limit"] == 25


def test_firm_detail_hit_and_404(demo_db):
    first = client.get("/firms", params={"limit": 1}).json()["items"][0]
    got = client.get(f"/firms/{first['firm_id']}").json()
    assert got["firm_id"] == first["firm_id"] and got["name"] == first["name"]
    assert client.get("/firms/does-not-exist").status_code == 404
