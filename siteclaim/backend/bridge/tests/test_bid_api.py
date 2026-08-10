"""The bid endpoints — GET the brief, POST the verdict. Mirrors /final-approval and /submit.

Two routes and no third. `GET /{set_id}/bid` assembles and proposes; `POST /{set_id}/bid/confirm`
records what a person decided. There is deliberately no endpoint that lets anything else write a
verdict, and no query parameter that makes the GET record one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import app
from bridge.identity import run_ref_for
from client_boq import models as cb_models
from client_boq import store as cb_store

BASE = "/bridge"
SET = "bid-api-test"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def reviewed():
    """A tender whose review has run and been approved — the state a bid decision follows."""
    from bridge.identity import bridge_conn

    conn = bridge_conn()
    try:
        cb_store.save_register(conn, cb_models.DepartureRegister(set_id=run_ref_for(SET)))
        cb_store.set_review_approved(conn, run_ref_for(SET), True)
    finally:
        conn.close()


class TestTheBrief:
    def test_it_comes_back_with_signals_a_recommendation_and_no_decision_yet(self, client,
                                                                            reviewed):
        body = client.get(f"{BASE}/{SET}/bid").json()
        assert body["set_id"] == run_ref_for(SET)
        assert set(body["signals"]) == {"deadline", "open_clarifications", "review_approved",
                                        "departures", "scope_gaps", "coverage"}
        assert body["recommendation"]["verdict"] in {"bid", "clarify"}
        assert body["recommendation"]["reasons"]
        assert body["decision"] is None

    def test_every_signal_arrives_with_its_source_named(self, client, reviewed):
        for key, block in client.get(f"{BASE}/{SET}/bid").json()["signals"].items():
            assert block.get("source"), key

    def test_a_tender_nothing_has_run_on_answers_rather_than_404ing(self, client):
        """"Nothing has happened yet" is a state. Every field says so on its own terms."""
        body = client.get(f"{BASE}/bid-api-untouched/bid")
        assert body.status_code == 200
        assert body.json()["decision"] is None

    def test_an_unresolvable_set_is_refused_as_route_confirm_refuses_one(self, client):
        assert client.get(f"{BASE}/ /bid").status_code in (400, 404)


class TestRecordingTheVerdict:
    def test_a_bid_is_recorded_and_the_brief_reflects_it(self, client, reviewed):
        posted = client.post(f"{BASE}/{SET}/bid/confirm",
                             json={"verdict": "bid", "decided_by": "SW"})
        assert posted.status_code == 200, posted.text
        assert posted.json()["verdict"] == "bid" and posted.json()["decided_by"] == "SW"

        assert client.get(f"{BASE}/{SET}/bid").json()["decision"]["verdict"] == "bid"

    def test_no_bid_without_a_rationale_is_refused_and_names_what_is_missing(self, client,
                                                                            reviewed):
        reply = client.post(f"{BASE}/{SET}/bid/confirm", json={"verdict": "no_bid"})
        assert reply.status_code == 400
        assert "rationale is required" in reply.json()["detail"]

    def test_clarify_without_a_rationale_is_refused_too(self, client, reviewed):
        reply = client.post(f"{BASE}/{SET}/bid/confirm",
                            json={"verdict": "clarify", "rationale": "  "})
        assert reply.status_code == 400

    def test_an_unknown_verdict_is_refused_and_names_the_three(self, client, reviewed):
        reply = client.post(f"{BASE}/{SET}/bid/confirm", json={"verdict": "probably"})
        assert reply.status_code == 400
        assert "'bid'" in reply.json()["detail"] and "'no_bid'" in reply.json()["detail"]

    def test_the_strategic_factors_survive_the_round_trip_untouched(self, client, reviewed):
        factors = {"fit": "we drilled the adjacent contract", "capacity": "two rigs free",
                   "win_probability": "unknown"}
        client.post(f"{BASE}/{SET}/bid/confirm",
                    json={"verdict": "bid", "factors": factors, "decided_by": "SW"})
        stored = client.get(f"{BASE}/{SET}/bid").json()["decision"]
        assert stored["factors"] == factors, "the operator's own words, unedited"

    def test_a_human_may_record_no_bid_the_rule_would_never_propose(self, client, reviewed):
        """The rule can only say bid or clarify. The PERSON can say no_bid, which is the whole
        point of the decision being theirs — and both stay visible side by side."""
        client.post(f"{BASE}/{SET}/bid/confirm",
                    json={"verdict": "no_bid", "rationale": "no rigs free in that window"})
        body = client.get(f"{BASE}/{SET}/bid").json()
        assert body["decision"]["verdict"] == "no_bid"
        assert body["recommendation"]["verdict"] != "no_bid"

    def test_re_deciding_replaces_rather_than_accumulating(self, client, reviewed):
        client.post(f"{BASE}/{SET}/bid/confirm",
                    json={"verdict": "clarify", "rationale": "three questions out"})
        client.post(f"{BASE}/{SET}/bid/confirm", json={"verdict": "bid"})
        assert client.get(f"{BASE}/{SET}/bid").json()["decision"]["verdict"] == "bid"


def test_both_routes_are_registered_and_there_is_no_third(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "get" in paths[f"{BASE}/{{set_id}}/bid"]
    assert "post" in paths[f"{BASE}/{{set_id}}/bid/confirm"]
    assert "post" not in paths[f"{BASE}/{{set_id}}/bid"], "the GET never records a verdict"
