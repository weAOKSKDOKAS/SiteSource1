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

import re
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from pipeline.llm_client import LLMClient
from rules_engine import taxonomy
from schemas.models import DocType, TenderDocument, TenderPackage

MIN_CONFIDENCE = 0.5

# -- Layer-1 deterministic doc-type signals (run BEFORE any LLM call) -------------------------
# Hong Kong tender document sets are filename-disciplined ("…-SR-…", "…-MM-…", "…-PS-S07-…"), so
# the KIND that gates item extraction can be decided by a regex over the name / first-page title —
# removing the classifier's non-determinism (a per-run LLM call that, on any hiccup, used to leave
# the SCHEDULE_OF_RATES seed in place and turn a Method of Measurement into phantom priced items).
# A filename token wins over the page title on purpose: an MM's page 1 mentions "Schedule of Rates"
# repeatedly, so its "-MM-" token must decide the kind before any title text is read. Order matters —
# the first matching pattern wins; PS-S## is checked before the bare APPENDIX token.
_FILENAME_SIGNALS: list[tuple[re.Pattern, DocType]] = [
    (re.compile(r"(?i)(?<![A-Za-z])S(?:OR|R)(?![A-Za-z])"), DocType.SCHEDULE_OF_RATES),  # -SR- / -SOR-
    (re.compile(r"(?i)(?<![A-Za-z])MM(?![A-Za-z])"), DocType.METHOD_OF_MEASUREMENT),      # -MM-
    (re.compile(r"(?i)(?<![A-Za-z])P?S[-_ ]?S\d+"), DocType.PARTICULAR_SPECIFICATION),    # PS-S07 / GS-S26
    (re.compile(r"(?i)APPENDIX"), DocType.GENERAL),                                        # appendix -> context
    (re.compile(r"(?i)CLARIF|ADDEND"), DocType.TENDER_ADDENDUM),
]
# First-page TITLE text (line-start anchored, so an inline mention is not taken as the title).
_TITLE_SIGNALS: list[tuple[re.Pattern, DocType]] = [
    (re.compile(r"(?im)^\s*(?:THE\s+)?SCHEDULE\s+OF\s+RATES"), DocType.SCHEDULE_OF_RATES),
    (re.compile(r"(?im)^\s*METHOD\s+OF\s+MEASUREMENT"), DocType.METHOD_OF_MEASUREMENT),
    (re.compile(r"(?im)^\s*(?:PARTICULAR|GENERAL)\s+SPECIFICATION"), DocType.PARTICULAR_SPECIFICATION),
    (re.compile(r"(?im)^\s*APPENDIX\s+\d"), DocType.GENERAL),
    (re.compile(r"(?im)^\s*(?:CLARIFICATION|TENDER\s+ADDENDUM|ADDENDUM)"), DocType.TENDER_ADDENDUM),
]

def _system_prompt() -> str:
    """The classification instruction, embedding the canonical trades so a trade-specific
    document maps to the same keys the scope split and shortlist use — and a geotechnical
    spec (PS-S07) lands on ``ground_investigation``, not ``foundation_substructure``.

    Two INDEPENDENT axes are requested: ``general`` (routing — does every trade get the
    whole file?) and ``doc_type`` (what KIND of document it is, which gates item
    extraction). They are orthogonal: a combined Schedule of Rates is ``general=true``
    (routed to everyone) yet ``doc_type=schedule_of_rates`` (its priced rows are
    extracted); a Method of Measurement is also ``general=true`` but
    ``doc_type=method_of_measurement`` so its item-like rows are NOT extracted as prices."""
    trades = ", ".join(sorted(taxonomy.CANONICAL_TRADES))
    return (
        "You route a Hong Kong tender's documents to subcontractors by trade AND identify "
        "each document's kind. Read the ONE attached document (its first pages are shown).\n\n"
        "ROUTING — set `general`=true for any whole-tender or multi-trade document every "
        "trade needs: form of tender, conditions of contract, general preliminaries, method "
        "of measurement, a COMBINED multi-section or multi-trade Schedule of Rates, or "
        "generic appendices and forms. Otherwise set `general`=false and list the specific "
        f"trade(s) in `trades` using ONE OR MORE of these canonical trades: {trades}. Choose "
        "the closest key — a geotechnical / ground-investigation / site-investigation / "
        "drilling spec is `ground_investigation`, NOT `foundation_substructure`. Clarifications, "
        "addenda, the method of measurement and general conditions are cross-trade: mark them "
        "`general`=true with an empty `trades`, never leaning to the tender's dominant trade.\n\n"
        "KIND — set `doc_type` to exactly one of: `schedule_of_rates` (a priced/priceable "
        "Schedule of Rates, whether single-trade or combined), `particular_specification`, "
        "`method_of_measurement`, `clarification` (a clarification or tender addendum), or "
        "`general` (conditions of contract, preliminaries, forms, anything else). `doc_type` "
        "is INDEPENDENT of `general`: a combined SoR is general=true AND "
        "doc_type=schedule_of_rates.\n\n"
        "Give a confidence 0..1. When unsure on routing, prefer general — sending a document "
        "to everyone is safe; withholding a relevant one is not. Never split or extract "
        "pages. Return JSON matching the schema."
    )


