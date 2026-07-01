"""Hand the approved dispatch bundles to the n8n webhook that creates the Gmail drafts.

The app never touches Google or the Anthropic API here. It POSTs the composed
bundles to ``N8N_WEBHOOK_URL``; n8n holds the Google credential and creates one
draft per firm. The call is **best-effort** and never breaks the demo: if the URL
is unset, or the POST raises / returns a non-2xx, dispatch falls back to the mock
outbox and the endpoint still returns normally.
"""

from __future__ import annotations

import logging
import os

from schemas.models import DispatchSet

logger = logging.getLogger(__name__)

# n8n owns delivery; in the demo every draft is created against this test inbox.
_DRAFT_RECIPIENT = "twl3henner@gmail.com"
_TIMEOUT_SECONDS = 10.0


def draft_via_n8n(dispatch_set: DispatchSet, project: str = "GE/2026/14") -> bool:
    """POST the bundles to n8n so it creates one Gmail draft per firm.

    Returns ``True`` only on a 2xx response. Returns ``False`` (and logs a warning)
    when ``N8N_WEBHOOK_URL`` is unset, the POST fails, or the response is non-2xx.
    Never raises — the dispatch endpoint must not break because of the webhook.
    """
    url = (os.getenv("N8N_WEBHOOK_URL") or "").strip()
    if not url:
        return False

    payload = {
        "project": project,
        "drafts": [
            {
                "to": _DRAFT_RECIPIENT,
                "subject": b.email_subject,
                "body": b.email_body,
                "firm_name": b.firm_name,
                "trade": b.trade,
                "enclosed": b.bundle_doc_refs,
            }
            for b in dispatch_set.bundles
        ],
    }

    try:
        import httpx  # already a dependency; imported here to keep the import local

        response = httpx.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 — network/parse/anything: never break dispatch
        logger.warning("n8n webhook POST failed (%s); falling back to the mock outbox.", exc)
        return False

    if 200 <= response.status_code < 300:
        logger.info("n8n webhook accepted %d draft(s).", len(payload["drafts"]))
        return True
    logger.warning("n8n webhook returned HTTP %s; falling back to the mock outbox.", response.status_code)
    return False
