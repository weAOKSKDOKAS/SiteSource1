"""The three endpoints: final-approval, submit, and the read that reflects both."""

import pytest
from fastapi.testclient import TestClient

from client_boq import store
from client_boq.models import LetterOfOffer

SET = "nd-2025-04"


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _seed_letter(price: float = 1_250_000.0) -> None:
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=SET, name=SET, slug=SET, status="estimated")
        store.save_letter(conn, LetterOfOffer(set_id=SET, price=price, price_str=f"HK${price:,.0f}",
                                              markdown="OFFER"))
    finally:
        conn.close()


def _deadline(date: str, status: str = "confirmed") -> None:
    conn = store.get_conn()
    try:
        store.upsert_set_meta(conn, SET, close_date=date, close_date_status=status)
    finally:
        conn.close()


# -- the read reflects approval, then submission ----------------------------------------------------
def test_get_reflects_the_lifecycle(client):
    _seed_letter()

    before = client.get(f"/bridge/{SET}/submission").json()
    assert before["approval"] is None and before["submission"] is None
    assert before["letter_ready"] is True

    client.post(f"/bridge/{SET}/final-approval", json={"verdict": "approve", "approved_by": "R. Lam"})
    mid = client.get(f"/bridge/{SET}/submission").json()
    assert mid["approval"]["verdict"] == "approve" and mid["submission"] is None

    client.post(f"/bridge/{SET}/submit", json={"proof": "portal-1"})
    after = client.get(f"/bridge/{SET}/submission").json()
    assert after["submission"]["proof"] == "portal-1"
    assert after["submission"]["price_snapshot"] == 1_250_000.0


def test_letter_ready_is_false_before_the_estimate(client):
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=SET, name=SET, slug=SET, status="reviewed")
    finally:
        conn.close()
    assert client.get(f"/bridge/{SET}/submission").json()["letter_ready"] is False


# -- submit before approval is a 409 naming the missing approval ------------------------------------
def test_submit_before_approval_is_409(client):
    _seed_letter()
    resp = client.post(f"/bridge/{SET}/submit", json={"proof": "x"})

    assert resp.status_code == 409
    assert "no final approval" in resp.json()["detail"]


def test_a_revise_verdict_does_not_open_submission(client):
    _seed_letter()
    client.post(f"/bridge/{SET}/final-approval",
                json={"verdict": "revise", "rationale": "fix exclusion 4"})
    assert client.post(f"/bridge/{SET}/submit", json={"proof": "x"}).status_code == 409


def test_a_revise_without_rationale_is_400(client):
    _seed_letter()
    resp = client.post(f"/bridge/{SET}/final-approval", json={"verdict": "revise"})
    assert resp.status_code == 400 and "what to correct" in resp.json()["detail"]


def test_an_unknown_verdict_is_400(client):
    resp = client.post(f"/bridge/{SET}/final-approval", json={"verdict": "maybe"})
    assert resp.status_code == 400


# -- a past-deadline submission still records but flags on_time=0 -----------------------------------
def test_a_late_submission_records_with_on_time_zero(client):
    _seed_letter()
    _deadline("2000-01-01")
    client.post(f"/bridge/{SET}/final-approval", json={"verdict": "approve"})
    resp = client.post(f"/bridge/{SET}/submit", json={"proof": "late-but-in"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["on_time"] == 0 and body["deadline"] == "2000-01-01"


def test_an_unknown_deadline_submits_with_on_time_null(client):
    _seed_letter()
    client.post(f"/bridge/{SET}/final-approval", json={"verdict": "approve"})
    body = client.post(f"/bridge/{SET}/submit", json={"proof": "x"}).json()

    assert body["on_time"] is None
    assert client.get(f"/bridge/{SET}/submission").json()["deadline_known"] is False
