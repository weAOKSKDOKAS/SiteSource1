"""E2E gate matrix for the two-step estimate: scope gate + run gate, and the register→scope wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from api import app

    return TestClient(app)


def _run_review(client: TestClient) -> dict:
    resp = client.post("/client-boq/review/run", data={"project_name": "demo-windows"},
                       files={"files": ("subcontract.pdf", b"%PDF-1.4 demo", "application/pdf")})
    assert resp.status_code == 200
    return resp.json()["result"]


def test_scope_and_run_gate_matrix_with_wiring_and_amendment() -> None:
    client = _client()
    result = _run_review(client)
    set_id = result["set_id"]
    items = result["register"]["items"]

    # 1) scope is gated on the review register being approved.
    assert client.post("/client-boq/estimate/scope", json={"set_id": set_id}).status_code == 409

    # Approve the review, confirming a rule_flagged departure and dismissing a candidate one.
    confirmed = next(d for d in items if d["criterion_id"] == "TP-04")     # rule_flagged
    dismissed = next(d for d in items if d["criterion_id"] == "SQD-06")    # candidate
    approve = client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {str(confirmed["item"]): "confirmed", str(dismissed["item"]): "dismissed"},
        "approved": True,
    })
    assert approve.status_code == 200

    # 2) run is gated on the SCOPE being approved — distinct 409 message.
    run_blocked = client.post("/client-boq/estimate/run", json={"set_id": set_id})
    assert run_blocked.status_code == 409 and "scope" in run_blocked.json()["detail"].lower()

    # Draft the scope (now allowed). The wiring: confirmed departure present, dismissed absent.
    scope = client.post("/client-boq/estimate/scope", json={"set_id": set_id})
    assert scope.status_code == 200
    notes = " ".join(n["text"] for n in scope.json()["result"]["scope"]["notes"])
    assert confirmed["proposed_position"] in notes            # confirmed departure carried into scope
    assert dismissed["proposed_position"] not in notes        # dismissed never resurfaces

    # Approve the scope with an amendment → it becomes the scope of record.
    amended = "Priced strictly to the tender drawings revision C; podium glazing excluded pending RFI."
    ap = client.post("/client-boq/estimate/scope/approve",
                     json={"set_id": set_id, "amended_summary": amended, "approved": True})
    assert ap.status_code == 200 and ap.json()["scope_approved"] is True
    assert client.get(f"/client-boq/estimate/scope/{set_id}").json()["summary_of_record"] == amended

    # 3) both gates open → run succeeds.
    assert client.post("/client-boq/estimate/run", json={"set_id": set_id}).status_code == 200

    # The offer letter carries the wiring through to Appendix A: the confirmed departure appears
    # verbatim (source register); the dismissed one is absent everywhere.
    lj = client.get(f"/client-boq/estimate/{set_id}/letter").json()
    appendix = lj["letter"]["appendix"]
    assert any(a["source"] == "register" and a["text"] == confirmed["proposed_position"] for a in appendix)
    assert all(dismissed["proposed_position"] not in a["text"] for a in appendix)
    assert dismissed["proposed_position"] not in lj["markdown"]


def test_scope_approve_requires_a_draft_first() -> None:
    client = _client()
    set_id = _run_review(client)["set_id"]
    client.post("/client-boq/review/approve", json={"set_id": set_id, "decisions": {}, "approved": True})
    # No scope draft yet → approve 404s (cannot approve nothing).
    assert client.post("/client-boq/estimate/scope/approve", json={"set_id": set_id}).status_code == 404
