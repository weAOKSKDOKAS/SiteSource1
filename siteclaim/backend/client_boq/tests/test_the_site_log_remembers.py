"""The tender remembers its discussions — and memory never becomes authority.

THE LOOP THIS CLOSES, per the owner's decision (plan §1.1): Site discussions are persisted, a
later question is grounded in what was already discussed and decided, and when a discussion
concludes something that changes money it becomes a **proposed condition citing the discussion** —
which then goes through the ordinary propose-and-confirm path. The AI never writes the number.

THE LINE THAT MUST NOT MOVE, pinned throughout: the log is MEMORY, NOT AUTHORITY. It stores the
validated answer — the type with no field for a rate, a verdict or a decision — so nothing the log
holds can ever carry more weight than the reply did. Nothing prices from it; the ground labels an
entry a DISCUSSION, never a clause.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    from api import app

    return TestClient(app)


def _seed_register(client):
    """The cheapest ground: one register line, so `/costing/ask` has something to stand on."""
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


class TestTheExchangePersists:
    def test_an_ask_lands_in_the_log_with_who_and_when(self, client):
        _seed_register(client)
        reply = client.post(f"{BASE}/costing/ask", headers={"X-CBOQ-Actor": "SW"},
                            json={"set_id": SET, "question": "what about LDs?"}).json()
        assert reply["log_seq"] == 1 and reply["asked_by"] == "SW"

        body = client.get(f"{BASE}/costing/{SET}/log").json()
        assert body["count"] == 1
        entry = body["entries"][0]
        assert entry["question"] == "what about LDs?"
        assert entry["asked_by"] == "SW" and entry["asked_at"]

    def test_the_log_survives_what_a_response_does_not(self, client):
        """The response dies with the tab; the log is what a refresh comes back to."""
        _seed_register(client)
        for n, q in enumerate(["first question", "second question"], start=1):
            assert client.post(f"{BASE}/costing/ask",
                               json={"set_id": SET, "question": q}).json()["log_seq"] == n
        entries = client.get(f"{BASE}/costing/{SET}/log").json()["entries"]
        assert [e["question"] for e in entries] == ["first question", "second question"]

    def test_a_tender_with_no_ground_logs_nothing(self, client):
        """The cannot-answer short-circuit returns before the model AND before the log — an
        exchange that grounded on nothing is not a discussion worth remembering."""
        reply = client.post(f"{BASE}/costing/ask",
                            json={"set_id": SET, "question": "anything?"}).json()
        assert reply["cannot_answer"]
        assert client.get(f"{BASE}/costing/{SET}/log").json()["count"] == 0


class TestTheGroundGainsMemory:
    def test_a_later_question_sees_the_earlier_discussion(self, client):
        _seed_register(client)
        client.post(f"{BASE}/costing/ask", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "question": "is the hillside access bad?"})
        from client_boq import store
        from client_boq.router import _ground_for

        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        assert "discussion:1" in ground.sources
        assert "is the hillside access bad?" in ground.sources["discussion:1"]
        assert "SW asked" in ground.sources["discussion:1"]

    def test_a_recorded_condition_reaches_the_ground_with_its_status(self, client):
        """"Confirmed" and "written down and rejected" are opposite facts sharing a table, so the
        status travels in words — a later discussion must not rely on a rejected condition."""
        _seed_register(client)
        client.post(f"{BASE}/costing/conditions", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "condition_id": "c-access",
                          "text": "the hillside track needs a platform before any rig stands"})
        from client_boq import store
        from client_boq.router import _ground_for

        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        assert "condition:c-access" in ground.sources
        assert "not yet decided" in ground.sources["condition:c-access"]

    def test_a_discussion_is_labelled_a_discussion_not_a_clause(self, client):
        """Memory, not authority — the label is the guard. A model reading the ground can cite
        `discussion:1` and a reader instantly knows it is quoting a conversation, not the pack."""
        _seed_register(client)
        client.post(f"{BASE}/costing/ask", json={"set_id": SET, "question": "q"})
        from client_boq import store
        from client_boq.router import _ground_for

        conn = store.get_conn()
        try:
            labels = [k for k in _ground_for(conn, SET).sources if k.startswith("discussion:")]
        finally:
            conn.close()
        assert labels == ["discussion:1"]


class TestAConditionBornOfADiscussion:
    def test_the_condition_carries_the_discussion_that_concluded_it(self, client):
        _seed_register(client)
        reply = client.post(f"{BASE}/costing/ask", headers={"X-CBOQ-Actor": "SW"},
                            json={"set_id": SET, "question": "platform needed?"}).json()
        client.post(f"{BASE}/costing/conditions", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "condition_id": "c-born",
                          "text": "hillside platform before any rig stands",
                          "born_of_seq": reply["log_seq"]})
        from client_boq import store

        conn = store.get_conn()
        try:
            row = store.load_condition(conn, SET, "c-born")
        finally:
            conn.close()
        assert row["born_of_seq"] == reply["log_seq"]

    def test_the_log_shows_which_discussion_became_a_condition(self, client):
        _seed_register(client)
        reply = client.post(f"{BASE}/costing/ask",
                            json={"set_id": SET, "question": "q"}).json()
        client.post(f"{BASE}/costing/conditions",
                    json={"set_id": SET, "condition_id": "c-x", "text": "some condition",
                          "born_of_seq": reply["log_seq"]})
        entries = client.get(f"{BASE}/costing/{SET}/log").json()["entries"]
        assert entries[0]["became_condition"] == "c-x"

    def test_a_condition_typed_straight_onto_the_register_says_no_discussion(self, client):
        _seed_register(client)
        client.post(f"{BASE}/costing/conditions",
                    json={"set_id": SET, "condition_id": "c-typed", "text": "typed by hand"})
        from client_boq import store

        conn = store.get_conn()
        try:
            row = store.load_condition(conn, SET, "c-typed")
        finally:
            conn.close()
        assert row["born_of_seq"] == 0, "0 is 'none' — seq is 1-based on purpose"


class TestMemoryIsNotAuthority:
    def test_the_logged_answer_still_has_no_field_for_a_number_or_verdict(self):
        """Structural: the log stores the validated Answer's dict, and Answer deliberately has no
        rate, no status, no decision field. If one is ever added this fails by name."""
        from client_boq.boq.ask import Answer

        fields = set(Answer.model_fields)
        assert fields == {"answer", "citations", "figures_used", "proposes", "cannot_answer",
                          "stripped"}, (
            "Answer gained a field — check it cannot carry a rate, a verdict or a decision "
            "before letting the log store it")

    def test_deciding_a_condition_is_still_the_sole_writer_path(self, client):
        """The provenance column must not have opened a second door: recording a condition born of
        a discussion writes NO status and NO model value."""
        _seed_register(client)
        reply = client.post(f"{BASE}/costing/ask",
                            json={"set_id": SET, "question": "q"}).json()
        client.post(f"{BASE}/costing/conditions",
                    json={"set_id": SET, "condition_id": "c-nv", "text": "words",
                          "born_of_seq": reply["log_seq"]})
        from client_boq import store

        conn = store.get_conn()
        try:
            row = store.load_condition(conn, SET, "c-nv")
        finally:
            conn.close()
        assert row["status"] == "" and row["applied_value"] is None


class TestTheColumnIsAdditive:
    def test_a_database_created_before_the_column_gains_it(self, tmp_path):
        """The same migration pattern `basis_key` pinned: an old DB's conditions table gains
        `born_of_seq` with DEFAULT 0, so every pre-log condition reads back as 'no discussion'."""
        from client_boq import models

        db = tmp_path / "old.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE client_boq_conditions (
                set_id TEXT NOT NULL, condition_id TEXT NOT NULL, text TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT, proposed_path TEXT NOT NULL DEFAULT '', proposed_value REAL,
                proposal_basis TEXT NOT NULL DEFAULT '', proposal_source TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '', decided_by TEXT NOT NULL DEFAULT '',
                decided_at TEXT, applied_value REAL,
                PRIMARY KEY (set_id, condition_id))""")
        conn.execute("INSERT INTO client_boq_conditions (set_id, condition_id, text) "
                     "VALUES ('s', 'old', 'written before the log existed')")
        conn.commit()
        models.init_tables(conn)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT born_of_seq FROM client_boq_conditions").fetchone()
        conn.close()
        assert row["born_of_seq"] == 0
