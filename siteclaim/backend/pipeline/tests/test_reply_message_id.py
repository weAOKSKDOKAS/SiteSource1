"""A reply records the Gmail message it came from — so our own RFQ can be told apart, after.

A stored reply record held `{reply, received_at, status}` and nothing else, so there was no link
back to the message. The outbound ledger is keyed by MESSAGE ID and the reply file had none to
match against: even a CURRENT self-ingest could not be identified afterwards. Five of the
operator's own dispatched RFQs sat in a comparison as returns from nobody, and nothing on the
record could say so.

Those five predate the ledger and cannot be recovered — accepted, and no cleanup tool is built.
What this closes is the next one.

**A LABEL AND NOTHING MORE.** Nothing is deleted, nothing is auto-withdrawn, and the comparison is
untouched by the labelling — withdrawing stays the operator's only way to change it. Asserted
below, because a "helpful" auto-withdraw is exactly the behaviour this must never grow.
"""

import pytest

from pipeline import reply_loop, reply_poller
from pipeline.workspace import Workspace
from schemas.models import BidLineItem, BidReply

TENDER = "gi-2026-17"


def _reply(firm="F1", trade="ground_investigation:G", rate=850.0):
    return BidReply(firm_id=firm, trade=trade,
                    line_items=[BidLineItem(item_ref="G1", rate=rate)])


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    return Workspace()


# -- the id round-trips ------------------------------------------------------------------------------
def test_the_message_id_is_stored_on_the_record(ws):
    reply_loop.accumulate_replies(ws, TENDER, [_reply()], message_id="msg-123")
    rec, = reply_loop.tender_reply_records(ws, TENDER)
    assert rec["message_id"] == "msg-123"


def test_a_manual_upload_honestly_carries_no_message_id(ws):
    """An upload has no Gmail message. Empty is the truth; inventing one would be worse."""
    reply_loop.accumulate_replies(ws, TENDER, [_reply()])
    rec, = reply_loop.tender_reply_records(ws, TENDER)
    assert rec["message_id"] == ""


def test_an_old_record_with_no_message_id_still_loads(ws):
    """Every reply file written before this must load unchanged — the field is additive."""
    from pipeline.reply_loop import _replies_path, _write_json

    _write_json(_replies_path(ws, TENDER), [
        {"reply": _reply().model_dump(), "received_at": "2026-08-06T00:00:00Z", "status": "active"},
    ])
    records = reply_loop.tender_reply_records(ws, TENDER)
    assert records[0].get("message_id", "") == ""
    assert [r.firm_id for r in reply_loop.tender_replies(ws, TENDER)] == ["F1"]


def test_superseding_keeps_each_record_s_own_id(ws):
    """History stays traceable per message, not collapsed onto the latest."""
    reply_loop.accumulate_replies(ws, TENDER, [_reply(rate=10.0)], message_id="msg-1")
    reply_loop.accumulate_replies(ws, TENDER, [_reply(rate=99.0)], message_id="msg-2")

    by_status = {r["status"]: r["message_id"] for r in reply_loop.tender_reply_records(ws, TENDER)}
    assert by_status == {"superseded": "msg-1", "active": "msg-2"}


# -- the label, on the endpoint ------------------------------------------------------------------------
def test_a_reply_from_our_own_outbound_message_is_labelled(ws):
    import api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    reply_loop.record_outbound(ws, "msg-ours", ref="r-1", to="ops@example.com")
    reply_loop.accumulate_replies(ws, TENDER, [_reply()], message_id="msg-ours")

    body = client.get(f"/tender/{TENDER}/replies").json()
    assert body["replies"][0]["own_outbound"] is True


def test_a_genuine_reply_is_not_labelled(ws):
    import api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    reply_loop.record_outbound(ws, "msg-ours", ref="r-1", to="ops@example.com")
    reply_loop.accumulate_replies(ws, TENDER, [_reply()], message_id="msg-from-a-firm")

    body = client.get(f"/tender/{TENDER}/replies").json()
    assert body["replies"][0]["own_outbound"] is False


def test_a_record_with_no_id_is_never_labelled(ws):
    """The five from this morning. No id, no claim — not "probably ours"."""
    import api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    reply_loop.record_outbound(ws, "msg-ours", ref="r-1", to="ops@example.com")
    reply_loop.accumulate_replies(ws, TENDER, [_reply()])

    body = client.get(f"/tender/{TENDER}/replies").json()
    assert body["replies"][0]["own_outbound"] is False


def test_labelling_changes_nothing_about_the_comparison(ws):
    """The whole safety of this change: a label is not an action.

    An own-outbound record stays ACTIVE and stays in the levelled set until a person withdraws it.
    Auto-withdrawing would be a price silently leaving a comparison, which is the failure mode the
    withdraw gate exists to prevent — even when the price is one we sent ourselves.
    """
    import api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    reply_loop.record_outbound(ws, "msg-ours", ref="r-1", to="ops@example.com")
    reply_loop.accumulate_replies(ws, TENDER, [_reply()], message_id="msg-ours")

    body = client.get(f"/tender/{TENDER}/replies").json()
    assert body["replies"][0]["status"] == "active"          # still active…
    assert body["reply_count"] == 1                          # …still counted…
    assert [r.firm_id for r in reply_loop.tender_replies(ws, TENDER)] == ["F1"]  # …still levelled
    # …and only the operator's own withdraw takes it out.
    assert client.post(f"/tender/{TENDER}/replies/withdraw",
                       json={"firm_id": "F1", "package_key": "ground_investigation:G"}).status_code == 200
    assert reply_loop.tender_replies(ws, TENDER) == []


# -- the poller hands the id over ------------------------------------------------------------------------
def test_the_poller_passes_the_message_id_to_a_processor_that_wants_it():
    seen = {}

    def process(ref, attachments, message_id=""):
        seen["ref"], seen["message_id"] = ref, message_id
        return "matched"

    assert reply_poller._accepts_message_id(process) is True
    process("r-1", [], message_id="msg-9")
    assert seen == {"ref": "r-1", "message_id": "msg-9"}


def test_a_processor_that_does_not_want_it_is_called_unchanged():
    """The protocol is a plain `(ref, attachments) -> str` callable that tests supply their own
    version of. A third positional would have broken every one of them."""
    def process(ref, attachments):
        return "matched"

    assert reply_poller._accepts_message_id(process) is False


def test_the_real_processor_declares_it():
    import api

    assert reply_poller._accepts_message_id(api._poller_process_reply) is True
