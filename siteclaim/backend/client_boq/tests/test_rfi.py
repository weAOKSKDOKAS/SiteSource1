"""Spec for T4 — the RFI / clarification loop.

The decision this is built on: **an open query does not block pricing.** A queried register line
stays open and the estimate still runs; the forcing function is the freeze gate, where every
unanswered question must become an answer or a stated priced assumption. Taken from the reference
package, where Tender Clarification No. 1 alone carried 17 questions answered in stages across two
clarifications and two addenda, while the submission deadline never moved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq import models

fitz = pytest.importorskip("fitz")  # PyMuPDF


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _pdf(pages: int, text: str = "page", toc: list | None = None) -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        doc.new_page().insert_text((72, 100), f"{text} {i} of {pages}, with enough text to read",
                                   fontsize=11)
    if toc:
        doc.set_toc(toc)
    data = doc.tobytes()
    doc.close()
    return data


def _reviewed(client: TestClient, name: str = "rfi-demo") -> str:
    """A set that has been ingested, split and reviewed, ready for verdicts."""
    binder = _pdf(12, "Binder page", toc=[
        [1, "Conditions of Tender", 1], [1, "Scope of Works", 5], [1, "Pricing Schedule", 9],
    ])
    resp = client.post("/client-boq/ingest/upload", data={"project_name": name},
                       files={"files": ("binder.pdf", binder, "application/pdf")})
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    client.post("/client-boq/review/run", data={"project_name": name, "set_id": set_id})
    return set_id


def _items(client: TestClient, set_id: str) -> list[dict]:
    return client.get(f"/client-boq/review/register/{set_id}").json()["register"]["items"]


# ---------------------------------------------------------------------------
# The fourth verdict
# ---------------------------------------------------------------------------
def test_query_is_a_verdict_the_human_gate_accepts(client):
    set_id = _reviewed(client)
    target = _items(client, set_id)[0]["item"]

    resp = client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(target): "query"}, "approved": True,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["queries_raised"]) == 1
    assert body["open_queries"] == 1


def test_a_queried_line_stays_open_while_the_others_close(client):
    set_id = _reviewed(client)
    items = _items(client, set_id)
    queried, dismissed = items[0]["item"], items[1]["item"]

    client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {str(queried): "query", str(dismissed): "dismissed"},
        "approved": True,
    })

    after = {i["item"]: i for i in _items(client, set_id)}
    assert after[queried]["status"] == "query"
    assert after[queried]["register_status"] == "open"     # the question is asked, not answered
    assert after[dismissed]["status"] == "dismissed"
    assert after[dismissed]["register_status"] == "closed"


def test_an_open_query_does_not_block_pricing(client):
    # The decision this whole feature turns on: the submission deadline does not move because the
    # client has not replied, so the estimate must still be able to run.
    set_id = _reviewed(client)
    target = _items(client, set_id)[0]["item"]
    client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(target): "query"}, "approved": True,
    })

    gate = client.get(f"/client-boq/gate/{set_id}").json()
    assert gate["review_approved"] is True
    assert gate["open_queries"] == 1        # ...and it is visible while it is open

    assert client.post("/client-boq/estimate/scope", json={"set_id": set_id}).status_code == 200
    client.post("/client-boq/estimate/scope/approve", json={"set_id": set_id, "approved": True})
    assert client.post("/client-boq/estimate/run", json={"set_id": set_id}).status_code == 200


def test_a_query_carries_the_citation_of_the_line_it_came_from(client):
    set_id = _reviewed(client)
    line = next(i for i in _items(client, set_id) if i["clause"])
    client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(line["item"]): "query"}, "approved": True,
    })

    rfi = client.get(f"/client-boq/rfi/{set_id}").json()["items"][0]
    assert rfi["origin"] == "register"
    assert rfi["register_item"] == line["item"]
    assert rfi["clause"] == line["clause"]   # the client can find what is being asked about


def test_a_citation_failed_line_can_be_queried_even_though_it_cannot_be_confirmed(client):
    set_id = _reviewed(client)
    failed = next((i for i in _items(client, set_id) if i["status"] == "citation_failed"), None)
    if failed is None:
        pytest.skip("this fixture register has no citation_failed line")

    blocked = client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(failed["item"]): "confirmed"}, "approved": False,
    })
    assert blocked.status_code == 409

    # Asking about it is exactly the right response, so it must be allowed.
    ok = client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(failed["item"]): "query"}, "approved": True,
    })
    assert ok.status_code == 200 and ok.json()["open_queries"] == 1


def test_an_unknown_verdict_is_still_refused(client):
    set_id = _reviewed(client)
    target = _items(client, set_id)[0]["item"]
    resp = client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(target): "maybe"}, "approved": True,
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Raising, batching, and the letter
# ---------------------------------------------------------------------------
def test_a_question_can_be_raised_while_pricing_not_only_from_the_register(client):
    # Many real questions surface only when someone tries to put a number on something.
    set_id = _reviewed(client)
    resp = client.post("/client-boq/rfi", json={
        "set_id": set_id, "origin": "pricing",
        "question": "Is the temporary access road to be priced by the contractor?",
        "clause": "4.12",
    })
    assert resp.status_code == 200
    assert resp.json()["rfi"]["origin"] == "pricing"
    assert resp.json()["open_queries"] == 1


def test_an_empty_question_and_a_bad_origin_are_refused(client):
    set_id = _reviewed(client)
    assert client.post("/client-boq/rfi", json={
        "set_id": set_id, "question": "   "}).status_code == 422
    assert client.post("/client-boq/rfi", json={
        "set_id": set_id, "question": "real question", "origin": "telepathy"}).status_code == 422


def test_batching_numbers_the_questions_and_marks_them_sent(client):
    set_id = _reviewed(client)
    for text in ("First question?", "Second question?", "Third question?"):
        client.post("/client-boq/rfi", json={"set_id": set_id, "question": text,
                                             "origin": "manual", "clause": "9.9"})

    resp = client.post("/client-boq/rfi/batch", json={"set_id": set_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 3
    assert body["ref"] == "Technical Query No. 1"

    listing = client.get(f"/client-boq/rfi/{set_id}").json()
    assert listing["by_status"] == {"sent": 3}
    assert [i["number"] for i in listing["items"]] == [1, 2, 3]
    assert listing["open"] == 3          # sent is still open: we are waiting on a reply


def test_the_letter_reproduces_the_questions_verbatim(client):
    # A letter that paraphrased would ask the client something other than what was meant.
    set_id = _reviewed(client)
    question = "Does clause 27.18 require scaffolding inspection by an independent competent person?"
    client.post("/client-boq/rfi", json={
        "set_id": set_id, "question": question, "origin": "manual", "clause": "27.18", "page": 41,
    })

    markdown = client.post("/client-boq/rfi/batch", json={"set_id": set_id}).json()["markdown"]
    assert question in markdown                 # exactly as written
    assert "Clause 27.18" in markdown           # cited so the client can find it
    assert "page 41" in markdown
    assert "**1.**" in markdown                 # and numbered


def test_a_second_batch_continues_the_numbering_of_rounds(client):
    set_id = _reviewed(client)
    client.post("/client-boq/rfi", json={"set_id": set_id, "question": "Round one?"})
    first = client.post("/client-boq/rfi/batch", json={"set_id": set_id}).json()
    client.post("/client-boq/rfi", json={"set_id": set_id, "question": "Round two?"})
    second = client.post("/client-boq/rfi/batch", json={"set_id": set_id}).json()

    assert first["ref"] == "Technical Query No. 1"
    assert second["ref"] == "Technical Query No. 2"
    assert second["count"] == 1                 # only the new draft went in the second round
    assert "Round one?" not in second["markdown"]


def test_batching_with_nothing_drafted_is_refused(client):
    set_id = _reviewed(client)
    assert client.post("/client-boq/rfi/batch", json={"set_id": set_id}).status_code == 422


def test_a_sent_batch_can_be_read_back(client):
    set_id = _reviewed(client)
    client.post("/client-boq/rfi", json={"set_id": set_id, "question": "Anything?"})
    batch_id = client.post("/client-boq/rfi/batch", json={"set_id": set_id}).json()["batch_id"]

    body = client.get(f"/client-boq/rfi/{set_id}/batch/{batch_id}").json()
    assert body["ref"] == "Technical Query No. 1"
    assert "Anything?" in body["markdown"]
    assert len(body["items"]) == 1
    assert client.get(f"/client-boq/rfi/{set_id}/batch/nope").status_code == 404


# ---------------------------------------------------------------------------
# Answers, and being overtaken
# ---------------------------------------------------------------------------
def test_recording_an_answer_closes_the_question(client):
    set_id = _reviewed(client)
    client.post("/client-boq/rfi", json={"set_id": set_id, "question": "Who supplies the crane?"})
    rfi_id = client.post("/client-boq/rfi/batch", json={"set_id": set_id}).json() and \
        client.get(f"/client-boq/rfi/{set_id}").json()["items"][0]["rfi_id"]

    resp = client.post("/client-boq/rfi/answer", json={
        "set_id": set_id, "rfi_id": rfi_id,
        "answer": "The contractor supplies all lifting plant.",
        "answered_by": "Tender Clarification No. 1",
    })
    assert resp.status_code == 200
    assert resp.json()["rfi"]["status"] == "answered"
    assert resp.json()["open_queries"] == 0
    assert client.get(f"/client-boq/rfi/{set_id}").json()["items"][0]["answered_by"] == \
        "Tender Clarification No. 1"


def test_answering_an_unknown_query_404s(client):
    set_id = _reviewed(client)
    assert client.post("/client-boq/rfi/answer", json={
        "set_id": set_id, "rfi_id": "rfi-999", "answer": "x"}).status_code == 404


def test_an_addendum_overtakes_open_questions_about_the_part_it_amends(client):
    # A question about a clause the client has since rewritten has been answered, whether or not
    # anyone wrote back. Leaving it open would have us chasing a reply that is not coming.
    set_id = _reviewed(client)
    parts = client.get(f"/client-boq/ingest/parts/{set_id}").json()["parts"]
    target = parts[0]["part_id"]

    client.post("/client-boq/rfi", json={
        "set_id": set_id, "question": "Is clause 2.2 priced per rig or per shift?",
        "origin": "register", "part_id": target, "clause": "2.2",
    })
    client.post("/client-boq/rfi/batch", json={"set_id": set_id})
    assert client.get(f"/client-boq/rfi/{set_id}").json()["open"] == 1

    client.post("/client-boq/ingest/document",
                data={"set_id": set_id, "kind": "addendum", "ref": "Tender Addendum No. 1"},
                files=[("files", ("Tender Addendum No.1.pdf", _pdf(2, "Letter"), "application/pdf")),
                       ("files", ("boq-rev1.pdf", _pdf(6, "Revised"), "application/pdf"))])
    resp = client.post("/client-boq/ingest/changes/approve", json={
        "set_id": set_id, "doc_id": "doc-1",
        "mappings": [{"filename": "boq-rev1.pdf", "part_id": target}],
    })

    assert len(resp.json()["overtaken_queries"]) == 1
    listing = client.get(f"/client-boq/rfi/{set_id}").json()
    assert listing["open"] == 0
    item = listing["items"][0]
    assert item["status"] == "overtaken"
    assert item["answered_by"] == "Tender Addendum No. 1"
    assert "Overtaken by" in item["answer"]


def test_a_question_about_an_untouched_part_survives_an_addendum(client):
    set_id = _reviewed(client)
    parts = client.get(f"/client-boq/ingest/parts/{set_id}").json()["parts"]
    amended, untouched = parts[0]["part_id"], parts[1]["part_id"]

    client.post("/client-boq/rfi", json={
        "set_id": set_id, "question": "Still open?", "part_id": untouched, "clause": "5.1"})
    client.post("/client-boq/rfi/batch", json={"set_id": set_id})

    client.post("/client-boq/ingest/document",
                data={"set_id": set_id, "kind": "addendum", "ref": "Tender Addendum No. 1"},
                files=[("files", ("Tender Addendum No.1.pdf", _pdf(2, "Letter"), "application/pdf")),
                       ("files", ("boq-rev1.pdf", _pdf(6, "Revised"), "application/pdf"))])
    resp = client.post("/client-boq/ingest/changes/approve", json={
        "set_id": set_id, "doc_id": "doc-1",
        "mappings": [{"filename": "boq-rev1.pdf", "part_id": amended}],
    })

    assert resp.json()["overtaken_queries"] == []
    assert client.get(f"/client-boq/rfi/{set_id}").json()["open"] == 1


def test_the_open_count_is_what_a_freeze_gate_would_read(client):
    set_id = _reviewed(client)
    for text in ("One?", "Two?", "Three?"):
        client.post("/client-boq/rfi", json={"set_id": set_id, "question": text})
    ids = [i["rfi_id"] for i in client.get(f"/client-boq/rfi/{set_id}").json()["items"]]
    client.post("/client-boq/rfi/batch", json={"set_id": set_id})

    assert client.get(f"/client-boq/rfi/{set_id}").json()["open"] == 3
    client.post("/client-boq/rfi/answer", json={
        "set_id": set_id, "rfi_id": ids[0], "answer": "Answered."})
    listing = client.get(f"/client-boq/rfi/{set_id}").json()
    assert listing["open"] == 2
    assert listing["by_status"] == {"answered": 1, "sent": 2}


def test_the_rfi_routes_are_mounted(client):
    paths = set(client.app.openapi()["paths"])  # openapi(), not app.routes — CLAUDE.md trap 1
    assert {
        "/client-boq/rfi",
        "/client-boq/rfi/{set_id}",
        "/client-boq/rfi/batch",
        "/client-boq/rfi/answer",
        "/client-boq/rfi/{set_id}/batch/{batch_id}",
    } <= paths
