"""Gmail API client — drafts out, reply polling in; the n8n replacement (transport only).

Both email directions used to ride an n8n instance (a Gmail-draft webhook outbound, a Gmail
trigger inbound) that failed repeatedly in production (ConnectionRefused with n8n down, OAuth
tokens expiring weekly in Testing mode, the trigger silently not firing) and required a second
always-on process. This module calls the Gmail API directly from the backend instead:

* :func:`create_draft` — one Gmail DRAFT per approved enquiry (the human gate holds: a draft is
  never auto-sent; the operator reviews and sends from Gmail).
* :func:`list_replies` / :func:`get_attachments` — the reply poller's read side: find messages
  carrying the ``[SiteSource Ref: …]`` correlation tag and download their attachments, which feed
  the EXISTING ``/inbound-reply`` processing path (this module transports bytes; it decides
  nothing).

Credentials come from the environment, never hardcoded: ``GOOGLE_CLIENT_ID`` +
``GOOGLE_CLIENT_SECRET`` (the operator's Google Cloud OAuth client) and ``GMAIL_TOKEN_PATH`` (a
token file this module refreshes automatically; default ``backend/.gmail_token.json``,
gitignored). The one-time consent flow that writes the token:

    python -m pipeline.gmail_client   # opens a browser once; writes GMAIL_TOKEN_PATH

The OAuth consent screen must be PUBLISHED to Production in the Google Cloud console — a Testing
consent screen expires its refresh tokens after 7 days (the recurring n8n pain).

All Google imports are LAZY: DEMO_MODE and the test suite never import a Google SDK or open a
socket. Any missing/invalid credential raises the typed :class:`GmailUnavailable` with an
actionable message — callers degrade gracefully (a Gmail failure never fails the dispatch).
Every call is logged one-line to stdout and, when ``SITESOURCE_GMAIL_LOG`` names a file, as a
JSONL record — debuggable without a browser.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

# Drafts need compose; the poller only reads (dedupe is on message id, so no read-marker and no
# modify scope). A token authorised for different scopes must be re-consented.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
]

_DEFAULT_TOKEN_PATH = Path(__file__).resolve().parents[1] / ".gmail_token.json"


class GmailUnavailable(RuntimeError):
    """Gmail cannot be reached with the current configuration. The message says exactly what to
    fix (missing libs / credentials / token / expired consent) — callers surface it and degrade;
    they never crash the dispatch or the poller loop."""


def token_path() -> Path:
    """Where the OAuth token lives (``GMAIL_TOKEN_PATH``, default ``backend/.gmail_token.json``)."""
    raw = os.getenv("GMAIL_TOKEN_PATH", "").strip()
    return Path(raw) if raw else _DEFAULT_TOKEN_PATH


def credentials_configured() -> bool:
    """Whether the OAuth client env vars are present (says nothing about token validity)."""
    return bool(os.getenv("GOOGLE_CLIENT_ID", "").strip() and os.getenv("GOOGLE_CLIENT_SECRET", "").strip())


def _log(event: str, **fields) -> None:
    """One line per Gmail call to stdout, plus a JSONL record when ``SITESOURCE_GMAIL_LOG`` names
    a file (the ``SITESOURCE_LLM_LOG`` pattern). Never raises — logging must not break a call."""
    line = f"[gmail] event={event}" + "".join(f" {k}={v}" for k, v in fields.items())
    print(line, flush=True)
    path = os.getenv("SITESOURCE_GMAIL_LOG", "").strip()
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": event, "ts": time.time(), **fields}) + "\n")
        except OSError:
            pass


def _load_credentials():
    """The refreshed OAuth credentials from the token file (lazy Google imports). Raises
    :class:`GmailUnavailable` with the exact fix when anything is missing or expired."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover — dev environments always have the deps
        raise GmailUnavailable(
            "Google API libraries not installed — pip install -r requirements.txt "
            "(google-auth, google-auth-oauthlib, google-api-python-client)."
        ) from exc

    path = token_path()
    if not path.is_file():
        raise GmailUnavailable(
            f"No Gmail token at {path} — run `python -m pipeline.gmail_client` once to authorise "
            "(needs GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in backend/.env)."
        )
    try:
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    except ValueError as exc:
        raise GmailUnavailable(
            f"Gmail token at {path} is unreadable/invalid — delete it and re-run "
            "`python -m pipeline.gmail_client` to re-authorise."
        ) from exc
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001 — any refresh failure gets the actionable message
            raise GmailUnavailable(
                "Gmail token refresh failed — if the OAuth consent screen is still in Testing "
                "mode its refresh tokens expire every 7 days: publish it to Production in the "
                "Google Cloud console, delete the token file and re-run "
                f"`python -m pipeline.gmail_client`. ({exc})"
            ) from exc
        path.write_text(creds.to_json(), encoding="utf-8")  # persist the refreshed token
        return creds
    raise GmailUnavailable(
        f"Gmail token at {path} is expired with no refresh token — delete it and re-run "
        "`python -m pipeline.gmail_client` (publish the consent screen to Production first)."
    )


