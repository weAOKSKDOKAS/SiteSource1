"""GMAIL_TEST_RECIPIENT on EVERY outbound path, not only on drafts.

The valve existed on the Gmail draft path and nowhere else. The SMTP path — `mailer.send_bundles`,
behind `POST /dispatch` with `send: true` — never read it, so with `SMTP_HOST` configured and
`DEMO_MODE` off, one button emailed real subcontractors while an operator believed a live-testing
override was protecting them.

That is worse than having no valve. It covered the reversible route (a draft sits in your own
mailbox and can be deleted) and left the irreversible one open (an SMTP send cannot be recalled),
and its existence read as protection.

Every test here asserts the same thing from a different angle: **with the override set, no address
belonging to a real firm survives to anywhere it could be sent to, or recorded as though it had
been.**
"""

import json

import pytest
from fastapi.testclient import TestClient

from api import app
from pipeline.stage_03_dispatch import mailer
from schemas.models import DispatchBundle, DispatchSet, DispatchStatus

client = TestClient(app)

OVERRIDE = "operator@example.com"
REAL = "estimating@a-real-subcontractor.example"


@pytest.fixture
def live(monkeypatch, tmp_path):
    """Off-demo and fully SMTP-configured — the only combination that opens a socket, which is
    exactly the combination the valve has to cover."""
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    # `SMTP_FROM`, not `SMTP_SENDER` — `MailerConfig.from_env` reads the former (falling back to
    # SMTP_USER). Getting this wrong makes `configured` false, which degrades every "live" test to
    # the mock outbox and passes for the wrong reason.
    monkeypatch.setenv("SMTP_FROM", "tenders@maincontractor.example")
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    return tmp_path


class _Capture:
    """Stands in for `_smtplib_transport` — every message that would have gone out, kept. No
    socket is opened, and nothing here needs one: the To header is the thing under test."""

    def __init__(self):
        self.sent = []

    def __call__(self, config, message):
        self.sent.append(message)


def _bundles(*firm_ids):
    return DispatchSet(bundles=[
        DispatchBundle(firm_id=f, firm_name=f"Firm {f}", trade="general",
                       email_subject=f"RFQ [SiteSource Ref: t.{f}.general]", email_body="please price")
        for f in firm_ids
    ])


def _with_register_email():
    """A real firm from the committed register that has an enquiry address and no contacts row —
    the register-FALLBACK path, which is where the recipient bug lived."""
    from db import store

    conn = store.get_connection()
    row = conn.execute(
        "SELECT f.firm_id, f.enquiry_email FROM firms f LEFT JOIN contacts c ON c.firm_id = f.firm_id "
        "WHERE f.enquiry_email != '' AND c.firm_id IS NULL LIMIT 1"
    ).fetchone()
    conn.close()
    return row["firm_id"], row["enquiry_email"]


# -- the policy itself --------------------------------------------------------------------------
def test_the_override_has_one_owner(monkeypatch):
    """Two copies of a safety rule is how one of them comes to be forgotten — which is what
    happened. `api.py` reads the policy from here rather than re-deriving it."""
    import api

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    assert mailer.test_recipient() == OVERRIDE
    assert api.mailer_test_recipient is mailer.test_recipient


def test_demo_forces_the_valve_off(monkeypatch):
    """DEMO sends nothing, so a redirect notice there would be a claim about work that never
    happened."""
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    assert mailer.test_recipient() == ""


