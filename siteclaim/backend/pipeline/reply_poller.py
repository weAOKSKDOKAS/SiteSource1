"""Background Gmail reply poller — the inbound n8n trigger replacement (transport only).

Every ``GMAIL_POLL_SECONDS`` (default 120) the poller asks Gmail for reply messages carrying the
``[SiteSource Ref: …]`` correlation tag (``subject:"SiteSource Ref" has:attachment newer_than:7d``),
downloads each NEW message's attachments, and hands them to the EXISTING inbound processing path —
the same shared function ``/inbound-reply`` runs (parse → resolve ref → item-identity routing →
accumulate/supersede → re-level → regenerate the comparison). The poller decides nothing and
re-implements nothing: it moves bytes from Gmail to that function.

Idempotency: processed Gmail ``message_id``s are persisted at the Workspace root
(``processed_messages.json``, alongside the dispatch registry), so re-reading the inbox never
double-processes a reply — and a backend that was OFFLINE for days simply catches up on the next
poll (the replies sit in Gmail; nothing is lost). A message whose ref does not resolve is recorded
``unmatched`` and surfaced in the poller state — reported, never silently dropped.

The loop can never crash the app: every iteration is wrapped; a failure records ``last_error`` and
retries next tick. ``GMAIL_POLLING_ENABLED`` defaults to false (DEMO and the test suite never
poll), and DEMO_MODE forces it off regardless. The blocking Gmail/parse work runs on a worker
thread (``asyncio.to_thread``), never on the event loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from pipeline.workspace import Workspace

_PROCESSED_FILE = "processed_messages.json"
_REF_RE = re.compile(r"\[SiteSource Ref:\s*([^\]]+)\]")

# Replies keep the dispatched subject ("Re: … [SiteSource Ref: …]") and carry the priced return as
# an attachment; newer_than:7d bounds the scan (processed ids are persisted, so a longer outage is
# still caught up as long as the poller runs within the window — widen via GMAIL_POLL_QUERY).
DEFAULT_QUERY = 'subject:"SiteSource Ref" has:attachment newer_than:7d'

# ``ProcessReply(ref, [(filename, bytes)]) -> status`` — the injected shared processing entry
# (api.process_inbound_reply behind a thin adapter). Injected so this module never imports api.
ProcessReply = Callable[[str, list[tuple[str, bytes]]], str]

# Poller state for the status surface: read by /integrations/gmail, written under a lock here.
_STATE_LOCK = threading.Lock()
STATE: dict = {
    "last_poll_at": None,   # ISO-8601 of the last completed poll (successful or not)
    "last_error": "",       # "" when the last poll succeeded
    "last_found": 0,        # messages matching the query on the last poll
    "processed_total": 0,   # replies fed to processing since startup
    "unmatched_total": 0,   # replies whose ref did not resolve (surfaced, never dropped)
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_state(**changes) -> None:
    with _STATE_LOCK:
        STATE.update(changes)


def _bump_state(key: str, by: int = 1) -> None:
    with _STATE_LOCK:
        STATE[key] = STATE.get(key, 0) + by


def poller_state() -> dict:
    """A snapshot of the poller's run state (for the integrations status endpoint)."""
    with _STATE_LOCK:
        return dict(STATE)


def polling_enabled() -> bool:
    """Polling is OPT-IN (``GMAIL_POLLING_ENABLED=true``) and DEMO_MODE forces it off — the demo
    and the test suite stay fully offline (no Gmail import, no background task)."""
    from pipeline.llm_client import demo_mode  # lazy: no import cycle at module import

    enabled = os.getenv("GMAIL_POLLING_ENABLED", "false").strip().lower() in ("1", "true", "yes")
    return enabled and not demo_mode()


def poll_seconds() -> int:
    try:
        return max(15, int(os.getenv("GMAIL_POLL_SECONDS", "120")))
    except ValueError:
        return 120


def poll_query() -> str:
    return os.getenv("GMAIL_POLL_QUERY", "").strip() or DEFAULT_QUERY


# ---------------------------------------------------------------------------
# Idempotency — processed Gmail message ids, persisted with the reply registry
# ---------------------------------------------------------------------------
def _processed_path(ws: Workspace) -> Path:
    return ws.root / _PROCESSED_FILE


