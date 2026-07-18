"""End-to-end DEMO test for the review slice, exercised through the HTTP API.

Runs the whole slice offline (s01→s02→s03→s07→s08) via ``POST /client-boq/review/run``, then asserts:
every status is represented in the register, citations are verified (a failed one exists), the
review→estimate gate 409s before approval and opens after, the human approve endpoint is the writer
of the verdict, and a citation_failed line cannot be confirmed.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from client_boq.models import (
    STATUS_CANDIDATE,
    STATUS_CITATION_FAILED,
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    STATUS_RULE_FLAGGED,
    STATUS_UNCOVERED,
    STATUS_UNRESOLVED,
)


def _client() -> TestClient:
    from api import app

    return TestClient(app)


def _run_review(client: TestClient) -> dict:
    # A dummy file forces multipart; DEMO ignores the bytes and returns the fixture-driven register.
    resp = client.post(
        "/client-boq/review/run",
        data={"project_name": "demo-windows"},
        files={"files": ("subcontract.pdf", b"%PDF-1.4 demo", "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    return body["result"]


def test_review_run_produces_every_status_and_gates_estimate() -> None:
    client = _client()
    result = _run_review(client)
    set_id = result["set_id"]
    counts = result["status_counts"]

    # Every status path represented in one DEMO register.
    for status in (STATUS_RULE_FLAGGED, STATUS_CANDIDATE, STATUS_UNCOVERED, STATUS_UNRESOLVED, STATUS_CITATION_FAILED):
        assert counts.get(status, 0) >= 1, f"missing status {status} in {counts}"

    # Slice-2 stages are explicitly marked pending, not silently missing.
    assert set(result["slice2_pending"]) == {"scope_alignment", "program", "cashflow"}
    assert result["slice"] == "1"

    # The register is persisted and readable from the tables (source of truth).
    reg = client.get(f"/client-boq/review/register/{set_id}")
    assert reg.status_code == 200

    # Gate is closed before approval.
    assert client.get(f"/client-boq/gate/{set_id}").json()["review_approved"] is False
    assert client.post("/client-boq/estimate/run", json={"set_id": set_id}).status_code == 409

    # A citation_failed line cannot be confirmed.
    failed_item = next(d["item"] for d in result["register"]["items"] if d["status"] == STATUS_CITATION_FAILED)
    blocked = client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(failed_item): STATUS_CONFIRMED}, "approved": False,
    })
    assert blocked.status_code == 409

    # A rule_flagged line CAN be confirmed, and approving opens the gate — the human is the verdict writer.
    flagged_item = next(d["item"] for d in result["register"]["items"] if d["status"] == STATUS_RULE_FLAGGED)
    approve = client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(flagged_item): STATUS_CONFIRMED}, "approved": True,
    })
    assert approve.status_code == 200
    assert approve.json()["review_approved"] is True

    # Gate is now open; the verdict was persisted on that line.
    assert client.get(f"/client-boq/gate/{set_id}").json()["review_approved"] is True
    reg2 = client.get(f"/client-boq/review/register/{set_id}").json()
    confirmed = {d["item"]: d["status"] for d in reg2["register"]["items"]}
    assert confirmed[flagged_item] == STATUS_CONFIRMED


def test_dismiss_verdict_persists_and_citation_failed_can_be_dismissed() -> None:
    # The 'dismissed' verdict is a distinct human path from 'confirmed' — and a citation_failed line,
    # which cannot be CONFIRMED, CAN be dismissed. Exercise both, end to end.
    client = _client()
    result = _run_review(client)
    set_id = result["set_id"]
    items = result["register"]["items"]
    candidate_item = next(d["item"] for d in items if d["status"] == STATUS_CANDIDATE)
    failed_item = next(d["item"] for d in items if d["status"] == STATUS_CITATION_FAILED)

    resp = client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {str(candidate_item): STATUS_DISMISSED, str(failed_item): STATUS_DISMISSED},
        "approved": False,
    })
    assert resp.status_code == 200

    reg = client.get(f"/client-boq/review/register/{set_id}").json()
    status = {d["item"]: d["status"] for d in reg["register"]["items"]}
    assert status[candidate_item] == STATUS_DISMISSED
    assert status[failed_item] == STATUS_DISMISSED  # a failed citation may be dismissed, not confirmed
