"""End-to-end DEMO test for the estimate spine, through the HTTP API.

Approve the review (opening the gate), run the estimate offline, and assert the totals, margin
readout, every flag, and the GET endpoint — plus that the estimate 409s before approval and that a
DEMO estimate run (like review) never writes the committed sitesource.db.
"""

from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from client_boq.store import _demo_db_path
from db import store as db_store

_ALL_FLAGS = {"missing_rate", "rate_outlier", "empty_activity", "zero_or_negative_qty", "unclassified_item"}


def _client() -> TestClient:
    from api import app

    return TestClient(app)


def _run_review(client: TestClient) -> str:
    resp = client.post("/client-boq/review/run", data={"project_name": "demo-windows"},
                       files={"files": ("subcontract.pdf", b"%PDF-1.4 demo", "application/pdf")})
    assert resp.status_code == 200
    return resp.json()["result"]["set_id"]


def _approve_review_scope(client: TestClient, set_id: str) -> None:
    """Drive the two estimate gates: approve the review, draft the scope, approve the scope."""
    assert client.post("/client-boq/review/approve",
                       json={"set_id": set_id, "decisions": {}, "approved": True}).status_code == 200
    assert client.post("/client-boq/estimate/scope", json={"set_id": set_id}).status_code == 200
    assert client.post("/client-boq/estimate/scope/approve",
                       json={"set_id": set_id, "approved": True}).status_code == 200


def test_estimate_gated_then_runs_with_hand_checked_totals() -> None:
    client = _client()
    set_id = _run_review(client)

    # Gated before review approval.
    assert client.post("/client-boq/estimate/run", json={"set_id": set_id}).status_code == 409

    # Open both gates (review approve → scope draft → scope approve).
    _approve_review_scope(client, set_id)

    # Run the estimate (DEMO inline).
    run = client.post("/client-boq/estimate/run", json={"set_id": set_id})
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "done"
    est = body["result"]

    t = est["totals"]
    assert t["total_direct"] == 5_652_600.0
    assert t["total_indirect"] == 421_315.0
    assert t["total_cost"] == 6_073_915.0
    assert t["margin_pct"] == 15.0
    assert t["price"] == 6_985_002.25
    assert t["margin_amount"] == 911_087.25

    # Every validation flag is exercised by the fixture schedule.
    assert set(est["flag_counts"]) == _ALL_FLAGS
    # The unclassified item is surfaced (not costed).
    assert any(i["item_id"] == "U1" for i in est["estimate"]["unclassified"])
    # Per-line cost traces are present (a productivity line records its hours).
    a1 = next(a for a in est["estimate"]["activities"] if a["item_id"] == "A1")
    prod_line = next(l for l in a1["lines"] if l["productivity"])
    assert prod_line["hours"] == 320.0 and prod_line["rate_source"] == "csv"

    # GET the persisted estimate.
    got = client.get(f"/client-boq/estimate/{set_id}")
    assert got.status_code == 200 and got.json()["totals"]["price"] == 6_985_002.25


def test_estimate_demo_leaves_committed_db_byte_identical(monkeypatch) -> None:
    monkeypatch.delenv("SITESOURCE_DB", raising=False)  # exercise the DEMO scratch-DB default (4A)
    committed = db_store.DEFAULT_DB_PATH
    before = hashlib.sha256(committed.read_bytes()).hexdigest()

    client = _client()
    set_id = _run_review(client)
    _approve_review_scope(client, set_id)
    assert client.post("/client-boq/estimate/run", json={"set_id": set_id}).status_code == 200
    # The workbook endpoint (read-only) must not write the committed DB either.
    assert client.get(f"/client-boq/estimate/{set_id}/workbook").status_code == 200

    assert hashlib.sha256(committed.read_bytes()).hexdigest() == before
    assert _demo_db_path().is_file()
