"""FIX 2 — the machine waits at the outbox by default, and the guard that makes that safe.

Automatic collection is the product. An install that watches nothing and tells the operator to edit
a ``.env`` file has replaced a feature with a configuration instruction.

**The guard had to be rebuilt before the default could flip.** The outbound ledger records the
MESSAGE id returned when a draft is created, and the Gmail API replaces that id when the draft is
sent:

    "When the draft is sent, the draft is automatically deleted and a new message with an updated
    ID is created with the SENT system label."
    "the [drafts] resource is a container that provides a stable ID because the underlying message
    IDs change every time the message is replaced."
    — developers.google.com/workspace/gmail/api/guides/drafts

The operator sends every draft by hand from Gmail, so the ledger missed EVERY time. With
``GMAIL_TEST_RECIPIENT`` addressing each RFQ back to the operator, our own enquiry lands in the
watched mailbox carrying the ref and the blank Schedule of Rates — and would be ingested as a
rateless bid that supersedes the firm's genuine reply on the same ``(firm_id, trade)`` key.

``X-SiteSource-Outbound`` travels WITH the message through the send, so it survives the id change.
It is not the draft's subject, body, recipient chain or human gate — all out of scope and all
untouched — and the operator never sees it.
"""

import base64

import pytest
from pipeline import gmail_client, reply_loop, reply_poller
from pipeline.workspace import Workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work"))
    return Workspace()


@pytest.fixture
def gmail(monkeypatch):
    state = {"messages": [], "fetched": []}

    def list_replies(query, **_kw):
        return state["messages"]

    def get_attachments(mid, **_kw):
        state["fetched"].append(mid)
        return [("SoR_return.xlsx", b"bytes")]

    monkeypatch.setattr(gmail_client, "list_replies", list_replies)
    monkeypatch.setattr(gmail_client, "get_attachments", get_attachments)
    monkeypatch.setattr(gmail_client, "_log", lambda *a, **k: None)
    return state


def _msg(mid, ref="t.F1.gi", outbound=""):
    return {"id": mid, "subject": f"Re: RFQ [SiteSource Ref: {ref}]", "outbound": outbound}


