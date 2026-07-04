"""Stage 01 — ingest: TenderPackage -> ScopePackages.

Layer 2 (Claude) reads the four tender documents (Method of Measurement,
Particular Specification, Tender Addendum, Schedule of Rates) and splits the work
into one :class:`TradeWorkPackage` per trade — a scope summary, the relevant SoR
items, and ``source_refs`` naming which document each came from. The system prompt
forbids the model from pricing or judging a firm; it only splits and extracts.

Layer 1 then validates every returned trade against the canonical taxonomy
(``rules_engine.taxonomy``, which reads ``references/rubrics/trade_taxonomy.md``):
off-taxonomy trades are mapped to a canonical key or surfaced as unmapped — never
silently dropped. The taxonomy check is deterministic Python, not the model.

DEMO_MODE: ``complete_json`` short-circuits to a baked ``ScopePackages`` fixture and
never touches the network, exactly as the SiteClaim extract stage did.
"""

from __future__ import annotations

import re
from typing import Optional

from pipeline.llm_client import LLMClient
from rules_engine.taxonomy import CANONICAL_TRADES, validate_scope
from schemas.models import ScopePackages, TenderPackage, TradeWorkPackage

# A large Schedule of Rates (SR-01 is 58 pages, Sections A-T, hundreds of items) cannot be
# extracted in one call — the JSON output exceeds max_tokens and truncates. So the text is
# chunked, extracted per chunk, and merged. Size a chunk so its expected JSON stays well
# under max_tokens (chunking, not a giant max_tokens ceiling, is what prevents truncation).
MAX_CHUNK_CHARS = 12000


def _system_prompt() -> str:
    """Build the split instruction, embedding the canonical trades from the taxonomy.

    States the output shape by exact field name (not by schema title) and lists the
    valid trades read live from ``rules_engine.taxonomy`` — so a newer model does not
    guess field names (the observed Sonnet-5 drift was ``package_name`` instead of
    ``trade``) and the trade list never drifts from the taxonomy.
    """
    trades = ", ".join(sorted(CANONICAL_TRADES))
    return (
        "You are a quantity-surveying assistant for a Hong Kong main contractor. Read the "
        "tender documents (Method of Measurement, Particular Specification, Tender Addendum, "
        "Schedule of Rates) and SPLIT the works into trade packages. You ONLY split and "
        "extract scope — never price the work, never invent a quantity or rate, never judge "
        "or rank a subcontractor.\n\n"
        "Return ONE JSON object with EXACTLY these field names and no others:\n"
        '{"project_name": <string>, "packages": [\n'
        '  {"trade": <canonical trade>, "scope_summary": <string>, '
        '"sor_items": [{"item_ref": <string>, "description": <string>, "unit": <string>, '
        '"qty": <number>}], "source_refs": [<string naming the tender document>]}\n'
        "]}\n\n"
        f"`trade` MUST be exactly one of these canonical trades: {trades}. Put the "
        "descriptive sub-section name (e.g. \"Geotechnical Works\", \"Section 7\") in "
        "`scope_summary`, NOT in any other field. Never emit a `package_name` field. Emit "
        "exactly one package per canonical trade that appears in the tender — consolidate "
        "several sub-sections of the same trade into that trade's single package rather than "
        "one package per sub-section — and no package for a trade that is not present.\n\n"
        "Populate `sor_items` with EVERY priced row of the Schedule of Rates for that trade "
        "— one object per row — copying its item reference, description, unit, and quantity "
        "verbatim (include `qty` when the row states one). Do NOT collapse a section into a "
        "single summary item: `scope_summary` is the prose overview, `sor_items` is the "
        "row-by-row list. Never invent an item, a rate, or a quantity.\n\n"
        "`item_ref` MUST be the EXACT printed item code as it appears in the schedule "
        '(e.g. "A1a(a)", "M2", "H14"), copied character-for-character — NEVER the section '
        "letter fused with neighbouring text or an adjacent column value, and NEVER an "
        "invented or renumbered code. If a row has no printed item code, SKIP that row "
        "rather than fabricate a ref."
    )


def _user_prompt(tender: TenderPackage) -> str:
    docs = "\n".join(f"- {d.doc_type.value}: {d.filename}" for d in tender.documents)
    return (
        f"Project: {tender.project_name}\n"
        f"Description: {tender.description}\n"
        f"Tender documents:\n{docs}\n\n"
        "Split this tender into trade work packages."
    )


# ---------------------------------------------------------------------------
# Chunked extraction — split a large SoR text into a handful of pieces, extract each,
# and merge the items (deterministic; never splits mid-line / mid-item-row).
# ---------------------------------------------------------------------------
_SECTION_RE = re.compile(r"(?im)^\s*(?:section|part)\s+[A-Za-z0-9]")
_PAGE_RE = re.compile(r"(?m)^\[page \d+\]")


def _split_on(text: str, pattern: re.Pattern) -> list[str]:
    """Split ``text`` at each ``pattern`` match, keeping each header with its block."""
    starts = [m.start() for m in pattern.finditer(text)]
    if not starts:
        return [text]
    blocks: list[str] = []
    if starts[0] > 0:
        blocks.append(text[: starts[0]])  # preamble before the first header
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        blocks.append(text[start:end])
    return [b for b in blocks if b.strip()]


