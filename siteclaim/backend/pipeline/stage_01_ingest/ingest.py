"""Stage 01 — ingest: TenderPackage -> ScopePackages.

Layer 2 (Claude) reads the tender documents and splits the work into one
:class:`TradeWorkPackage` per trade **or work section**, using the tender's own
discipline structure — a building/fit-out tender splits by trade (electrical, M&P,
fire services); a civil or ground-investigation tender splits by work section
(drilling, sampling, field testing, field installations, drainage works). Each
package carries a scope summary, the relevant SoR items, and ``source_refs`` naming
which document each came from. The model only splits and extracts; it never prices
or judges a firm.

Layer 1 then normalises every returned work-package key against the canonical
taxonomy (``rules_engine.taxonomy``, which reads ``references/rubrics/trade_taxonomy.md``):
a known label is mapped to its canonical key; an unknown one is kept under a
slugified key and surfaced for review — never dropped, never an error. The check is
deterministic Python, not the model, and runs cleanly on any tender type.

DEMO_MODE: ``complete_json`` short-circuits to a baked ``ScopePackages`` fixture and
never touches the network, exactly as the SiteClaim extract stage did.
"""

from __future__ import annotations

from typing import Optional

from pipeline.llm_client import LLMClient
from rules_engine.taxonomy import validate_scope
from schemas.models import ScopePackages, TenderPackage

_SYSTEM = (
    "You are a quantity-surveying assistant for a Hong Kong main contractor. "
    "Read the tender documents and SPLIT the works into one package per trade OR "
    "work section, using the tender's own discipline and section structure. A "
    "building or fit-out tender splits by trade (for example electrical, mechanical "
    "& plumbing, fire services, joinery & fitting-out); a civil or ground-"
    "investigation tender splits by work section (for example drilling, sampling, "
    "field testing, field installations, drainage works, slope works). For each "
    "package return a concise scope_summary, the relevant Schedule-of-Rates / Bills-"
    "of-Quantities items (item_ref, description, unit, qty), and source_refs naming "
    "which document each item came from. Use the tender's own terminology. "
    "You ONLY split and extract scope — you never price the work, never invent a "
    "quantity or rate, and never judge or rank a subcontractor. Return JSON matching "
    "the ScopePackages schema."
)


def _user_prompt(tender: TenderPackage) -> str:
    docs = "\n".join(f"- {d.doc_type.value}: {d.filename}" for d in tender.documents)
    return (
        f"Project: {tender.project_name}\n"
        f"Description: {tender.description}\n"
        f"Tender documents:\n{docs}\n\n"
        "Split this tender into work packages by trade or work section, "
        "whichever matches the tender's own structure."
    )


def ingest_tender(
    tender: TenderPackage,
    demo_fixture: Optional[str] = None,
    *,
    client: Optional[LLMClient] = None,
    images: Optional[list[str]] = None,
) -> ScopePackages:
    """Split ``tender`` into one :class:`TradeWorkPackage` per trade or work section.

    In DEMO_MODE the split is read from ``demo_fixture``; otherwise Layer 2 produces
    it (reading ``images`` — rendered tender pages — when given, for the live upload
    path). Either way Layer 1 normalises work-package keys against the taxonomy
    before returning, and runs cleanly on any tender type.
    """
    client = client or LLMClient()
    scope = client.complete_json(
        system=_SYSTEM,
        user=_user_prompt(tender),
        target_model=ScopePackages,
        demo_fixture=demo_fixture,
        images=images,
    )
    normalised, unmapped = validate_scope(scope)
    if unmapped:
        # Not a failure: non-canonical work sections are kept under a slugified key
        # and listed here for human review against the taxonomy.
        print(f"[ingest] non-canonical work sections (kept, slugified): {unmapped}")
    return normalised
