"""Turn an uploaded/linked priced tender into ``tender_items`` rows (Phase B1b).

Three sources, all producing the same row-dict shape (item_ref, description, unit, qty,
rate, amount, section):

* **xlsx** in our SoR-sheet layout — the deterministic path: reuse ``parse_sor_xlsx``
  (openpyxl, no model) → :class:`BidReply` line items, which carry rates.
* **PDF / image** priced tender — reuse the existing chunked reply parser
  ``parse_bid_reply`` (text-first, bounded-concurrent, merge-deduped). LLM, live-only.
* **pipeline link** — a :class:`ScopePackages` already produced by the sourcing pipeline;
  capture its scope items (unpriced — ``SorItem`` has no rate) as the tender snapshot, the
  compounding loop (§10).

Identity/pricing is copied verbatim; nothing is invented.
"""

from __future__ import annotations

from typing import Optional

from pipeline.documents import extract_document
from pipeline.llm_client import LLMClient
from pipeline.stage_04_level.level import parse_bid_reply
from pipeline.stage_04_level.reply_xlsx import parse_sor_xlsx
from schemas.models import BidReply, ScopePackages


def _from_bidreply(reply: BidReply) -> list[dict]:
    return [
        {
            "item_ref": li.item_ref, "description": li.description or "", "unit": li.unit or "",
            "qty": li.qty, "rate": li.rate, "amount": li.amount, "section": "",
        }
        for li in reply.line_items
    ]


def tender_items_from_xlsx(file_bytes: bytes) -> list[dict]:
    """Deterministic: parse our SoR-sheet xlsx into tender item rows (rates kept)."""
    return _from_bidreply(parse_sor_xlsx(file_bytes))


def tender_items_from_document(
    file_bytes: bytes, content_type: Optional[str], *,
    client: Optional[LLMClient] = None, demo_fixture: Optional[str] = None,
) -> list[dict]:
    """Priced-tender PDF/image → tender item rows, via the chunked reply parser (LLM)."""
    text, images = extract_document(file_bytes, content_type)
    reply = parse_bid_reply(
        firm_id="", trade="", images=images, doc_text=text, demo_fixture=demo_fixture, client=client,
    )
    return _from_bidreply(reply)


def tender_items_from_scope(scope: ScopePackages) -> list[dict]:
    """Capture a pipeline scope split into the tender snapshot (unpriced — rate stays None,
    the compounding loop). ``section`` records which trade package the item came from."""
    items: list[dict] = []
    for pkg in scope.packages:
        for it in pkg.sor_items:
            items.append({
                "item_ref": it.item_ref, "description": it.description or "", "unit": it.unit or "",
                "qty": it.qty, "rate": None, "amount": None, "section": pkg.trade,
            })
    return items
