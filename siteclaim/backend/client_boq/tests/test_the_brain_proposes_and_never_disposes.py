"""The brain proposes and never disposes — pinned structurally, not by prompt.

The owner's three decisions (plan §1): one strong model reads everything; it dispatches focused
reads; and it is PROPOSE-ONLY — every approval, verdict and number stays a human click. These
tests pin the mechanisms that make that true by construction:

* `RawBriefing` has NO field for a verdict, a rate, a class or a gate flag (the DepartureProposal
  guarantee). If one is ever added, the frozen-fields test here fails by name.
* A proposed action is only an id into the ACTIONS registry. `validate` discards an id the
  registry does not carry — visibly, in `stripped` — and the TAB comes from the registry, so the
  model cannot invent a destination. Every destination is a screen; the gated endpoint behind it
  still takes a human click with an actor header.
* Citations are validated against the ground exactly as the chat's are.
* Running the brain changes NOTHING: no gate flag, no verdict, no condition. The briefing table
  is append-only memory, like the site log.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"

TAB_IDS = {"documents", "register", "bid", "scope", "site", "route", "sourcing", "price",
           "offer", "closeout"}


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    from api import app

    return TestClient(app)


def _seed_register(client) -> None:
    from client_boq import models, store

    register = models.DepartureRegister(set_id=SET, items=[models.DepartureItem(
        item=1, clause="GCC 12", criterion_id="CRIT-LD-01",
        clause_area="Liquidated damages",
        rationale="LDs are 0.1% per day, capped at 10%.", cited_text="clause 12 text")])
    conn = store.get_conn()
    try:
        store.save_register(conn, register)
    finally:
        conn.close()


class TestTheShapeCannotCarryAVerdict:
    def test_the_raw_briefing_has_no_field_for_authority(self):
        from client_boq.brain import RawAction, RawBriefing

        assert set(RawBriefing.model_fields) == {
            "understanding", "disagreements", "proposed_actions", "cannot_assess"}, (
            "RawBriefing gained a field — check it cannot carry a verdict, a rate, a class or a "
            "gate flag before letting the brain produce it")
        assert set(RawAction.model_fields) == {"action_id", "reasoning", "citations"}, (
            "RawAction gained a field — the tab/label must keep coming from the registry, "
            "never from the model")

    def test_every_registry_destination_is_a_real_screen(self):
        from client_boq.brain import ACTIONS

        assert {tab for tab, _label in ACTIONS.values()} <= TAB_IDS


class TestValidationIsTheDoorman:
    def test_an_invented_action_is_discarded_and_named(self):
        from client_boq import brain
        from client_boq.boq.ask import Ground

        briefing = brain.validate(
            {"understanding": "u", "proposed_actions": [
                {"action_id": "approve_everything_now", "reasoning": "trust me"},
                {"action_id": "decide_register", "reasoning": "lines are open"},
            ]},
            Ground(sources={"gate:review": "the register is NOT yet approved"}))
        assert [a.action_id for a in briefing.actions] == ["decide_register"]
        assert briefing.actions[0].tab == "register", "the destination is the registry's"
        assert any("approve_everything_now" in s for s in briefing.stripped)

    def test_an_ungrounded_citation_is_stripped_and_reported(self):
        from client_boq import brain
        from client_boq.boq.ask import Ground

        briefing = brain.validate(
            {"proposed_actions": [{"action_id": "settle_sweep", "reasoning": "r",
                                   "citations": [{"source": "register:MADE-UP", "quote": "q"},
                                                 {"source": "bill", "quote": "real"}]}]},
            Ground(sources={"bill": "revision 0: 23 items"}))
        action = briefing.actions[0]
        assert [c.source for c in action.citations] == ["bill"]
        assert any("register:MADE-UP" in s for s in briefing.stripped)


class TestTheRunIsGatedAndOffline:
    def test_a_tender_with_nothing_read_is_a_409_with_the_reason(self, client):
        response = client.post(f"{BASE}/brain/run", json={"set_id": SET})
        assert response.status_code == 409
        assert "nothing has been read" in response.json()["detail"]

    def test_a_demo_run_produces_a_persisted_briefing_with_screen_actions(self, client):
        _seed_register(client)
        reply = client.post(f"{BASE}/brain/run", headers={"X-CBOQ-Actor": "SW"},
                            json={"set_id": SET})
        assert reply.status_code == 200, reply.text
        result = reply.json()["result"]
        assert result["understanding"]
        assert result["actions"], "the fixture proposes actions"
        for action in result["actions"]:
            assert action["tab"] in TAB_IDS and action["label"], (
                "every action is a screen reference the registry supplied")

        body = client.get(f"{BASE}/brain/{SET}").json()
        assert body["count"] == 1 and body["briefing"]["seq"] == 1
        assert body["briefing"]["created_by"] == "SW"

    def test_briefings_append_rather_than_overwrite(self, client):
        _seed_register(client)
        client.post(f"{BASE}/brain/run", json={"set_id": SET})
        client.post(f"{BASE}/brain/run", json={"set_id": SET})
        body = client.get(f"{BASE}/brain/{SET}").json()
        assert body["count"] == 2 and body["briefing"]["seq"] == 2

    def test_running_the_brain_decides_nothing(self, client):
        """The whole point, end to end: after a run, every gate and verdict is exactly where a
        human left it."""
        from client_boq import store

        _seed_register(client)
        client.post(f"{BASE}/brain/run", json={"set_id": SET})
        conn = store.get_conn()
        try:
            assert store.review_is_approved(conn, SET) is False
            register = store.load_register(conn, SET)
            assert all(item.status == "candidate" or item.status == ""
                       or "candidate" in item.status for item in register.items), (
                "no register line gained a verdict")
            assert store.load_conditions(conn, SET) == []
        finally:
            conn.close()

    def test_a_briefing_that_never_ran_says_so(self, client):
        body = client.get(f"{BASE}/brain/{SET}").json()
        assert body["briefing"] is None
        assert "has not run" in body["waiting_on"]


class TestTheBrainIsItsOwnQuestion:
    def test_the_stored_brain_provider_wins(self):
        from client_boq import llm

        cfg = {"provider": "deepseek", "provider_ingest": "anthropic",
               "provider_brain": "openai"}
        assert llm.resolve_provider(cfg, llm.STAGE_BRAIN) == "openai"

    def test_unset_falls_to_the_app_default_not_to_ingest(self):
        """The brain reasons over what was read — it reads no pages, so inheriting the
        document-reading provider would be a category error dressed as a default."""
        from client_boq import llm

        cfg = {"provider": "deepseek", "provider_ingest": "anthropic", "provider_brain": ""}
        assert llm.resolve_provider(cfg, llm.STAGE_BRAIN) == "deepseek"

    def test_the_settings_endpoint_round_trips_the_brain_choice(self, client):
        reply = client.post(f"{BASE}/settings", headers={"X-CBOQ-Actor": "SW"},
                            json={"provider_brain": "anthropic", "model_brain": "claude-x"})
        assert reply.status_code == 200
        body = reply.json()
        assert body["provider_brain"] == "anthropic"
        assert body["effective"]["brain_provider"] == "anthropic"
        assert body["effective"]["model_brain"] == "claude-x"

    def test_an_unknown_brain_provider_is_refused(self, client):
        assert client.post(f"{BASE}/settings",
                           json={"provider_brain": "skynet"}).status_code == 422


class TestTheGroundModule:
    def test_an_unknown_family_is_a_keyerror_not_an_empty_ground(self, client):
        from client_boq import ground, store

        conn = store.get_conn()
        try:
            with pytest.raises(KeyError):
                ground.assemble(conn, SET, families={"bogus"})
        finally:
            conn.close()

    def test_gate_states_ride_along_only_with_real_content(self, client):
        """On a virgin tender the gate lines alone would be the no-ground refusal wearing
        sources; with a register present they appear, named."""
        from client_boq import ground, store

        conn = store.get_conn()
        try:
            assert ground.assemble(conn, SET).sources == {}
        finally:
            conn.close()

        _seed_register(client)
        conn = store.get_conn()
        try:
            sources = ground.assemble(conn, SET).sources
        finally:
            conn.close()
        assert "gate:review" in sources and "NOT yet approved" in sources["gate:review"]
        assert "bill" in sources and "no bill of quantities" in sources["bill"]
