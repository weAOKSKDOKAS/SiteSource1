"""Stage 04 — level: BidReplies -> LevelledBids.

Layer 2 parses each returned Schedule of Rates document into a :class:`BidReply`
(line items, rates, exclusions) via ``complete_json``; DEMO_MODE reads baked
``BidReply`` fixtures (see :func:`load_demo_replies`). Layer 1
(:mod:`rules_engine.leveling`, pure Python) then does **every calculation**:
recompute amounts, sum to ``corrected_total``, flag arithmetic disagreements,
record scope gaps and exclusions, and normalise onto a common scope basis.

Firm display names are resolved from the proprietary database (Layer 3); the
arithmetic never depends on the model.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from db import store
from pipeline.concurrency import run_calls
from pipeline.llm_client import LLMClient
from pipeline.stage_01_ingest.ingest import _chunk_text  # reuse the ingest text chunker
from rules_engine.leveling import level_reply, peer_item_reference
from schemas.models import BidReply, LevelledBid, ScopePackages

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

# A returned SoR with many line items overruns max_tokens if parsed in one call (the JSON
# truncates mid-string), so — exactly as ingest does — the reply is parsed across bounded
# calls and the line items merged. A scanned reply arrives as rendered pages, chunked by
# page group (the image analogue of the ingest text chunker); a text reply reuses _chunk_text.
IMAGE_PAGES_PER_CHUNK = 3

_PARSE_SYSTEM = (
    "You parse a subcontractor's returned Schedule of Rates into structured data. "
    "Extract EVERY line item shown on the attached pages/text — each with item_ref, "
    "description, unit, qty, rate, and amount — plus the stated exclusions and the "
    "bidder's claimed total. Transcribe faithfully — do NOT correct arithmetic, do NOT "
    "fill a missing rate, do NOT invent a number; if the claimed total is not shown "
    "here, return null for claimed_total. Return a JSON object matching the BidReply "
    "schema with fields firm_id, trade, line_items, exclusions, and claimed_total."
)


def load_demo_replies(demo_fixture: str) -> list[BidReply]:
    """Load a baked list of :class:`BidReply` from ``backend/fixtures/<demo_fixture>``."""
    data = json.loads((_FIXTURES_DIR / demo_fixture).read_text(encoding="utf-8"))
    return [BidReply.model_validate(item) for item in data]


def _chunk_pages(images: list[str], pages_per_chunk: int) -> list[list[str]]:
    """Group rendered reply pages into vision calls of ``pages_per_chunk`` pages each —
    the image analogue of ``_chunk_text`` (a whole page is never split)."""
    return [images[i:i + pages_per_chunk] for i in range(0, len(images), pages_per_chunk)]


def merge_replies(replies: list[BidReply], firm_id: str, trade: str) -> BidReply:
    """Merge partial replies into one BidReply: concatenate ``line_items`` deduped by
    ``item_ref`` (the first wins), union the exclusions, and take the first stated
    ``claimed_total``. ``firm_id`` / ``trade`` are the identity resolved from the ref —
    authoritative here, never taken from a parse. Used for the per-chunk results of
    :func:`parse_bid_reply` and by the API to combine deterministically-parsed SoR
    sheets (xlsx) with any model-parsed pages."""
    line_items = []
    seen: set[str] = set()
    exclusions: list[str] = []
    claimed_total: Optional[float] = None
    for reply in replies:
        for item in reply.line_items:
            key = (item.item_ref or "").strip()
            if key and key in seen:
                continue  # dedupe by non-empty item_ref; keep the first
            if key:
                seen.add(key)
            line_items.append(item)
        for exclusion in reply.exclusions:
            if exclusion not in exclusions:
                exclusions.append(exclusion)
        if claimed_total is None and reply.claimed_total is not None:
            claimed_total = reply.claimed_total
    return BidReply(
        firm_id=firm_id, trade=trade, line_items=line_items,
        exclusions=exclusions, claimed_total=claimed_total,
    )


def parse_bid_reply(
    *, firm_id: str, trade: str, images: Optional[list[str]] = None, doc_text: str = "",
    demo_fixture: Optional[str] = None, client: Optional[LLMClient] = None,
) -> BidReply:
    """Layer 2: parse one returned SoR document into a BidReply (live path).

    A large priced SoR (many line items) overruns ``max_tokens`` if parsed in one call —
    the JSON truncates mid-string and the whole reply fails. So, exactly as ingest does,
    the document is parsed across bounded calls and the line items merged: extracted text
    is chunked with the ingest chunker (``_chunk_text``) and any scanned pages are grouped
    into small vision calls (``_chunk_pages``). ``firm_id`` / ``trade`` come from the
    resolved ref and stay authoritative through the merge."""
    client = client or LLMClient()
    base_user = f"Parse the returned Schedule of Rates for firm {firm_id}, trade {trade}."
    calls: list[tuple[str, Optional[list[str]]]] = [
        (base_user + "\n\n=== Returned SoR document text ===\n" + chunk, None)
        for chunk in _chunk_text(doc_text)
    ]
    calls += [(base_user, group) for group in _chunk_pages(images or [], IMAGE_PAGES_PER_CHUNK)]
    if not calls:  # no text and no images (DEMO fixture / small reply) -> one call
        calls.append((base_user, None))
    # Chunk calls are independent — run bounded-concurrent, in input order (merge_replies
    # dedupes by item_ref first-wins, so chunk order must be preserved).
    replies = run_calls(
        lambda call: client.complete_json(
            system=_PARSE_SYSTEM, user=call[0], target_model=BidReply,
            demo_fixture=demo_fixture, images=call[1], purpose="reply-parse",
        ),
        calls,
    )
    return merge_replies(replies, firm_id, trade)


def _scope_basis(
    replies: list[BidReply], scope: ScopePackages,
) -> tuple[dict[str, list], dict[str, float]]:
    """The common-scope basis for scope-aware leveling: ``({unit key -> canonical items},
    {normalized ref -> peer median amount})``. The peer map is keyed on the NORMALISED ref so a
    canonical item a firm omitted is valued by what its peers charged for the same item even when the
    ref forms drift (``J5(a)`` / ``J5A``). Pure Layer-1 routing; no model."""
    from rules_engine.leveling import computable_amount
    from pipeline.stage_04_level.route_items import build_canonical_items, normalize_ref

    canon_by_unit: dict[str, list] = {}
    for c in build_canonical_items(scope):
        if c.package_key is not None:
            canon_by_unit.setdefault(c.package_key, []).append(c)

    peer_amounts: dict[str, list[float]] = {}
    for reply in replies:
        for line in reply.line_items:
            amount = computable_amount(line)
            if amount is not None:
                peer_amounts.setdefault(normalize_ref(line.item_ref), []).append(amount)
    from statistics import median
    peer_by_norm = {nr: float(median(vals)) for nr, vals in peer_amounts.items() if vals}
    return canon_by_unit, peer_by_norm


def level_bids(
    replies: list[BidReply],
    scope: Optional[ScopePackages] = None,
    demo_fixture: Optional[str] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> list[LevelledBid]:
    """Level every reply onto a common scope basis.

    If ``replies`` is empty and ``demo_fixture`` is given, the baked ``BidReply`` fixture is loaded
    (the DEMO_MODE path). Firm names come from the database. When ``scope`` is given, each bid is
    levelled against its routed unit's FULL canonical item set: a canonical item the firm did not
    return is a scope gap valued at the peer price, so partial-coverage returns are honest and
    compared like-for-like. Without a scope it is the reply-anchored behaviour (unchanged)."""
    if not replies and demo_fixture:
        replies = load_demo_replies(demo_fixture)

    from pipeline.stage_04_level.route_items import normalize_ref, route_items

    canon_by_unit, peer_by_norm = _scope_basis(replies, scope) if scope is not None else ({}, {})

    own_conn = conn is None
    conn = conn or store.get_connection()
    try:
        # Value both gap kinds (returned-but-unpriced AND not-returned scope) on the SAME norm-keyed
        # peer basis, so a gap whose ref form drifts from its peers' (J5(a) vs J5A) is still priced at
        # the peer median. `peer` is keyed by each returned raw ref (what level_reply looks up) but
        # valued via peer_by_norm. The reply-anchored (no-scope) path has no norm basis -> raw peer.
        peer = (
            {line.item_ref: peer_by_norm[normalize_ref(line.item_ref)]
             for reply in replies for line in reply.line_items
             if line.item_ref and normalize_ref(line.item_ref) in peer_by_norm}
            if scope is not None else peer_item_reference(replies)
        )
        levelled = []
        for reply in replies:
            profile = store.firm_profile(conn, reply.firm_id)
            firm_name = profile.name if profile is not None else reply.firm_id
            # Which canonical items of this unit the reply actually covered — by the SAME routing
            # (exact ref, then description) that grouped the lines. So a line matched by description
            # (a garbled / absent ref) marks its canonical item returned and is NOT then double-counted
            # as an unpriced gap valued at the peer price.
            returned = {
                normalize_ref(r.canonical_ref)
                for r in (route_items(reply.line_items, scope) if scope is not None else [])
                if r.canonical_ref and r.package_key == reply.trade
            }
            unpriced = [
                (c.item_ref, c.description, peer_by_norm.get(c.norm_ref, 0.0))
                for c in canon_by_unit.get(reply.trade, [])
                if c.norm_ref and c.norm_ref not in returned
            ]
            levelled.append(level_reply(reply, firm_name, peer, unpriced_scope=unpriced))
        return levelled
    finally:
        if own_conn:
            conn.close()