def _split_into_blocks(text: str) -> list[str]:
    """Prefer Section-header boundaries when cleanly detectable (>=2), else page boundaries."""
    if len(_SECTION_RE.findall(text)) >= 2:
        return _split_on(text, _SECTION_RE)
    if len(_PAGE_RE.findall(text)) >= 2:
        return _split_on(text, _PAGE_RE)
    return [text]


def _cap_block(block: str, max_chars: int) -> list[str]:
    """Hard-split an over-long block on line boundaries — never mid-line."""
    if len(block) <= max_chars:
        return [block]
    pieces, current, size = [], [], 0
    for line in block.splitlines(keepends=True):
        if size + len(line) > max_chars and current:
            pieces.append("".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line)
    if current:
        pieces.append("".join(current))
    return pieces


def _chunk_text(text: str, max_chars: Optional[int] = None) -> list[str]:
    """Chunk ``text`` into a handful of pieces under ``max_chars`` on section/page/line
    boundaries. Never splits mid-line, so an item row is never cut in half."""
    max_chars = max_chars or MAX_CHUNK_CHARS
    if not text.strip():
        return []
    chunks, current, size = [], [], 0
    for block in _split_into_blocks(text):
        for piece in _cap_block(block, max_chars):
            if size + len(piece) > max_chars and current:
                chunks.append("\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _merge_scopes(results: list[ScopePackages], tender: TenderPackage) -> ScopePackages:
    """Merge per-chunk results into one ScopePackages: group packages by trade, concatenate
    ``sor_items`` deduped by ``item_ref`` (unique across sections). ``project_name`` /
    ``scope_summary`` / ``source_refs`` are taken once, from their first appearance."""
    project_name = ""
    order: list[str] = []
    merged: dict[str, dict] = {}
    for scope in results:
        if scope.project_name and not project_name:
            project_name = scope.project_name
        for pkg in scope.packages:
            if pkg.trade not in merged:
                merged[pkg.trade] = {"scope_summary": pkg.scope_summary, "source_refs": [], "items": [], "seen": set()}
                order.append(pkg.trade)
            entry = merged[pkg.trade]
            if not entry["scope_summary"] and pkg.scope_summary:
                entry["scope_summary"] = pkg.scope_summary
            for ref in pkg.source_refs:
                if ref not in entry["source_refs"]:
                    entry["source_refs"].append(ref)
            for item in pkg.sor_items:
                key = (item.item_ref or "").strip()
                if key and key in entry["seen"]:
                    continue  # dedupe by non-empty item_ref; keep the first
                if key:
                    entry["seen"].add(key)
                entry["items"].append(item)
    packages = [
        TradeWorkPackage(
            trade=trade, scope_summary=merged[trade]["scope_summary"],
            sor_items=merged[trade]["items"], source_refs=merged[trade]["source_refs"],
        )
        for trade in order
    ]
    return ScopePackages(project_name=project_name or tender.project_name, packages=packages)


def _extract(
    client: LLMClient, tender: TenderPackage, doc_text: str, images: Optional[list[str]], demo_fixture: Optional[str]
) -> ScopePackages:
    """Run the item-extraction prompt over the document and merge into one ScopePackages.

    Large text is chunked (one small call per chunk); any scanned pages go in a single
    vision call; a small or empty document (incl. the DEMO fixture) is a single call.
    """
    system = _system_prompt()
    base_user = _user_prompt(tender)
    calls: list[tuple[str, Optional[list[str]]]] = [
        (base_user + "\n\n=== Extracted tender document text ===\n" + chunk, None)
        for chunk in _chunk_text(doc_text)
    ]
    if images:
        calls.append((base_user + "\n\n=== Attached scanned tender pages ===", images))
    if not calls:  # no text and no images (DEMO fixture / small tender) -> one call
        calls.append((base_user, None))
    results = [
        client.complete_json(
            system=system, user=user, target_model=ScopePackages, demo_fixture=demo_fixture, images=call_images
        )
        for (user, call_images) in calls
    ]
    return _merge_scopes(results, tender)


def ingest_tender(
    tender: TenderPackage,
    demo_fixture: Optional[str] = None,
    *,
    client: Optional[LLMClient] = None,
    images: Optional[list[str]] = None,
    doc_text: str = "",
) -> ScopePackages:
    """Split ``tender`` into one :class:`TradeWorkPackage` per trade.

    In DEMO_MODE the split is read from ``demo_fixture``. Otherwise Layer 2 produces it
    text-first: ``doc_text`` (the extracted text layer) is chunked on section/page
    boundaries and each chunk extracted separately, then merged — so a 58-page Schedule
    of Rates yields the full item list without truncation. Scanned pages (``images``) go
    in a single vision call. ``project_name`` is taken from the tender; Layer 1 then
    normalises trades against the taxonomy before returning.
    """
    client = client or LLMClient()
    scope = _extract(client, tender, doc_text, images, demo_fixture)
    normalised, unmapped = validate_scope(scope)
    if unmapped:
        # Surfaced, not dropped — a human reconciles these against the taxonomy.
        print(f"[ingest] unmapped trades (kept for review): {unmapped}")
    return normalised
