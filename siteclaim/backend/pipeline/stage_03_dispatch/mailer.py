"""Real email transport for dispatched bundles (Phase A) — stdlib SMTP.

The mock outbox (:mod:`db.outbox`) records "sent" bundles to a JSON file and never
touches the network; it is the offline/demo transport. This module is its live
counterpart: it builds a real MIME email per bundle, attaches the routed files
(:class:`~schemas.models.BundleAttachment`), resolves the recipient from the
address book (:func:`db.store.contact_for`), and hands it to an SMTP server.

Sending real email to a real subcontractor is outward-facing and hard to take back,
so it is gated three ways. ``send_bundles`` opens a socket only when **all** of these
hold: ``DEMO_MODE`` is off, ``dry_run`` is False, and SMTP is configured
(``SMTP_HOST`` set). Any one of them missing routes to the mock outbox instead, so a
misconfigured or offline run degrades to recording, never to a surprise blast.

``smtplib`` is imported lazily inside the transport, so importing this module — and
the entire DEMO_MODE path — never even loads it. A ``transport`` seam lets the
message-building and address-book logic be exercised with no network at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from email.message import EmailMessage
from mimetypes import guess_type
from pathlib import Path
from typing import Callable, Optional
import sqlite3

from db import store
from db.outbox import OUTBOX_PATH, send_mock
from pipeline.llm_client import demo_mode
from schemas.models import (
    BundleAttachment,
    Contact,
    DispatchBundle,
    DispatchSet,
    DispatchStatus,
)

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class MailerConfig:
    """SMTP settings, read from the environment (see ``.env.example``)."""

    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    sender: str = ""
    use_starttls: bool = True

    @classmethod
    def from_env(cls) -> "MailerConfig":
        return cls(
            host=os.getenv("SMTP_HOST", "").strip(),
            port=int(os.getenv("SMTP_PORT", "587").strip() or "587"),
            username=os.getenv("SMTP_USER", "").strip(),
            password=os.getenv("SMTP_PASSWORD", ""),
            sender=os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
            use_starttls=os.getenv("SMTP_STARTTLS", "true").strip().lower() in _TRUTHY,
        )

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)


# ---------------------------------------------------------------------------
# Message building (pure — no socket, unit-testable)
# ---------------------------------------------------------------------------
def _attach_file(msg: EmailMessage, attachment: BundleAttachment) -> bool:
    """Attach ``attachment`` if its real file exists. Return True if attached."""
    if not attachment.source_path:
        return False
    path = Path(attachment.source_path)
    if not path.is_file():
        return False
    maintype, subtype = (guess_type(path.name)[0] or "application/octet-stream").split("/", 1)
    msg.add_attachment(
        path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name
    )
    return True


def build_message(bundle: DispatchBundle, contact: Contact, config: MailerConfig) -> EmailMessage:
    """Build the MIME email for one bundle: composed body + the routed real files."""
    msg = EmailMessage()
    msg["From"] = config.sender
    msg["To"] = contact.email
    msg["Subject"] = bundle.email_subject
    msg.set_content(bundle.email_body or "")
    for attachment in bundle.attachments:
        _attach_file(msg, attachment)
    return msg


# ---------------------------------------------------------------------------
# Transport (the only place a socket is opened)
# ---------------------------------------------------------------------------
def _smtplib_transport(config: MailerConfig, message: EmailMessage) -> None:
    import smtplib  # lazy — the DEMO/dry-run path never imports it

    with smtplib.SMTP(config.host, config.port, timeout=30) as server:
        if config.use_starttls:
            server.starttls()
        if config.username:
            server.login(config.username, config.password)
        server.send_message(message)


Transport = Callable[[MailerConfig, EmailMessage], None]


def _record(outbox_path: Path | str, records: list[dict]) -> None:
    from db.outbox import read_outbox  # reuse the outbox JSON reader/writer shape
    import json

    existing = read_outbox(outbox_path)
    existing.extend(records)
    path = Path(outbox_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")


def _live_enabled(dry_run: bool, config: MailerConfig) -> bool:
    """Real send happens only off-demo, not dry-run, and fully configured."""
    return not demo_mode() and not dry_run and config.configured


def send_bundles(
    dispatch_set: DispatchSet,
    *,
    conn: Optional[sqlite3.Connection] = None,
    config: Optional[MailerConfig] = None,
    dry_run: bool = False,
    outbox_path: Path | str = OUTBOX_PATH,
    transport: Optional[Transport] = None,
) -> DispatchSet:
    """Send (or mock-send) every bundle and return the set with updated statuses.

    Offline, dry-run, or unconfigured → the mock outbox (:func:`db.outbox.send_mock`),
    every bundle ``sent_mock``. Live → a real email per bundle: a firm with an
    address-book contact is emailed with its attachments and marked ``sent``; a firm
    with **no contact** is marked ``send_failed`` (never silently dropped) and the run
    continues. Every outcome is appended to the outbox JSON for the audit trail.
    """
    config = config or MailerConfig.from_env()
    if not _live_enabled(dry_run, config):
        return send_mock(dispatch_set, outbox_path=outbox_path)

    transport = transport or _smtplib_transport
    own_conn = conn is None
    conn = conn or store.get_connection()
    sent_bundles: list[DispatchBundle] = []
    records: list[dict] = []
    try:
        for bundle in dispatch_set.bundles:
            contact = store.contact_for(conn, bundle.firm_id, bundle.trade)
            if contact is None:
                sent_bundles.append(bundle.model_copy(update={"status": DispatchStatus.SEND_FAILED}))
                records.append({
                    "firm_id": bundle.firm_id, "firm_name": bundle.firm_name, "trade": bundle.trade,
                    "status": DispatchStatus.SEND_FAILED.value, "reason": "no address-book contact",
                })
                continue
            message = build_message(bundle, contact, config)
            attached = [a.filename for a in bundle.attachments if a.source_path and Path(a.source_path).is_file()]
            transport(config, message)
            sent_bundles.append(bundle.model_copy(update={"status": DispatchStatus.SENT}))
            records.append({
                "firm_id": bundle.firm_id, "firm_name": bundle.firm_name, "trade": bundle.trade,
                "to": contact.email, "email_subject": bundle.email_subject,
                "attachments": attached, "status": DispatchStatus.SENT.value,
            })
    finally:
        if own_conn:
            conn.close()

    _record(outbox_path, records)
    return DispatchSet(bundles=sent_bundles)
