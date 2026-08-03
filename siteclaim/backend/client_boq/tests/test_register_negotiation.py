"""Spec for U3 — negotiation text, and taking a question back out of a build.

Both close the same gap. Dismissing a clause is rarely the end of it: "we accept it as drafted"
and "we will not press this as a departure, but we will ask for X" are different positions, and
only the second one has anything to send. The `contractor_response` column existed for that and
nothing wrote it.

The pairing matters. Because the draft text lives on the REGISTER LINE and not on the question,
unqueueing the question keeps the text — which is what the design asks for in as many words:
"Remove from RFI Build 3 — keeps this draft text".
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
def reviewed(client: TestClient) -> tuple[TestClient, str, list[dict]]:
    """A set carried as far as a register, without approving it."""
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": "negotiation-demo"},
        files={"files": ("binder.pdf", _binder(), "application/pdf")},
    )
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    client.post("/client-boq/review/run",
                data={"project_name": "negotiation-demo", "set_id": set_id})
    items = client.get(f"/client-boq/review/register/{set_id}").json()["register"]["items"]
    assert items, "the fixture register should not be empty"
    return client, set_id, items


def _item(client: TestClient, set_id: str, number: int) -> dict:
    items = client.get(f"/client-boq/review/register/{set_id}").json()["register"]["items"]
    return next(i for i in items if i["item"] == number)


# ---------------------------------------------------------------------------
# Negotiation text
# ---------------------------------------------------------------------------
def test_dismissing_with_a_negotiation_position_records_both(reviewed):
    client, set_id, items = reviewed
    target = items[0]["item"]
    text = "We will accept the clause if the assessment period is cut to 20 business days."

    resp = client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {str(target): "dismissed"},
        "negotiations": {str(target): text},
        "approved": False,
    })
    assert resp.status_code == 200, resp.text

    row = _item(client, set_id, target)
    assert row["status"] == "dismissed"
    assert row["contractor_response"] == text


def test_negotiation_text_can_be_edited_without_re_deciding_the_line(reviewed):
    """Changing what you will ask for is not changing your verdict, so it must not require one."""
    client, set_id, items = reviewed
    target = items[0]["item"]

    client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {str(target): "dismissed"},
        "negotiations": {str(target): "First draft."},
        "approved": False,
    })
    client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {},                       # no verdict this time
        "negotiations": {str(target): "Second, better draft."},
        "approved": False,
    })

    row = _item(client, set_id, target)
    assert row["contractor_response"] == "Second, better draft."
    assert row["status"] == "dismissed"       # the verdict survived untouched


def test_a_query_verdict_asks_the_humans_own_words(reviewed):
    """When someone has written what they want to ask, that is the question — not the model's
    rationale, which is only ever the fallback."""
    client, set_id, items = reviewed
    target = items[0]["item"]
    mine = "Please confirm whether the retention is released in one moiety or two."

    client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {str(target): "query"},
        "negotiations": {str(target): mine},
        "approved": False,
    })

    rfis = client.get(f"/client-boq/rfi/{set_id}").json()["items"]
    raised = [r for r in rfis if r["register_item"] == target]
    assert raised and raised[0]["question"] == mine


def test_approving_without_negotiations_leaves_the_column_empty(reviewed):
    client, set_id, items = reviewed
    target = items[0]["item"]
    client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(target): "confirmed"}, "approved": False,
    })
    assert _item(client, set_id, target)["contractor_response"] == ""


# ---------------------------------------------------------------------------
# Taking a question back out of a build
# ---------------------------------------------------------------------------
def test_withdrawing_a_draft_question_keeps_the_draft_text(reviewed):
    """The point of the pairing: the text lives on the register line, so removing the question
    from the build cannot take it with it."""
    client, set_id, items = reviewed
    target = items[0]["item"]
    text = "We will ask for a 20-day assessment period."

    client.post("/client-boq/review/approve", json={
        "set_id": set_id,
        "decisions": {str(target): "query"},
        "negotiations": {str(target): text},
        "approved": False,
    })
    rfi = next(r for r in client.get(f"/client-boq/rfi/{set_id}").json()["items"]
               if r["register_item"] == target)
    before = client.get(f"/client-boq/rfi/{set_id}").json()["open"]

    resp = client.delete(f"/client-boq/rfi/{set_id}/{rfi['rfi_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["rfi"]["status"] == "withdrawn"
    assert resp.json()["open_queries"] == before - 1

    # Nothing was destroyed: the question is still on the record, and so is the draft.
    after = client.get(f"/client-boq/rfi/{set_id}").json()
    assert any(r["rfi_id"] == rfi["rfi_id"] and r["status"] == "withdrawn" for r in after["items"])
    assert _item(client, set_id, target)["contractor_response"] == text


def test_a_sent_question_cannot_be_withdrawn(reviewed):
    """The client has it. Pretending otherwise would put our register out of step with what
    actually went out."""
    client, set_id, items = reviewed
    client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(items[0]["item"]): "query"}, "approved": False,
    })
    rfi = client.get(f"/client-boq/rfi/{set_id}").json()["items"][0]
    client.post("/client-boq/rfi/batch", json={"set_id": set_id, "ref": "Technical Query No. 1"})

    resp = client.delete(f"/client-boq/rfi/{set_id}/{rfi['rfi_id']}")
    assert resp.status_code == 409
    assert "sent" in resp.json()["detail"] or "draft" in resp.json()["detail"]


def test_withdrawing_an_unknown_question_404s(reviewed):
    client, set_id, _items = reviewed
    assert client.delete(f"/client-boq/rfi/{set_id}/rfi-999").status_code == 404


# ---------------------------------------------------------------------------
# The gate flag rides along with every verdict — a trap worth pinning down
# ---------------------------------------------------------------------------
def test_recording_a_verdict_writes_the_gate_flag_it_is_given(reviewed):
    """`/review/approve` does two jobs: it records verdicts AND it writes the review gate.

    That means a caller recording one row's verdict with `approved: false` REOPENS a closed
    register — which invalidates everything built on it. Callers must pass the gate's current
    state, not a convenient default. This was a real bug in the Register tab, found by walking
    the real tender; the fix is in `tabs/Register.tsx` and this test is why it stays fixed.
    """
    client, set_id, items = reviewed
    client.post("/client-boq/review/approve",
                json={"set_id": set_id, "decisions": {}, "approved": True})
    assert client.get(f"/client-boq/gate/{set_id}").json()["review_approved"] is True

    # Recording another verdict while carrying the gate forward leaves it closed...
    client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(items[0]["item"]): "confirmed"}, "approved": True,
    })
    assert client.get(f"/client-boq/gate/{set_id}").json()["review_approved"] is True

    # ...and sending `false` genuinely reopens it. Documented, not accidental: that is how a
    # register is reopened at all.
    client.post("/client-boq/review/approve", json={
        "set_id": set_id, "decisions": {str(items[1]["item"]): "confirmed"}, "approved": False,
    })
    assert client.get(f"/client-boq/gate/{set_id}").json()["review_approved"] is False


def test_the_route_is_mounted(client):
    paths = set(client.app.openapi()["paths"])  # openapi(), not app.routes — CLAUDE.md trap 1
    assert "/client-boq/rfi/{set_id}/{rfi_id}" in paths
