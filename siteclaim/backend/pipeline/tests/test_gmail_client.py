"""Gmail client (the n8n replacement) — fully offline: every test drives a STUB service (the
Google builder-chain shape), no Google SDK import, no socket. The suite environment deliberately
has no google-* packages installed, so these tests also prove the lazy-import invariant."""

import base64
from email import message_from_bytes

import pytest

from pipeline.gmail_client import (
    GmailUnavailable,
    create_draft,
    credentials_configured,
    get_attachments,
    list_replies,
    token_path,
)


# -- a stub of the Gmail API builder chain (users().drafts().create(...).execute()) ----------
class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class StubService:
    """Programmable Gmail service: records calls, returns scripted results per method."""

    def __init__(self, *, draft_result=None, list_result=None, get_results=None, attachment_results=None):
        self.calls: list[tuple[str, dict]] = []
        self._draft_result = draft_result if draft_result is not None else {"id": "draft-1"}
        self._list_result = list_result or {"messages": []}
        self._get_results = dict(get_results or {})       # message_id -> result
        self._attachment_results = dict(attachment_results or {})  # attachment_id -> result

    def users(self):
        return self

    def drafts(self):
        return self

    def messages(self):
        return self

    def attachments(self):
        return self

    def create(self, userId, body):
        self.calls.append(("drafts.create", {"userId": userId, "body": body}))
        return _Call(self._draft_result)

    def list(self, userId, q, maxResults):
        self.calls.append(("messages.list", {"userId": userId, "q": q, "maxResults": maxResults}))
        return _Call(self._list_result)

    def get(self, userId, id, **kwargs):  # noqa: A002 — the Gmail API's own parameter name
        if "messageId" in kwargs:  # attachments().get(userId, messageId, id)
            self.calls.append(("attachments.get", {"messageId": kwargs["messageId"], "id": id}))
            return _Call(self._attachment_results[id])
        self.calls.append(("messages.get", {"id": id, **kwargs}))
        return _Call(self._get_results[id])


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


# -- create_draft ----------------------------------------------------------------------------
def test_create_draft_builds_the_full_mime_message_and_returns_the_draft_id():
    svc = StubService(draft_result={"id": "d-42"})
    draft_id = create_draft(
        "firm@example.hk", "RFQ [SiteSource Ref: ge-2026-14.f1.ground_investigation:H]",
        "Please price the attached section.", [("SoR_gi_Section_H.pdf", b"%PDF-1.4 slice")],
        service=svc,
    )
    assert draft_id == "d-42"
    (name, payload), = svc.calls
    assert name == "drafts.create" and payload["userId"] == "me"
    raw = payload["body"]["message"]["raw"]
    msg = message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg["To"] == "firm@example.hk"
    assert "SiteSource Ref: ge-2026-14.f1.ground_investigation:H" in msg["Subject"]
    parts = list(msg.walk())
    body_text = next(p for p in parts if p.get_content_type() == "text/plain").get_payload(decode=True)
    assert b"Please price the attached section." in body_text
    att = next(p for p in parts if p.get_filename() == "SoR_gi_Section_H.pdf")
    assert att.get_payload(decode=True) == b"%PDF-1.4 slice"       # attachment bytes round-trip
    assert att.get_content_type() == "application/pdf"


def test_create_draft_wraps_an_api_error_in_the_typed_failure():
    svc = StubService(draft_result=RuntimeError("503 backend error"))
    with pytest.raises(GmailUnavailable, match="draft creation failed"):
        create_draft("a@b.c", "s", "b", [], service=svc)


def test_create_draft_without_credentials_raises_the_actionable_unavailable(monkeypatch, tmp_path):
    # No injected service and no token/libs -> the typed failure with a fix, never a raw crash.
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "absent.json"))
    with pytest.raises(GmailUnavailable):
        create_draft("a@b.c", "s", "b", [])


# -- list_replies / get_attachments -----------------------------------------------------------
def test_list_replies_returns_id_and_subject_and_applies_the_after_filter():
    svc = StubService(
        list_result={"messages": [{"id": "m1"}, {"id": "m2"}]},
        get_results={
            "m1": {"payload": {"headers": [{"name": "Subject", "value": "Re: RFQ [SiteSource Ref: r1]"}]}},
            "m2": {"payload": {"headers": [{"name": "Subject", "value": "Re: RFQ [SiteSource Ref: r2]"}]}},
        },
    )
    out = list_replies('subject:"SiteSource Ref" has:attachment', after=1_700_000_000, service=svc)
    assert [(m["id"], m["subject"]) for m in out] == [
        ("m1", "Re: RFQ [SiteSource Ref: r1]"), ("m2", "Re: RFQ [SiteSource Ref: r2]"),
    ]
    q = next(p["q"] for n, p in svc.calls if n == "messages.list")
    assert q.endswith("after:1700000000")                       # the incremental filter applied


def test_get_attachments_walks_nested_parts_and_decodes_by_attachment_id():
    svc = StubService(
        get_results={"m1": {"payload": {
            "filename": "", "body": {},
            "parts": [
                {"filename": "", "body": {"data": _b64url(b"body text")}, "mimeType": "text/plain"},
                {"filename": "", "parts": [  # a nested multipart holding the real attachment
                    {"filename": "return.xlsx", "body": {"attachmentId": "att-1"}},
                    {"filename": "inline.pdf", "body": {"data": _b64url(b"%PDF inline")}},
                ]},
            ],
        }}},
        attachment_results={"att-1": {"data": _b64url(b"PK-xlsx-bytes")}},
    )
    out = get_attachments("m1", service=svc)
    assert ("return.xlsx", b"PK-xlsx-bytes") in out             # fetched via attachments().get
    assert ("inline.pdf", b"%PDF inline") in out                 # small inline part decoded directly
    assert len(out) == 2                                         # the bodiless/no-filename parts skipped


# -- configuration surface ---------------------------------------------------------------------
def test_token_path_and_credentials_configured_read_the_env(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert credentials_configured() is False
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert credentials_configured() is True
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "tok.json"))
    assert token_path() == tmp_path / "tok.json"
