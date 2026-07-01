"""Stage 01 — document classification for per-trade routing (Layer 2).

Stage 01's scope split tags SoR *items* by trade, but the whole-file routing in
:func:`pipeline.stage_03_dispatch.attachments.route_documents` reads
``TenderDocument.trades`` — and on the live upload path nothing populated it, so every
document was treated as general and every subcontractor received every original. This
module fills that gap: the LLM classifies each uploaded document as **general** (every
trade needs it) or **trade-specific** (which trade), and writes the result to
``TenderDocument.trades`` so the tagged tender can flow to ``/dispatch``.

Rules (see BUILD_PLAN.md §5 and the task brief — these are settled):

* **Whole-file routing only.** Classification never slices or extracts pages. A
  combined multi-section Schedule of Rates is sent whole to everyone as the legal
  reference; the per-trade priceable items are delivered by the existing
  :func:`~pipeline.stage_03_dispatch.attachments.generate_sor_sheet`.
* **Per document, from its own first pages.** Each document is classified from its own
  first one or two rendered pages (the type/section sits on the header page), never by
  reconstructing which page belongs to which file from a merged list.
* **Normalised against the canonical taxonomy** (:func:`rules_engine.taxonomy.normalize`),
  the same way scope validation does. An unmapped label is *surfaced for review, never
  silently dropped*. On low confidence — or when a label maps to nothing — the document
  is classified **general** (empty ``trades``): sending a document to everyone is safe,
  withholding a relevant one is the failure mode to avoid.

DEMO_MODE: this runs on the live upload path only. ``complete_json`` short-circuits to
a fixture and opens no socket offline; the module imports no provider SDK.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from pipeline.llm_client import LLMClient
from rules_engine import taxonomy
from schemas.models import TenderDocument, TenderPackage

MIN_CONFIDENCE = 0.5

_SYSTEM = (
    "You route a Hong Kong tender's documents to subcontractors by trade. Classify the "
    "ONE attached document (its first pages are shown) as either GENERAL — every trade "
    "needs it: form of tender, conditions of contract, general preliminaries, method of "
    "measurement, a COMBINED multi-section or multi-trade Schedule of Rates, or generic "
    "appendices and forms — or TRADE-SPECIFIC: a particular-specification section or a "
    "single-trade Schedule of Rates for one discipline. Read the header/first page to "
    "identify the document. Set general=true for any whole-tender or multi-trade "
    "document. Otherwise set general=false and list the specific trade(s) in `trades` "
    "using Hong Kong construction trade names (e.g. electrical, fire services, "
    "mechanical & plumbing, joinery / fitting-out, reinforced concrete, foundation / "
    "substructure, landscape / tree works, external works). Give a confidence 0..1. When "
    "unsure, prefer general — sending a document to everyone is safe; withholding a "
    "relevant one is not. Never split or extract pages. Return JSON matching the schema."
)


class DocClassification(BaseModel):
    """Layer-2 result for one document: general, or specific to some trade(s)."""

    general: bool = False
    trades: list[str] = Field(default_factory=list)
    confidence: float = 0.0


def _doc_prompt(doc: TenderDocument) -> str:
    return (
        f"Document type (as uploaded): {doc.doc_type.value}\n"
        f"Filename: {doc.filename}\n"
        "Classify this single document as general or trade-specific."
    )


def _resolve_trades(result: DocClassification) -> list[str]:
    """Map a classification to canonical trade keys (empty = general).

    General, low-confidence, or all-unmapped classifications resolve to ``[]`` (safe:
    routed to everyone). Mapped trades are de-duplicated, order-stable; unmapped labels
    are surfaced for human review rather than routed to nobody.
    """
    if result.general or result.confidence < MIN_CONFIDENCE:
        return []
    mapped: list[str] = []
    unmapped: list[str] = []
    for label in result.trades:
        key = taxonomy.normalize(label)
        if key is None:
            unmapped.append(label)
        elif key not in mapped:
            mapped.append(key)
    if unmapped:
        # Surfaced, not routed to a non-existent trade (which would reach nobody).
        print(f"[classify] unmapped document trades (general-routed, surfaced for review): {unmapped}")
    return mapped


def classify_documents(
    tender: TenderPackage,
    per_doc_images: Optional[list[list[str]]] = None,
    *,
    demo_fixture: Optional[str] = None,
    client: Optional[LLMClient] = None,
) -> TenderPackage:
    """Return ``tender`` with each document's ``trades`` populated by Layer 2.

    ``per_doc_images[i]`` are the first one or two rendered pages of ``tender.documents[i]``
    (the live vision path); pass ``None`` for a text-only classification. A per-document
    classification error falls back to **general** (empty trades) — never a withheld
    document. The input tender is not mutated; a tagged copy is returned.
    """
    client = client or LLMClient()
    tagged: list[TenderDocument] = []
    for index, doc in enumerate(tender.documents):
        images = per_doc_images[index] if per_doc_images and index < len(per_doc_images) else None
        try:
            result = client.complete_json(
                system=_SYSTEM,
                user=_doc_prompt(doc),
                target_model=DocClassification,
                demo_fixture=demo_fixture,
                images=images,
            )
            trades = _resolve_trades(result)
        except (RuntimeError, FileNotFoundError, ValidationError, ValueError) as exc:
            # Any classification hiccup routes the document general — the safe direction.
            print(f"[classify] classification failed for {doc.filename!r} ({exc}); routing general.")
            trades = []
        tagged.append(doc.model_copy(update={"trades": trades}))
    return TenderPackage(
        project_name=tender.project_name,
        description=tender.description,
        documents=tagged,
    )