class DocClassification(BaseModel):
    """Layer-2 result for one document: routing (general / trades) plus its kind (doc_type)."""

    general: bool = False
    trades: list[str] = Field(default_factory=list)
    doc_type: str = ""  # schedule_of_rates | particular_specification | method_of_measurement | clarification | general
    confidence: float = 0.0


# doc_type label (from the model) -> canonical DocType. Only schedule_of_rates gates item
# extraction on; the rest are recorded but never feed the priced-item split.
_DOC_TYPE_ALIASES = {
    "schedule_of_rates": DocType.SCHEDULE_OF_RATES,
    "sor": DocType.SCHEDULE_OF_RATES,
    "particular_specification": DocType.PARTICULAR_SPECIFICATION,
    "particular_spec": DocType.PARTICULAR_SPECIFICATION,
    "specification": DocType.PARTICULAR_SPECIFICATION,
    "spec": DocType.PARTICULAR_SPECIFICATION,
    "method_of_measurement": DocType.METHOD_OF_MEASUREMENT,
    "mom": DocType.METHOD_OF_MEASUREMENT,
    "clarification": DocType.TENDER_ADDENDUM,
    "addendum": DocType.TENDER_ADDENDUM,
    "tender_addendum": DocType.TENDER_ADDENDUM,
    "general": DocType.GENERAL,
    "conditions_of_contract": DocType.GENERAL,
    "general_conditions": DocType.GENERAL,
    "preliminaries": DocType.GENERAL,
}


