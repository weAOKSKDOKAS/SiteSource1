"""`/costing/ask` reads the register's real fields.

THE DEFECT, and it is not an LLM defect. `_ground_for` assembled the register block with

    label = f"register:{item.criterion_id or item.clause_ref or item.id}"
    ground.sources[label] = f"{item.title}. {item.finding}"[:1200]

and `DepartureItem` has none of `title`, `finding`, `clause_ref` or `id`. Its `model_config` is
`{}` — no `extra="allow"` — so pydantic raises `AttributeError` rather than returning None. The
`item.title` access was unconditional for every register item, so the Ask box returned a bare HTTP
500 on any tender that had a review register, **before a single token was sent**.

Why nothing caught it: every client_boq test forces DEMO_MODE, and in DEMO `complete_json` returns
its fixture before any provider code runs — but the fixture short-circuit is DOWNSTREAM of the
ground assembly, so a DEMO test exercises this line and would have failed. There was simply no test
that put a register item in front of it.

These tests build a register from `DepartureItem`'s ACTUAL fields, so a rename anywhere in the
model breaks them here rather than in a 500 an operator sees.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq import models, store

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _item(**kw) -> models.DepartureItem:
    row = {
        "item": 1,
        "clause": "GCT 27.1",
        "criterion_id": "CRIT-LD-01",
        "category": "Time and liquidated damages",
        "clause_area": "Liquidated damages",
        "extracted_value": "HK$25,000 per day",
        "cited_text": "The Contractor shall pay liquidated damages at the rate stated.",
        "rationale": "Above the benchmark rate for a contract of this value.",
        "proposed_position": "Seek a cap at 10% of the contract sum.",
        "status": models.STATUS_CANDIDATE,
    }
    row.update(kw)
    return models.DepartureItem(**row)


def _register(*items: models.DepartureItem) -> models.DepartureRegister:
    return models.DepartureRegister(set_id=SET, items=list(items))


def _save(register: models.DepartureRegister) -> None:
    conn = store.get_conn()
    try:
        store.save_register(conn, register)
    finally:
        conn.close()


class TestTheGroundIsBuiltFromFieldsTheModelHas:

    def test_every_field_the_ground_reads_exists_on_the_model(self):
        """The direct statement of the defect. Any of these names disappearing is an AttributeError
        in production, so it is asserted here instead."""
        fields = set(models.DepartureItem.model_fields)
        for name in ("item", "clause", "criterion_id", "category", "clause_area",
                     "extracted_value", "cited_text", "rationale", "proposed_position", "status"):
            assert name in fields, f"_ground_for reads {name!r}"

    def test_the_names_it_used_to_read_are_not_on_the_model(self):
        """Kept so the fix cannot be quietly reverted by someone 'restoring' the old field names —
        they were never there."""
        fields = set(models.DepartureItem.model_fields)
        assert not fields & {"title", "finding", "clause_ref", "id"}

    def test_the_model_refuses_unknown_attributes_which_is_why_it_raised(self):
        with pytest.raises(AttributeError):
            _ = _item().title  # type: ignore[attr-defined]

    def test_a_register_item_becomes_a_source(self, client):
        from client_boq.router import _ground_for

        _save(_register(_item()))
        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        assert "register:CRIT-LD-01" in ground.sources
        body = ground.sources["register:CRIT-LD-01"]
        assert "Liquidated damages" in body
        assert "HK$25,000 per day" in body
        assert "Seek a cap" in body

    def test_a_finding_with_no_criterion_is_labelled_by_its_clause(self):
        """s04/s05/s06 findings and uncovered clauses carry no `criterion_id`, and that is the
        exact case the old `item.clause_ref` fallback would have raised on."""
        from client_boq.router import _ground_for

        _save(_register(_item(criterion_id="", clause="SCT 12.4")))
        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        assert "register:SCT 12.4" in ground.sources

    def test_an_item_with_neither_falls_back_to_its_number_rather_than_raising(self):
        from client_boq.router import _ground_for

        _save(_register(_item(item=7, criterion_id="", clause="")))
        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        assert "register:7" in ground.sources

    def test_an_item_carrying_no_text_at_all_says_so_rather_than_being_blank(self):
        from client_boq.router import _ground_for

        bare = models.DepartureItem(item=3, criterion_id="CRIT-X")
        _save(_register(bare))
        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        # `status` always has a value, so it must not be what makes an empty line look like
        # ground worth citing.
        assert "carries no text" in ground.sources["register:CRIT-X"]

    def test_the_ground_is_capped_at_sixty_items(self):
        from client_boq.router import _ground_for

        _save(_register(*[_item(item=n, criterion_id=f"CRIT-{n:03d}") for n in range(1, 81)]))
        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        assert len([k for k in ground.sources if k.startswith("register:")]) == 60

    def test_each_source_is_truncated_to_the_stated_budget(self):
        from client_boq.router import _ground_for

        _save(_register(_item(rationale="x" * 5000)))
        conn = store.get_conn()
        try:
            ground = _ground_for(conn, SET)
        finally:
            conn.close()
        # The 1,200 budget bounds the ITEM's own text; the status is a short constant tail.
        assert len(ground.sources["register:CRIT-LD-01"]) <= 1200 + 40


class TestTheEndpointAnswersInsteadOf500:

    def test_asking_about_a_tender_with_a_register_does_not_500(self, client):
        """The reproduction. This returned `{"detail": "Something went wrong on the server…"}` for
        every tender that had been reviewed."""
        _save(_register(_item()))
        response = client.post(f"{BASE}/costing/ask",
                               json={"set_id": SET, "question": "What are the liquidated damages?"})
        assert response.status_code != 500, response.text
        assert response.status_code == 200, response.text

    def test_the_answer_is_returned_and_the_register_reached_the_ground(self, client):
        _save(_register(_item()))
        body = client.post(f"{BASE}/costing/ask",
                           json={"set_id": SET, "question": "What are the liquidated damages?"}
                           ).json()
        assert "answer" in body or "cannot_answer" in body or "reply" in body, body

    def test_a_tender_with_no_register_still_answers(self, client):
        response = client.post(f"{BASE}/costing/ask",
                               json={"set_id": "never-reviewed", "question": "anything?"})
        assert response.status_code == 200, response.text
