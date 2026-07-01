"""The n8n webhook hand-off for Gmail drafts is best-effort and never breaks dispatch:
unset URL or a failing POST falls back to the mock outbox; only a 2xx marks the
bundles ``drafted_gmail``.
"""

import httpx
from fastapi.testclient import TestClient

from api import app
from schemas.models import DispatchBundle, DispatchSet

client = TestClient(app)


def _dispatch() -> DispatchSet:
    return DispatchSet(bundles=[
        DispatchBundle(firm_id="A", firm_name="Alpha Ltd", trade="field_testing",
                       bundle_doc_refs=["SR-01.pdf"], email_subject="Enquiry A", email_body="Body A"),
        DispatchBundle(firm_id="B", firm_name="Beta Ltd", trade="geophysical_survey",
                       bundle_doc_refs=["SR-01.pdf"], email_subject="Enquiry B", email_body="Body B"),
    ])


def _send():
    body = {"dispatch": _dispatch().model_dump(mode="json"),
            "project_name": "GE/2026/14 — Ground Investigation", "send": True}
    return client.post("/dispatch", json=body).json()


def test_unset_url_uses_mock_outbox_and_makes_no_http_call(monkeypatch):
    monkeypatch.delenv("N8N_WEBHOOK_URL", raising=False)
    calls: list = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append((a, k)))
    res = _send()
    assert [b["status"] for b in res["bundles"]] == ["sent_mock", "sent_mock"]
    assert calls == []  # the webhook is never attempted when the URL is unset


def test_failing_post_falls_back_to_sent_mock_without_raising(monkeypatch):
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example/webhook/sitesource")

    def boom(*a, **k):
        raise httpx.ConnectError("n8n unreachable")

    monkeypatch.setattr(httpx, "post", boom)
    res = _send()  # must not raise even though the POST throws
    assert [b["status"] for b in res["bundles"]] == ["sent_mock", "sent_mock"]


def test_2xx_post_marks_bundles_drafted_gmail_with_the_expected_payload(monkeypatch):
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example/webhook/sitesource")
    captured: dict = {}

    class _Resp:
        status_code = 200

    def ok(url, json=None, timeout=None):
        captured["url"], captured["json"], captured["timeout"] = url, json, timeout
        return _Resp()

    monkeypatch.setattr(httpx, "post", ok)
    res = _send()
    assert [b["status"] for b in res["bundles"]] == ["drafted_gmail", "drafted_gmail"]
    # the payload n8n receives
    assert captured["url"] == "https://n8n.example/webhook/sitesource"
    assert captured["json"]["project"] == "GE/2026/14"
    drafts = captured["json"]["drafts"]
    assert len(drafts) == 2
    assert drafts[0] == {
        "to": "twl3henner@gmail.com",
        "subject": "Enquiry A",
        "body": "Body A",
        "firm_name": "Alpha Ltd",
        "trade": "field_testing",
        "enclosed": ["SR-01.pdf"],
    }
