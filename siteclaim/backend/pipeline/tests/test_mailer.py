"""Real email transport (Phase A) — gated send, mock-outbox fallback, no network.

The live path is exercised with a fake ``transport`` so the message-building and
address-book logic run with zero sockets. The three fallbacks (DEMO_MODE, dry-run,
unconfigured) each prove no real send happens.
"""

import pytest

from db import seed, store
from db.outbox import read_outbox
from pipeline.stage_03_dispatch.mailer import MailerConfig, build_message, send_bundles
from schemas.models import (
    AttachmentKind,
    BundleAttachment,
    DispatchBundle,
    DispatchSet,
    DispatchStatus,
)

_CONFIG = MailerConfig(host="smtp.example.com", port=587, sender="buying-team@example.com")


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("mailer") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


def _bundle(firm_id="F-EL-02", trade="electrical", attachments=None) -> DispatchBundle:
    return DispatchBundle(
        firm_id=firm_id, firm_name="Vantage E&M Engineering Ltd", trade=trade,
        email_subject="RFQ — Electrical — Kwun Tong", email_body="Please price the enclosed.",
        attachments=attachments or [], status=DispatchStatus.APPROVED,
    )


def test_demo_mode_never_sends_and_records_mock(tmp_path, conn):
    # DEMO_MODE is on in the test env: configured or not, the mailer records only.
    out = tmp_path / "outbox.json"
    sent = send_bundles(DispatchSet(bundles=[_bundle()]), conn=conn, config=_CONFIG, outbox_path=out)
    assert all(b.status is DispatchStatus.SENT_MOCK for b in sent.bundles)


def test_dry_run_forces_mock_even_when_configured(tmp_path, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    out = tmp_path / "outbox.json"
    sent = send_bundles(DispatchSet(bundles=[_bundle()]), conn=conn, config=_CONFIG, dry_run=True, outbox_path=out)
    assert all(b.status is DispatchStatus.SENT_MOCK for b in sent.bundles)


def test_unconfigured_smtp_falls_back_to_mock(tmp_path, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    out = tmp_path / "outbox.json"
    sent = send_bundles(DispatchSet(bundles=[_bundle()]), conn=conn, config=MailerConfig(), outbox_path=out)
    assert all(b.status is DispatchStatus.SENT_MOCK for b in sent.bundles)


def test_live_send_resolves_contact_attaches_files_and_marks_sent(tmp_path, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    sheet = tmp_path / "SoR_electrical.xlsx"
    sheet.write_bytes(b"PK\x03\x04 fake xlsx bytes")
    attachment = BundleAttachment(
        filename="SoR_electrical.xlsx", kind=AttachmentKind.SOR_SHEET, trade="electrical",
        source_path=str(sheet), generated=True,
    )
    captured: list = []
    out = tmp_path / "outbox.json"

    sent = send_bundles(
        DispatchSet(bundles=[_bundle(attachments=[attachment])]),
        conn=conn, config=_CONFIG, transport=lambda cfg, msg: captured.append(msg), outbox_path=out,
    )

    assert sent.bundles[0].status is DispatchStatus.SENT
    assert len(captured) == 1
    message = captured[0]
    assert message["To"] == store.contact_for(conn, "F-EL-02", "electrical").email
    filenames = [a.get_filename() for a in message.iter_attachments()]
    assert "SoR_electrical.xlsx" in filenames  # the real file rode along
    records = read_outbox(out)
    assert records[-1]["status"] == "sent" and records[-1]["to"]


def test_live_send_marks_firm_without_a_contact_failed(tmp_path, conn, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")

    def refuse(cfg, msg):
        raise AssertionError("must not send to a firm with no contact")

    out = tmp_path / "outbox.json"
    sent = send_bundles(
        DispatchSet(bundles=[_bundle(firm_id="F-XX-99")]),
        conn=conn, config=_CONFIG, transport=refuse, outbox_path=out,
    )
    assert sent.bundles[0].status is DispatchStatus.SEND_FAILED
    assert read_outbox(out)[-1]["reason"] == "no contact email (address book or register)"


def test_build_message_carries_body_and_only_existing_files(tmp_path, conn):
    present = tmp_path / "real.pdf"
    present.write_bytes(b"%PDF-1.4")
    attachments = [
        BundleAttachment(filename="real.pdf", kind=AttachmentKind.GENERAL, source_path=str(present)),
        BundleAttachment(filename="ghost.pdf", kind=AttachmentKind.GENERAL, source_path=str(tmp_path / "missing.pdf")),
        BundleAttachment(filename="labelled.pdf", kind=AttachmentKind.GENERAL, source_path=None),
    ]
    contact = store.contact_for(conn, "F-EL-02", "electrical")
    message = build_message(_bundle(attachments=attachments), contact, _CONFIG)
    filenames = [a.get_filename() for a in message.iter_attachments()]
    assert filenames == ["real.pdf"]  # missing and path-less attachments are skipped
    body = message.get_body(preferencelist=("plain",))
    assert "Please price" in body.get_content()
