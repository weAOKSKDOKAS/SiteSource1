"""Spec for U5 — the scope of record, item by item. The freeze gate.

The estimate's scope used to be one summary plus a flat list of notes: enough to brief a pricing
run, not enough to sign. Freezing needs three things a paragraph cannot carry —

  * WHERE each line came from, so nothing walks into the scope on its own;
  * WHOSE WORDS it is in, so a model's suggestion and a person's decision never look alike;
  * whether an unanswered query has become an assumption somebody actually accepted.

The last one is the gate. Locked decision 8 says an open query does not block pricing — the
submission deadline does not move because the client has not replied — and that the forcing
function is freeze, where every unanswered query becomes an answer or a stated priced assumption.
So what blocks here is not the open query. It is pricing on a guess with nothing recording that a
person agreed to it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

fitz = pytest.importorskip("fitz")  # PyMuPDF


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _binder(pages: int = 12) -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        doc.new_page().insert_text((72, 100), f"Binder page {i} of {pages}", fontsize=11)
    doc.set_toc([
        [1, "Conditions of Tender", 1],
        [1, "Scope of Works", 5],
        [1, "Pricing Schedule", 9],
    ])
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def scoped(client: TestClient):
    """A set carried to a drafted scope, with one confirmed departure and one open query."""
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": "freeze-demo"},
        files={"files": ("binder.pdf", _binder(), "application/pdf")},
    )
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    client.post("/client-boq/review/run", data={"project_name": "freeze-demo", "set_id": set_id})

    items = client.get(f"/client-boq/review/register/{set_id}").json()["register"]["line_items"]
    confirmable = next(i for i in items if i["status"] != "citation_failed")
    queryable = next(i for i in items if i["item"] != confirmable["item"])

    client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {
            str(confirmable["item"]): "confirmed",
            str(queryable["item"]): "query",
        },
        "approved": True,
    })
    client.post("/client-boq/estimate/scope", json={"set_id": set_id})
    return client, set_id


def _sources(client: TestClient, set_id: str) -> dict:
    return client.get(f"/client-boq/estimate/scope/{set_id}/sources").json()


# ---------------------------------------------------------------------------
# Sources are derived, and nothing maps itself
# ---------------------------------------------------------------------------
def test_sources_come_from_the_register_the_queries_and_the_amendments(scoped):
    client, set_id = scoped
    body = _sources(client, set_id)
    groups = {s["group"] for s in body["sources"]}
    assert "departure" in groups, "a confirmed departure is a scope source"
    assert "rfi" in groups, "an open query is a scope source"
    assert all(s["mapped"] is False for s in body["sources"])
    assert body["items"] == [] and body["baseline"] == 0


def test_nothing_walks_into_the_scope_on_its_own(scoped):
    """Drafting the scope must not populate it. Every line is somebody's decision."""
    client, set_id = scoped
    assert _sources(client, set_id)["items"] == []


def test_mapping_a_source_moves_it_and_is_not_repeatable(scoped):
    client, set_id = scoped
    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"]
               if s["group"] == "departure")

    resp = client.post("/client-boq/estimate/scope/map", json={"set_id": set_id, "source_ref": ref})
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["source_ref"] == ref

    after = _sources(client, set_id)
    assert next(s for s in after["sources"] if s["source_ref"] == ref)["mapped"] is True
    assert len(after["items"]) == 1

    # Mapping it twice would put the same position into the offer letter twice.
    assert client.post("/client-boq/estimate/scope/map",
                       json={"set_id": set_id, "source_ref": ref}).status_code == 409


def test_unmapping_returns_the_source_to_the_rail(scoped):
    client, set_id = scoped
    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"]
               if s["group"] == "departure")
    item_id = client.post("/client-boq/estimate/scope/map",
                          json={"set_id": set_id, "source_ref": ref}).json()["item"]["item_id"]

    resp = client.delete(f"/client-boq/estimate/scope/item/{set_id}/{item_id}")
    assert resp.status_code == 200
    after = _sources(client, set_id)
    assert after["items"] == []
    assert next(s for s in after["sources"] if s["source_ref"] == ref)["mapped"] is False


