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

from typing import Optional

from pipeline.llm_client import LLMClient
from rules_engine.taxonomy import CANONICAL_TRADES, validate_scope
from schemas.models import ScopePackages, TenderPackage


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
        "one package per sub-section — and no package for a trade that is not present."
    )


def _user_prompt(tender: TenderPackage) -> str:
    docs = "\n".join(f"- {d.doc_type.value}: {d.filename}" for d in tender.documents)
    return (
        f"Project: {tender.project_name}\n"
        f"Description: {tender.description}\n"
        f"Tender documents:\n{docs}\n\n"
        "Split this tender into trade work packages."
    )


def ingest_tender(
    tender: TenderPackage,
    demo_fixture: Optional[str] = None,
    *,
    client: Optional[LLMClient] = None,
    images: Optional[list[str]] = None,
) -> ScopePackages:
    """Split ``tender`` into one :class:`TradeWorkPackage` per trade.

    In DEMO_MODE the split is read from ``demo_fixture``; otherwise Layer 2 produces
    it (reading ``images`` — rendered tender pages — when given, for the live upload
    path). Either way Layer 1 normalises trades against the taxonomy before returning.
    """
    client = client or LLMClient()
    scope = client.complete_json(
        system=_system_prompt(),
        user=_user_prompt(tender),
        target_model=ScopePackages,
        demo_fixture=demo_fixture,
        images=images,
    )
    # project_name is known from the tender — inject it rather than depend on the model
    # echoing it (a newer model may omit it; ScopePackages defaults it to "").
    if not scope.project_name:
        scope = scope.model_copy(update={"project_name": tender.project_name})
    normalised, unmapped = validate_scope(scope)
    if unmapped:
        # Surfaced, not dropped — a human reconciles these against the taxonomy.
        print(f"[ingest] unmapped trades (kept for review): {unmapped}")
    return normalised