def _resolve_doc_type(label: str) -> Optional[DocType]:
    """Map a model doc_type label to a canonical :class:`DocType` (None if unrecognised)."""
    key = (label or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _DOC_TYPE_ALIASES.get(key)


_DOC_TEXT_SNIPPET_CHARS = 2000  # the header / first page identifies the kind; a snippet suffices


def _deterministic_doc_type(filename: str, text: str = "") -> tuple[Optional[DocType], str]:
    """The document's kind from deterministic Layer-1 signals, or ``(None, "")`` when none applies.

    Filename tokens first (they win over the page title so an MM's SoR mentions cannot flip it), then
    the first-page TITLE — of the title matches, the EARLIEST wins, so a document's own top-of-page
    title beats a later inline mention of another kind. Pure regex; writes no decision value."""
    name = filename or ""
    for pattern, dt in _FILENAME_SIGNALS:
        if pattern.search(name):
            return dt, "filename"
    head = (text or "")[:_DOC_TEXT_SNIPPET_CHARS]
    best_pos: Optional[int] = None
    best_dt: Optional[DocType] = None
    for pattern, dt in _TITLE_SIGNALS:
        m = pattern.search(head)
        if m is not None and (best_pos is None or m.start() < best_pos):
            best_pos, best_dt = m.start(), dt
    return (best_dt, "title") if best_dt is not None else (None, "")


def _doc_prompt(doc: TenderDocument, text: str = "") -> str:
    base = (
        f"Document type (as uploaded): {doc.doc_type.value}\n"
        f"Filename: {doc.filename}\n"
    )
    if text.strip():
        base += (
            "\n=== First extracted text of this document (use it to identify the kind and "
            "trade) ===\n" + text.strip()[:_DOC_TEXT_SNIPPET_CHARS] + "\n\n"
        )
    return base + "Classify this single document as general or trade-specific."


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
    per_doc_text: Optional[list[str]] = None,
    demo_fixture: Optional[str] = None,
    client: Optional[LLMClient] = None,
) -> TenderPackage:
    """Return ``tender`` with each document's ``trades`` and ``doc_type`` populated by L2.

    **Text-first**: when ``per_doc_text[i]`` has a usable text layer the document is
    classified from a text snippet (no image is attached, so the call routes to the cheap
    text provider); only a scanned document with no text falls back to vision, using
    ``per_doc_images[i]`` (its first one or two rendered pages).

    **Fail safe on BOTH axes.** A per-document error, a low-confidence read, or an
    unrecognised label falls back to **general** for routing (empty trades — never a
    withheld document) AND to the neutral ``DocType.GENERAL`` kind — never the caller's
    seed. So a classification hiccup can promote nothing into the priced-item path; each
    document records how its kind was decided in ``doc_type_source`` (``llm`` | ``fallback``)
    so the caller can surface the fallbacks. The input tender is not mutated; a tagged copy
    is returned.
    """
    client = client or LLMClient()
    tagged: list[TenderDocument] = []
    for index, doc in enumerate(tender.documents):
        text = per_doc_text[index] if per_doc_text and index < len(per_doc_text) else ""
        # Layer 1 first: a deterministic filename / title signal decides the kind with NO LLM call,
        # and is FINAL — the LLM cannot override it. Routing stays general (empty trades): sending a
        # whole file to everyone is the safe default, and the relevant-doc assembler slices per
        # section at dispatch regardless. Only a signal-less document reaches the classifier below.
        det_type, det_source = _deterministic_doc_type(doc.filename, text)
        if det_type is not None:
            tagged.append(doc.model_copy(update={"doc_type": det_type, "doc_type_source": det_source, "trades": []}))
            continue
        # Text-first: a usable text layer classifies from text (cheap provider, no render);
        # only a scanned document with no text is sent to vision.
        images = None if text.strip() else (
            per_doc_images[index] if per_doc_images and index < len(per_doc_images) else None
        )
        # Fail SAFE: default to the NEUTRAL kind, never the caller's seed. A document only leaves
        # this loop as a Schedule of Rates (or any specific kind) when the classifier CONFIDENTLY
        # resolves it — so a timeout, a JSON/validation error, a low-confidence read, or an
        # unrecognised label can never promote a document into the priced-item path by inertia.
        doc_type: DocType = DocType.GENERAL
        source = "fallback"
        trades: list[str] = []
        try:
            result = client.complete_json(
                system=_system_prompt(),
                user=_doc_prompt(doc, text),
                target_model=DocClassification,
                demo_fixture=demo_fixture,
                images=images,
                purpose="classify",
            )
            trades = _resolve_trades(result)
            resolved_type = _resolve_doc_type(result.doc_type)
            if resolved_type is not None and result.confidence >= MIN_CONFIDENCE:
                doc_type, source = resolved_type, "llm"
            else:
                # Recognised-but-low-confidence, or an unrecognised label -> neutral (general), surfaced.
                print(f"[classify] {doc.filename!r}: doc_type not confidently resolved "
                      f"(label={result.doc_type!r}, confidence={result.confidence}); routing general as context.")
        except (RuntimeError, FileNotFoundError, ValidationError, ValueError) as exc:
            # Any classification hiccup -> general (empty trades), the safe direction.
            print(f"[classify] classification failed for {doc.filename!r} ({exc}); routing general as context.")
        tagged.append(doc.model_copy(update={"trades": trades, "doc_type": doc_type, "doc_type_source": source}))
    return TenderPackage(
        project_name=tender.project_name,
        description=tender.description,
        documents=tagged,
    )
