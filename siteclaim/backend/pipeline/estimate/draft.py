"""Scope-of-works + SoR/BOQ skeleton draft (Phase P3b — Layer 2, assist only).

Given a self-perform package's trade and tendered scope, draft (1) a concise scope-of-works
narrative and (2) a candidate item skeleton — any commonly-needed items NOT already in the
tender SoR. Purpose tag ``estimate-draft``. Layer 1 canonicalises the trade against the
taxonomy. The person edits and prices everything.

Rate-primary and rate-optional, and — the load-bearing honesty rule — the draft NEVER invents
a quantity or a rate: the LLM proposes item refs/descriptions/units only; quantities come from
the tender (already seeded from the package) and prices come from the human. DEMO reads a baked
fixture; a deterministic FALLBACK (the scope summary as the narrative, no invented items) means
the draft can never hard-fail.
"""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from pipeline.llm_client import LLMClient, demo_mode
from rules_engine.taxonomy import normalize as _normalize_trade
from schemas.estimate import EstimateDraft

ESTIMATE_DRAFT_FIXTURE = "cases/estimate/estimate_draft.json"

_SYSTEM = (
    "You help a Hong Kong main contractor build their OWN priced tender for a work package "
    "they will self-perform. Given the trade and the tendered scope, produce two things: "
    "(1) a concise scope-of-works narrative (a few sentences) describing the works to be "
    "priced; and (2) a candidate item skeleton — commonly-needed items that are NOT already "
    "in the tender's Schedule of Rates (e.g. mobilisation, standing-time contingency, "
    "testing), each with item_ref, description, and unit. Do NOT invent quantities or rates — "
    "the person quantifies and prices every line. Return JSON: "
    '{"scope_of_works": <string>, "items": [{"item_ref": <string>, "description": <string>, '
    '"unit": <string>}]}.'
)


def _prompt(trade: str, scope_summary: str, existing_refs: list[str]) -> str:
    refs = ", ".join(existing_refs) if existing_refs else "(none yet)"
    return (
        f"Trade: {trade}\n"
        f"Tendered scope: {(scope_summary or '').strip() or '(not provided)'}\n"
        f"Item refs already in the tender SoR: {refs}\n\n"
        "Draft the scope-of-works and propose only additional items not already listed."
    )


def _fallback_scope(trade: str, scope_summary: str) -> str:
    """A deterministic scope narrative from what we already hold — no invention."""
    summary = (scope_summary or "").strip()
    if summary:
        return summary
    label = (trade or "the works").replace("_", " ")
    return f"Self-perform the {label} package as tendered; scope to be confirmed against the tender documents."


def draft_estimate(
    trade: str, scope_summary: str, existing_refs: list[str], *,
    demo_fixture: Optional[str] = None, client: Optional[LLMClient] = None,
) -> dict:
    """Return ``{trade, scope_of_works, additional_items, trade_mapped}``. ``additional_items``
    are candidate lines NOT already present (deduped against ``existing_refs``), each carrying
    NO quantity or rate. ``trade_mapped`` is False when the trade is off-taxonomy (surfaced,
    never dropped)."""
    canon = _normalize_trade(trade)
    trade_key = canon or trade
    client = client or LLMClient()

    scope_out = _fallback_scope(trade_key, scope_summary)
    additional: list[dict] = []
    if demo_fixture or not demo_mode():
        try:
            drafted = client.complete_json(
                system=_SYSTEM, user=_prompt(trade_key, scope_summary, existing_refs),
                target_model=EstimateDraft, demo_fixture=demo_fixture, purpose="estimate-draft",
            )
            if drafted.scope_of_works.strip():
                scope_out = drafted.scope_of_works.strip()
            additional = [
                {"item_ref": it.item_ref.strip(), "description": (it.description or "").strip(), "unit": (it.unit or "").strip()}
                for it in drafted.items if it.item_ref.strip()
            ]
        except (RuntimeError, FileNotFoundError, ValidationError, ValueError):
            additional = []

    seen = {r.strip().lower() for r in existing_refs}
    deduped: list[dict] = []
    for it in additional:
        key = it["item_ref"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return {"trade": trade_key, "scope_of_works": scope_out, "additional_items": deduped, "trade_mapped": canon is not None}
