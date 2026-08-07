"""The closeout endpoints: outcome (+ corpus hook), lessons, change-control, closeout, handover."""

import pytest
from fastapi.testclient import TestClient

SET = "nd-2025-04"


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


# -- outcome round-trips and triggers the corpus hook ----------------------------------------------
def test_outcome_round_trips(client):
    resp = client.post(f"/bridge/{SET}/outcome",
                       json={"status": "won", "notes": "Awarded at HK$1.25m."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"]["status"] == "won"

    read = client.get(f"/bridge/{SET}/closeout").json()
    assert read["outcome"]["status"] == "won" and read["handover_ready"] is True


def test_a_won_outcome_feeds_the_corpus(client):
    body = client.post(f"/bridge/{SET}/outcome", json={"status": "won"}).json()
    assert body["corpus"]["fed"] is True and body["corpus"]["benchmark_project_id"]


def test_a_submitted_outcome_does_not_feed_the_corpus(client):
    body = client.post(f"/bridge/{SET}/outcome", json={"status": "submitted"}).json()
    assert body["corpus"]["fed"] is False


def test_an_unknown_status_is_400(client):
    assert client.post(f"/bridge/{SET}/outcome", json={"status": "pending"}).status_code == 400


# -- lessons -----------------------------------------------------------------------------------------
def test_lessons_add_and_list(client):
    client.post(f"/bridge/{SET}/lessons", json={"category": "pricing", "lesson": "Rock rate light."})
    client.post(f"/bridge/{SET}/lessons", json={"category": "scope", "lesson": "Tighten exclusions."})
    lessons = client.get(f"/bridge/{SET}/lessons").json()["lessons"]

    assert [l["lesson"] for l in lessons] == ["Rock rate light.", "Tighten exclusions."]


def test_an_empty_lesson_is_400(client):
    assert client.post(f"/bridge/{SET}/lessons", json={"lesson": "  "}).status_code == 400


# -- change-control log ------------------------------------------------------------------------------
def test_post_submission_events_add_and_list(client):
    client.post(f"/bridge/{SET}/post-submission",
                json={"kind": "clarification", "detail": "Prelims include the cabin."})
    events = client.get(f"/bridge/{SET}/post-submission").json()["events"]

    assert len(events) == 1 and events[0]["kind"] == "clarification"


def test_an_empty_event_is_400(client):
    assert client.post(f"/bridge/{SET}/post-submission", json={"detail": ""}).status_code == 400


# -- closeout aggregates the three logs -------------------------------------------------------------
def test_closeout_aggregates(client):
    client.post(f"/bridge/{SET}/outcome", json={"status": "won"})
    client.post(f"/bridge/{SET}/lessons", json={"category": "pricing", "lesson": "A"})
    client.post(f"/bridge/{SET}/post-submission", json={"kind": "note", "detail": "B"})
    state = client.get(f"/bridge/{SET}/closeout").json()

    assert state["outcome"]["status"] == "won"
    assert len(state["lessons"]) == 1 and len(state["events"]) == 1


def test_an_untouched_tender_closeout_is_empty_not_404(client):
    state = client.get(f"/bridge/never-touched/closeout").json()
    assert state["outcome"] is None and state["handover_ready"] is False


# -- handover gated on won ---------------------------------------------------------------------------
def test_handover_is_a_preview_before_won(client):
    h = client.get(f"/bridge/{SET}/handover").json()
    assert h["ready"] is False and h["missing"]


def test_handover_is_ready_once_won(client):
    client.post(f"/bridge/{SET}/outcome", json={"status": "won"})
    h = client.get(f"/bridge/{SET}/handover").json()

    assert h["ready"] is True
    assert "Handover" in h["markdown"]