def test_unset_is_off(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.delenv("GMAIL_TEST_RECIPIENT", raising=False)
    assert mailer.test_recipient() == ""


def test_whitespace_only_is_off_not_an_empty_recipient(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", "   ")
    assert mailer.test_recipient() == ""


# -- PATH 1: the SMTP send (the one that was open) ----------------------------------------------
def test_smtp_no_real_address_survives_to_the_wire(live, monkeypatch):
    firm_id, real_email = _with_register_email()
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    transport = _Capture()

    out = mailer.send_bundles(_bundles(firm_id), transport=transport,
                              outbox_path=live / "outbox.json")

    assert len(transport.sent) == 1
    assert transport.sent[0]["To"] == OVERRIDE
    assert real_email not in str(transport.sent[0])          # nowhere in the MIME message at all
    assert all(b.status == DispatchStatus.SENT for b in out.bundles)


def test_smtp_without_the_override_still_reaches_the_register_address(live, monkeypatch):
    """The valve is opt-in. With it off, the recipient chain is byte-for-byte what it was."""
    firm_id, real_email = _with_register_email()
    monkeypatch.delenv("GMAIL_TEST_RECIPIENT", raising=False)
    transport = _Capture()

    mailer.send_bundles(_bundles(firm_id), transport=transport, outbox_path=live / "outbox.json")

    assert transport.sent[0]["To"] == real_email


def test_smtp_a_firm_with_no_address_at_all_is_redirected_too(live, monkeypatch):
    """Matching the drafts path exactly. A valve that redirects some firms and fails others is one
    an operator has to reason about — and a safety valve you have to reason about is one you
    eventually get wrong."""
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    transport = _Capture()

    out = mailer.send_bundles(_bundles("F-NO-SUCH-FIRM"), transport=transport,
                              outbox_path=live / "outbox.json")

    assert transport.sent[0]["To"] == OVERRIDE
    assert out.bundles[0].status == DispatchStatus.SENT          # not send_failed


def test_smtp_without_the_override_an_unknown_firm_still_fails_loudly(live, monkeypatch):
    monkeypatch.delenv("GMAIL_TEST_RECIPIENT", raising=False)
    transport = _Capture()

    out = mailer.send_bundles(_bundles("F-NO-SUCH-FIRM"), transport=transport,
                              outbox_path=live / "outbox.json")

    assert transport.sent == []                                   # nothing was sent
    assert out.bundles[0].status == DispatchStatus.SEND_FAILED    # and it says so


def test_smtp_says_so_on_the_response_so_the_ui_can_show_it(live, monkeypatch):
    firm_id, _ = _with_register_email()
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)

    out = mailer.send_bundles(_bundles(firm_id), transport=_Capture(),
                              outbox_path=live / "outbox.json")

    assert out.notice.startswith("TEST MODE")
    assert OVERRIDE in out.notice


def test_smtp_a_normal_run_carries_no_notice(live, monkeypatch):
    firm_id, _ = _with_register_email()
    monkeypatch.delenv("GMAIL_TEST_RECIPIENT", raising=False)

    out = mailer.send_bundles(_bundles(firm_id), transport=_Capture(),
                              outbox_path=live / "outbox.json")

    assert out.notice == ""


# -- PATH 1b: the audit trail must not record an address that was never used --------------------
def test_the_outbox_records_what_was_used_and_what_it_replaced(live, monkeypatch):
    firm_id, real_email = _with_register_email()
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    path = live / "outbox.json"

    mailer.send_bundles(_bundles(firm_id), transport=_Capture(), outbox_path=path)

    record = json.loads(path.read_text(encoding="utf-8"))[0]
    assert record["to"] == OVERRIDE                  # what actually went
    assert record["test_mode"] is True               # so a reader can tell a test run from a real one
    assert record["redirected_from"] == real_email   # and what it replaced


def test_the_outbox_of_a_normal_run_is_unchanged(live, monkeypatch):
    firm_id, real_email = _with_register_email()
    monkeypatch.delenv("GMAIL_TEST_RECIPIENT", raising=False)
    path = live / "outbox.json"

    mailer.send_bundles(_bundles(firm_id), transport=_Capture(), outbox_path=path)

    record = json.loads(path.read_text(encoding="utf-8"))[0]
    assert record["to"] == real_email
    assert "test_mode" not in record and "redirected_from" not in record


def test_the_register_fallback_path_does_not_raise(live, monkeypatch):
    """It did. The success record read `contact.email`, and on the register-fallback path
    `contact` is None — so a firm whose address came from the register (rather than the address
    book) crashed the whole send with an AttributeError, after its message had gone out."""
    firm_id, _ = _with_register_email()
    monkeypatch.delenv("GMAIL_TEST_RECIPIENT", raising=False)

    out = mailer.send_bundles(_bundles(firm_id), transport=_Capture(),
                              outbox_path=live / "outbox.json")

    assert out.bundles[0].status == DispatchStatus.SENT


# -- PATH 2: the mock outbox (degraded send) ----------------------------------------------------
def test_the_mock_outbox_never_records_an_address_at_all(live, monkeypatch):
    """Unconfigured SMTP degrades to recording rather than sending. Nothing leaves, and the record
    carries no recipient — so there is nothing for the valve to redirect and nothing to leak."""
    firm_id, real_email = _with_register_email()
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    path = live / "outbox.json"

    out = mailer.send_bundles(_bundles(firm_id), transport=_Capture(), outbox_path=path)

    assert all(b.status == DispatchStatus.SENT_MOCK for b in out.bundles)
    assert real_email not in path.read_text(encoding="utf-8")


def test_dry_run_opens_no_socket_even_with_smtp_configured(live, monkeypatch):
    firm_id, _ = _with_register_email()
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    transport = _Capture()

    out = mailer.send_bundles(_bundles(firm_id), transport=transport, dry_run=True,
                              outbox_path=live / "outbox.json")

    assert transport.sent == []
    assert all(b.status == DispatchStatus.SENT_MOCK for b in out.bundles)


# -- PATH 3: the endpoint, end to end -----------------------------------------------------------
def test_post_dispatch_send_true_redirects_and_reports(live, monkeypatch):
    """The button that was open. `POST /dispatch {send: true}` is the only caller of
    `send_bundles`, and it is reachable from the desk's Sourcing tab."""
    firm_id, real_email = _with_register_email()
    monkeypatch.setenv("GMAIL_TEST_RECIPIENT", OVERRIDE)
    transport = _Capture()
    monkeypatch.setattr("api.build_dispatch", lambda *a, **k: _bundles(firm_id))
    monkeypatch.setattr("pipeline.stage_03_dispatch.mailer._smtplib_transport", transport)

    body = client.post("/dispatch", json={
        "shortlist": {"per_trade": {}}, "approvals": {}, "send": True,
    }).json()

    assert body["notice"].startswith("TEST MODE") and OVERRIDE in body["notice"]
    assert transport.sent and transport.sent[0]["To"] == OVERRIDE
    assert real_email not in json.dumps(body)      # nowhere on the response either