# ---------------------------------------------------------------------------
# The default
# ---------------------------------------------------------------------------
def test_polling_is_on_when_gmail_is_connected_and_nothing_is_set(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.delenv("GMAIL_POLLING_ENABLED", raising=False)
    monkeypatch.setattr(gmail_client, "credentials_configured", lambda: True)
    assert reply_poller.polling_enabled() is True


def test_an_unconfigured_install_does_not_poll(monkeypatch):
    """No credential means nothing to poll and every tick would be a failure — an install that
    logs errors in a loop is worse than one that says nothing."""
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.delenv("GMAIL_POLLING_ENABLED", raising=False)
    monkeypatch.setattr(gmail_client, "credentials_configured", lambda: False)
    assert reply_poller.polling_enabled() is False


def test_demo_forces_it_off_even_with_a_credential(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(gmail_client, "credentials_configured", lambda: True)
    monkeypatch.delenv("GMAIL_POLLING_ENABLED", raising=False)
    assert reply_poller.polling_enabled() is False
    monkeypatch.setenv("GMAIL_POLLING_ENABLED", "true")
    assert reply_poller.polling_enabled() is False       # explicit ON loses to DEMO


@pytest.mark.parametrize("raw", ["false", "FALSE", " no ", "0"])
def test_the_override_still_turns_it_off(monkeypatch, raw):
    """Both directions, as the brief requires. An operator who does not want it watching says so
    and is obeyed."""
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.setattr(gmail_client, "credentials_configured", lambda: True)
    monkeypatch.setenv("GMAIL_POLLING_ENABLED", raw)
    assert reply_poller.polling_enabled() is False


@pytest.mark.parametrize("raw", ["true", "TRUE", " yes ", "1"])
def test_the_override_still_turns_it_on_without_a_credential(monkeypatch, raw):
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.setattr(gmail_client, "credentials_configured", lambda: False)
    monkeypatch.setenv("GMAIL_POLLING_ENABLED", raw)
    assert reply_poller.polling_enabled() is True


# ---------------------------------------------------------------------------
# The header — what makes default-on safe
# ---------------------------------------------------------------------------
def test_the_outbound_header_is_stamped_on_the_draft():
    raw = gmail_client._mime_raw("op@x.com", "RFQ [SiteSource Ref: t.F1.gi]", "body", [],
                                 ref="t.F1.gi")
    mime = base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
    assert f"{gmail_client.OUTBOUND_HEADER}: t.F1.gi" in mime


def test_no_ref_stamps_no_header():
    """A draft with no correlation ref gets no header rather than an empty one — an empty header
    would be a claim about a message we cannot identify."""
    raw = gmail_client._mime_raw("op@x.com", "s", "b", [])
    mime = base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
    assert gmail_client.OUTBOUND_HEADER not in mime


def test_our_own_message_is_skipped_on_the_header_alone(ws, gmail):
    """The case the ledger CANNOT catch: the message id changed when the draft was sent, so it is
    not in the ledger — and the header still identifies it."""
    gmail["messages"] = [_msg("m-sent-new-id", outbound="t.F1.gi"), _msg("m-reply")]
    seen: list[str] = []

    summary = reply_poller.poll_once(
        lambda ref, atts: (seen.append(ref), "matched")[1], workspace=ws)

    assert summary["own"] == 1
    assert summary["processed"] == 1
    assert seen == ["t.F1.gi"]                  # the REPLY only
    assert gmail["fetched"] == ["m-reply"]      # our own attachment was never downloaded


def test_the_ledger_still_works_as_a_second_signal(ws, gmail):
    """Kept rather than deleted: it catches a draft that was never sent but is somehow listed, and
    two independent guards on a data-corrupting failure is the right number."""
    reply_loop.record_outbound(ws, "m-never-sent")
    gmail["messages"] = [_msg("m-never-sent")]          # no header on this one
    summary = reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    assert summary["own"] == 1 and summary["processed"] == 0


def test_a_genuine_reply_carries_no_header_and_is_processed(ws, gmail):
    """The guard must not eat the thing it exists to protect. A subcontractor's reply is composed
    in their own mail client and cannot carry our header."""
    gmail["messages"] = [_msg("m-reply")]
    summary = reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    assert summary["own"] == 0 and summary["processed"] == 1


def test_the_header_travels_on_the_created_draft(monkeypatch):
    """End of the outbound path: `create_gmail_drafts` passes the enquiry's ref, so the stamp is on
    the message Gmail stores — and therefore on the message it sends."""
    from pipeline.stage_03_dispatch.drafts import create_gmail_drafts

    captured: dict = {}

    class Drafts:
        def create(self, userId, body):
            captured["raw"] = body["message"]["raw"]

            class R:
                def execute(_s):
                    return {"id": "D1", "message": {"id": "M1"}}
            return R()

    class Svc:
        def users(self):
            return type("U", (), {"drafts": lambda _s: Drafts()})()

    monkeypatch.setattr(gmail_client, "_log", lambda *a, **k: None)
    create_gmail_drafts(
        [{"firm_id": "F1", "to": "op@x.com", "subject": "RFQ", "body": "b",
          "ref": "t.F1.gi", "attachments": []}],
        service=Svc())
    mime = base64.urlsafe_b64decode(captured["raw"]).decode("utf-8", "replace")
    assert f"{gmail_client.OUTBOUND_HEADER}: t.F1.gi" in mime


def test_list_replies_surfaces_the_header(monkeypatch):
    """`poll_once` can only skip on what `list_replies` returns, so the header has to be requested
    in the metadata read — not merely present on the message."""
    asked: dict = {}

    class Messages:
        def list(self, userId, q, maxResults):
            return type("C", (), {"execute": lambda _s: {"messages": [{"id": "m1"}]}})()

        def get(self, userId, id, format, metadataHeaders):
            asked["headers"] = metadataHeaders
            return type("C", (), {"execute": lambda _s: {"payload": {"headers": [
                {"name": "Subject", "value": "Re: RFQ"},
                {"name": gmail_client.OUTBOUND_HEADER, "value": "t.F1.gi"},
            ]}}})()

    class Svc:
        def users(self):
            return type("U", (), {"messages": lambda _s: Messages()})()

    out = gmail_client.list_replies("q", service=Svc())
    assert gmail_client.OUTBOUND_HEADER in asked["headers"]
    assert out == [{"id": "m1", "subject": "Re: RFQ", "outbound": "t.F1.gi"}]