def load_processed(ws: Workspace) -> dict:
    """``{message_id: {ref, status, at}}`` — every Gmail message already handled."""
    path = _processed_path(ws)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def mark_processed(ws: Workspace, message_id: str, *, ref: str, status: str) -> None:
    processed = load_processed(ws)
    processed[message_id] = {"ref": ref, "status": status, "at": _now_iso()}
    path = _processed_path(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(processed, indent=2), encoding="utf-8")


def ref_from_subject(subject: str) -> str:
    """The correlation ref off a reply subject (``Re: RFQ … [SiteSource Ref: x.y.z]``), or ``""``."""
    m = _REF_RE.search(subject or "")
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# One poll — synchronous and fully testable (stub service + fake processor)
# ---------------------------------------------------------------------------
def poll_once(process: ProcessReply, *, workspace: Optional[Workspace] = None, service=None) -> dict:
    """One inbox sweep: list matching messages, skip already-processed ids, download each new
    message's attachments and feed the shared processing path. Returns a summary dict and NEVER
    raises — a Gmail/processing failure is recorded (``last_error`` / a per-message ``failed``
    entry) and retried on a later tick. A message is marked processed only after its outcome is
    known (matched / unmatched / error-free skip), so a transient failure is retried."""
    from pipeline import gmail_client  # lazy: only a live poll imports the Gmail path

    ws = workspace or Workspace()
    summary = {"found": 0, "processed": 0, "skipped": 0, "unmatched": 0, "failed": 0}
    try:
        messages = gmail_client.list_replies(poll_query(), service=service)
    except gmail_client.GmailUnavailable as exc:
        _update_state(last_poll_at=_now_iso(), last_error=str(exc))
        gmail_client._log("poll_unavailable", error=str(exc)[:200])
        return summary
    summary["found"] = len(messages)
    processed_ids = load_processed(ws)
    for m in messages:
        mid = m.get("id", "")
        if not mid or mid in processed_ids:
            summary["skipped"] += 1
            continue
        ref = ref_from_subject(m.get("subject", ""))
        try:
            attachments = gmail_client.get_attachments(mid, service=service)
            status = process(ref, attachments)
        except gmail_client.GmailUnavailable as exc:
            # Transport failure mid-poll: NOT marked processed — retried next tick.
            summary["failed"] += 1
            _update_state(last_error=str(exc))
            continue
        except Exception as exc:  # noqa: BLE001 — a bad reply must not stall the sweep
            # Processing failure (unreadable attachment, etc.): recorded so it is visible, and
            # marked processed with the error so ONE poisoned message cannot block the inbox
            # forever; the record keeps the reason for the operator.
            summary["failed"] += 1
            mark_processed(ws, mid, ref=ref, status=f"error: {exc}")
            gmail_client._log("reply_error", message_id=mid, ref=ref, error=str(exc)[:200])
            continue
        mark_processed(ws, mid, ref=ref, status=status)
        if status == "matched":
            summary["processed"] += 1
            _bump_state("processed_total")
        else:
            summary["unmatched"] += 1  # surfaced (state + processed record), never dropped
            _bump_state("unmatched_total")
        gmail_client._log("reply_processed", message_id=mid, ref=ref, status=status)
    _update_state(last_poll_at=_now_iso(), last_error="", last_found=summary["found"])
    return summary


async def run_forever(process: ProcessReply) -> None:  # pragma: no cover — the thin async shell
    """The background loop: one threadpooled :func:`poll_once` every ``GMAIL_POLL_SECONDS``.
    Never crashes the app — any iteration failure is recorded and the next tick retries."""
    from pipeline import gmail_client

    interval = poll_seconds()
    gmail_client._log("poller_started", interval=interval)
    while True:
        try:
            await asyncio.to_thread(poll_once, process)
        except Exception as exc:  # noqa: BLE001 — the loop itself must survive anything
            _update_state(last_poll_at=_now_iso(), last_error=str(exc))
            gmail_client._log("poll_crashed", error=str(exc)[:200])
        await asyncio.sleep(interval)
