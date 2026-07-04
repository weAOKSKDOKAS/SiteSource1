"""The reply loop — correlate an inbound subcontractor reply to its tender/firm/trade.

Closing the loop so an emailed reply lands in the right tender's comparison without a
manual upload. Two matchers, in strict order:

1. **Correlation ref (primary, deterministic).** On dispatch a stable ref
   ``<tender>.<firm>.<trade>`` is put in the email subject (``[SiteSource Ref: <ref>]``)
   and the mapping ``ref -> {tender_id, firm_id, trade}`` is recorded in a registry
   (a JSON file at the Workspace root). The reply keeps the ref in its subject, so n8n
   passes it back and the backend resolves the reply with a pure registry lookup — no
   model, no guessing.
2. **AI fallback (secondary, best-effort).** Only when a reply arrives with *no* ref
   (a fresh email) does :func:`fallback_match` read the attachment and pick the matching
   outstanding dispatch — and only if it is confident. If it cannot, the caller reports
   "unmatched — needs manual assignment" rather than guessing.

Replies accumulate per tender (deduped by firm — a resend replaces the earlier reply),
so the comparison grows as replies come in; the caller re-levels all of a tender's
replies and regenerates the xlsx with the existing, unforked leveling/export code.

DEMO_MODE: the registry, accumulation, and resolution are pure JSON/dict work (offline).
The fallback goes through ``complete_json``, so it short-circuits to a fixture and opens
no socket offline; the module imports no provider SDK.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ValidationError

from pipeline.llm_client import LLMClient
from pipeline.workspace import Workspace, tender_slug
from schemas.models import BidReply

_REGISTRY_FILE = "dispatch_registry.json"
_REPLIES_FILE = "replies.json"
_MIN_FALLBACK_CONFIDENCE = 0.6


# ---------------------------------------------------------------------------
# Correlation ref (primary)
# ---------------------------------------------------------------------------
def make_ref(tender_id: str, firm_id: str, trade: str) -> str:
    """A stable correlation ref for one (tender, firm, trade).

    Dot-separated because tender slugs, firm ids, and trade keys never contain a dot,
    so the three parts stay unambiguous and the ref is safe inside an email subject.
    """
    return f"{tender_slug(tender_id)}.{firm_id}.{trade}"


def subject_with_ref(subject: str, ref: str) -> str:
    """Append the correlation tag n8n reads back off the reply's subject."""
    return f"{subject} [SiteSource Ref: {ref}]"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------
def _read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Registry (ref -> {tender_id, firm_id, trade})
# ---------------------------------------------------------------------------
def _registry_path(ws: Workspace) -> Path:
    return ws.root / _REGISTRY_FILE


def record_dispatch(ws: Workspace, ref: str, tender_id: str, firm_id: str, trade: str) -> None:
    """Record the ref -> tender/firm/trade mapping so inbound can resolve it."""
    registry = _read_json(_registry_path(ws), {})
    registry[ref] = {"tender_id": tender_id, "firm_id": firm_id, "trade": trade}
    _write_json(_registry_path(ws), registry)


def resolve_ref(ws: Workspace, ref: str) -> Optional[dict]:
    """Resolve a correlation ref deterministically (the primary path). None if unknown."""
    if not ref:
        return None
    return _read_json(_registry_path(ws), {}).get(ref)


def outstanding_dispatches(ws: Workspace) -> list[dict]:
    """Every recorded dispatch (for the fallback matcher's candidate list)."""
    return [{"ref": ref, **info} for ref, info in _read_json(_registry_path(ws), {}).items()]


# ---------------------------------------------------------------------------
# Per-tender reply accumulation
# ---------------------------------------------------------------------------
def _replies_path(ws: Workspace, tender_id: str) -> Path:
    return ws.tender_dir(tender_id) / _REPLIES_FILE


def tender_replies(ws: Workspace, tender_id: str) -> list[BidReply]:
    """Every reply received for ``tender_id`` so far."""
    return [BidReply.model_validate(r) for r in _read_json(_replies_path(ws, tender_id), [])]


def accumulate_reply(ws: Workspace, tender_id: str, reply: BidReply) -> list[BidReply]:
    """Store ``reply`` for ``tender_id`` and return all replies received so far.

    Deduped by firm: a firm that replies again replaces its earlier reply, so re-leveling
    over the returned list never double-counts a firm.
    """
    replies = [r for r in tender_replies(ws, tender_id) if r.firm_id != reply.firm_id]
    replies.append(reply)
    _write_json(_replies_path(ws, tender_id), [r.model_dump() for r in replies])
    return replies


def comparison_path(ws: Workspace, tender_id: str) -> Path:
    """Where this tender's accumulating leveled comparison xlsx is written."""
    return ws.artifacts_dir(tender_id, create=True) / "comparison.xlsx"


def comparison_file(ws: Workspace, tender_id: str) -> Path:
    """The comparison xlsx path WITHOUT creating the directory (for a read / serve)."""
    return ws.artifacts_dir(tender_id) / "comparison.xlsx"


def replies_last_received(ws: Workspace, tender_id: str) -> Optional[str]:
    """ISO-8601 UTC time the tender's replies file last changed (when the newest reply
    landed), or ``None`` if no reply has arrived yet."""
    path = _replies_path(ws, tender_id)
    if not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# AI fallback (secondary) — only when no ref is present
# ---------------------------------------------------------------------------
class RefMatch(BaseModel):
    """The fallback matcher's verdict — which outstanding dispatch the reply belongs to."""

    matched: bool = False
    ref: str = ""
    confidence: float = 0.0


_FALLBACK_SYSTEM = (
    "A subcontractor's priced reply arrived with no correlation reference. Given the "
    "attached reply document and a list of outstanding sub-contract enquiries (each with "
    "a ref, firm, trade and project), decide which ONE enquiry this reply answers. Match "
    "on the firm's name and the trade/scope shown in the document. If you cannot identify "
    "a single confident match, set matched=false. Never guess. Return JSON with matched, "
    "the chosen ref, and a confidence 0..1."
)


def _fallback_prompt(candidates: list[dict]) -> str:
    lines = "\n".join(
        f"- ref={c['ref']} | firm={c['firm_id']} | trade={c['trade']} | project={c['tender_id']}"
        for c in candidates
    )
    return f"Outstanding enquiries:\n{lines}\n\nWhich ref does the attached reply answer?"


def fallback_match(
    images: list[str],
    ws: Workspace,
    *,
    demo_fixture: Optional[str] = None,
    client: Optional[LLMClient] = None,
    min_confidence: float = _MIN_FALLBACK_CONFIDENCE,
) -> Optional[dict]:
    """Best-effort match of a ref-less reply to an outstanding dispatch, or None.

    Secondary to :func:`resolve_ref`. Returns None (→ "unmatched, needs manual
    assignment") when there are no outstanding dispatches, the model is not confident,
    or it names a ref that was never dispatched.
    """
    candidates = outstanding_dispatches(ws)
    if not candidates:
        return None
    client = client or LLMClient()
    try:
        result = client.complete_json(
            system=_FALLBACK_SYSTEM,
            user=_fallback_prompt(candidates),
            target_model=RefMatch,
            demo_fixture=demo_fixture,
            images=images,
            purpose="reply-match",
        )
    except (RuntimeError, FileNotFoundError, ValidationError, ValueError):
        return None
    known = {c["ref"] for c in candidates}
    if result.matched and result.confidence >= min_confidence and result.ref in known:
        return resolve_ref(ws, result.ref)
    return None