# ---------------------------------------------------------------------------
# Authorship
# ---------------------------------------------------------------------------
def test_editing_a_line_always_stamps_it_user(scoped):
    """You edited it, you own it. There is no state where a person's words are attributed to a
    model, and none where a model's words silently become a person's."""
    client, set_id = scoped
    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"]
               if s["group"] == "departure")
    item = client.post("/client-boq/estimate/scope/map",
                       json={"set_id": set_id, "source_ref": ref}).json()["item"]

    edited = client.post("/client-boq/estimate/scope/item", json={
        "set_id": set_id, "item_id": item["item_id"],
        "text": "We exclude all temporary works to the adjoining site.",
    }).json()["item"]
    assert edited["badge"] == "user"
    assert edited["text"] == "We exclude all temporary works to the adjoining site."


def test_taking_ownership_without_changing_the_words(scoped):
    client, set_id = scoped
    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"]
               if s["group"] == "departure")
    item = client.post("/client-boq/estimate/scope/map",
                       json={"set_id": set_id, "source_ref": ref}).json()["item"]

    converted = client.post("/client-boq/estimate/scope/item", json={
        "set_id": set_id, "item_id": item["item_id"], "convert_to_user": True,
    }).json()["item"]
    assert converted["badge"] == "user"
    assert converted["text"] == item["text"]      # the words are untouched


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def test_an_open_query_maps_as_an_unaccepted_fallback(scoped):
    client, set_id = scoped
    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"] if s["group"] == "rfi")
    item = client.post("/client-boq/estimate/scope/map",
                       json={"set_id": set_id, "source_ref": ref}).json()["item"]

    assert item["is_fallback"] is True
    assert item["accepted"] is False
    assert _sources(client, set_id)["fallbacks_active"] == 1


def test_freezing_refuses_while_a_fallback_is_unaccepted(scoped):
    """The price would otherwise rest on a suggestion nobody agreed to."""
    client, set_id = scoped
    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"] if s["group"] == "rfi")
    client.post("/client-boq/estimate/scope/map", json={"set_id": set_id, "source_ref": ref})

    resp = client.post("/client-boq/estimate/scope/approve",
                       json={"set_id": set_id, "approved": True})
    assert resp.status_code == 409
    assert "unaccepted" in resp.json()["detail"]

    # And the estimate stays shut, because the scope gate never opened.
    assert client.post("/client-boq/estimate/run", json={"set_id": set_id}).status_code == 409


def test_accepting_the_fallback_opens_the_gate(scoped):
    client, set_id = scoped
    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"] if s["group"] == "rfi")
    item = client.post("/client-boq/estimate/scope/map",
                       json={"set_id": set_id, "source_ref": ref}).json()["item"]

    accepted = client.post("/client-boq/estimate/scope/item", json={
        "set_id": set_id, "item_id": item["item_id"],
        "text": "Priced on a 20-business-day assessment period.",
        "accept": True,
    }).json()
    assert accepted["item"]["accepted"] is True
    assert accepted["fallbacks_active"] == 0

    resp = client.post("/client-boq/estimate/scope/approve",
                       json={"set_id": set_id, "approved": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["scope_approved"] is True


def test_a_scope_with_no_fallbacks_at_all_still_freezes(scoped):
    """The gate blocks on unaccepted guesses, not on having done any mapping."""
    client, set_id = scoped
    resp = client.post("/client-boq/estimate/scope/approve",
                       json={"set_id": set_id, "approved": True})
    assert resp.status_code == 200


def test_an_open_query_by_itself_does_not_block(scoped):
    """Locked decision 8: the submission deadline does not move because the client has not
    replied. The query is still open here — what changed is that we recorded what we priced."""
    client, set_id = scoped
    before = client.get(f"/client-boq/rfi/{set_id}").json()["open"]
    assert before > 0

    ref = next(s["source_ref"] for s in _sources(client, set_id)["sources"] if s["group"] == "rfi")
    item = client.post("/client-boq/estimate/scope/map",
                       json={"set_id": set_id, "source_ref": ref}).json()["item"]
    client.post("/client-boq/estimate/scope/item", json={
        "set_id": set_id, "item_id": item["item_id"], "accept": True,
    })

    assert client.post("/client-boq/estimate/scope/approve",
                       json={"set_id": set_id, "approved": True}).status_code == 200
    assert client.get(f"/client-boq/rfi/{set_id}").json()["open"] == before  # still unanswered


def test_the_scope_routes_are_mounted(client):
    paths = set(client.app.openapi()["paths"])  # openapi(), not app.routes — CLAUDE.md trap 1
    assert {
        "/client-boq/estimate/scope/{set_id}/sources",
        "/client-boq/estimate/scope/map",
        "/client-boq/estimate/scope/item",
        "/client-boq/estimate/scope/item/{set_id}/{item_id}",
    } <= paths