def build_service():
    """A Gmail API service from the env credentials (lazy import; network only on use).
    Tests never call this — every public function accepts an injected ``service`` stub."""
    creds = _load_credentials()
    from googleapiclient.discovery import build  # lazy

    # cache_discovery=False: no file-cache warnings, no external discovery-doc read at runtime.
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _mime_raw(to: str, subject: str, body: str, attachments: list[tuple[str, bytes]]) -> str:
    """The RFC-2822 message for one enquiry, base64url-encoded the way the Gmail API wants it."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for filename, data in attachments:
        mime, _ = mimetypes.guess_type(filename)
        maintype, subtype = (mime or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def create_draft(
    to: str, subject: str, body: str, attachments: list[tuple[str, bytes]], *, service=None,
) -> str:
    """Create ONE Gmail draft (never a send — the operator reviews and sends from Gmail) and
    return its draft id. ``attachments`` is ``[(filename, bytes)]`` — the already-assembled
    relevant-only bundle. Raises :class:`GmailUnavailable` when Gmail cannot be reached."""
    svc = service or build_service()
    raw = _mime_raw(to, subject, body, attachments)
    try:
        draft = svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    except GmailUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — normalise SDK/API errors into the typed failure
        _log("draft_error", to=to, error=str(exc)[:200])
        raise GmailUnavailable(f"Gmail draft creation failed: {exc}") from exc
    draft_id = str(draft.get("id", ""))
    _log("draft_created", to=to, draft_id=draft_id, attachments=len(attachments))
    return draft_id


def list_replies(query: str, *, after: Optional[float] = None, max_results: int = 100, service=None) -> list[dict]:
    """Messages matching ``query`` (e.g. ``subject:\"SiteSource Ref\" has:attachment newer_than:7d``),
    each as ``{"id", "subject"}``. ``after`` (epoch seconds) narrows with Gmail's ``after:`` filter.
    Read-only; raises :class:`GmailUnavailable` when Gmail cannot be reached."""
    svc = service or build_service()
    q = f"{query} after:{int(after)}" if after else query
    try:
        listing = svc.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
        out: list[dict] = []
        for m in listing.get("messages", []) or []:
            meta = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata", metadataHeaders=["Subject"],
            ).execute()
            headers = {h["name"].lower(): h["value"] for h in meta.get("payload", {}).get("headers", [])}
            out.append({"id": m["id"], "subject": headers.get("subject", "")})
        return out
    except GmailUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        _log("poll_error", error=str(exc)[:200])
        raise GmailUnavailable(f"Gmail reply listing failed: {exc}") from exc


def _walk_parts(part: dict):
    yield part
    for child in part.get("parts", []) or []:
        yield from _walk_parts(child)


def get_attachments(message_id: str, *, service=None) -> list[tuple[str, bytes]]:
    """Every real attachment of one message as ``[(filename, bytes)]`` (inline/bodiless parts are
    skipped). Raises :class:`GmailUnavailable` when Gmail cannot be reached."""
    svc = service or build_service()
    try:
        msg = svc.users().messages().get(userId="me", id=message_id).execute()
        out: list[tuple[str, bytes]] = []
        for part in _walk_parts(msg.get("payload", {}) or {}):
            filename = part.get("filename") or ""
            body = part.get("body", {}) or {}
            if not filename:
                continue
            if body.get("attachmentId"):
                att = svc.users().messages().attachments().get(
                    userId="me", messageId=message_id, id=body["attachmentId"],
                ).execute()
                data = att.get("data", "")
            else:
                data = body.get("data", "")
            if data:
                out.append((filename, base64.urlsafe_b64decode(data)))
        return out
    except GmailUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        _log("attachment_error", message_id=message_id, error=str(exc)[:200])
        raise GmailUnavailable(f"Gmail attachment download failed: {exc}") from exc


def run_consent_flow() -> Path:  # pragma: no cover — interactive, browser-based, one-time
    """The ONE-TIME local consent flow: opens a browser against the operator's OAuth client and
    writes the token file. After this the refresh token keeps the backend authorised (publish the
    consent screen to Production so it does not expire every 7 days)."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret):
        raise GmailUnavailable(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set — create an OAuth client "
            "(Desktop app) in the Google Cloud console and put both in backend/.env."
        )
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GmailUnavailable(
            "google-auth-oauthlib not installed — pip install -r requirements.txt."
        ) from exc
    flow = InstalledAppFlow.from_client_config(
        {"installed": {
            "client_id": client_id, "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }},
        SCOPES,
    )
    creds = flow.run_local_server(port=0)
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")
    print(f"[gmail] token written to {path} — the backend can now draft and poll.")
    return path


if __name__ == "__main__":  # pragma: no cover — the documented one-time authorisation step
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    run_consent_flow()
