"""INGEST stage 02 — interpret one part.

Bucket: **AI**. Each split part gets a plain-language context card: what this part is, what
it obliges the contractor to do, and which of its content bears on price. Downstream stages
read these cards to decide which parts to open in full, so ingest pays once for reading and
the review does not re-read a 400-page binder to find its pricing schedule.

Two rules govern this stage, and they are the reason it is per-part rather than per-set:

* **A part we cannot read is catalogued, never guessed.** A scanned part with no text layer
  gets one attempt through vision; if that fails too, the card says "unreadable" and says
  why. Fabricating a summary for an unread part would poison every stage downstream.
* **A part that fails to interpret is a flagged card, not a failed job.** The set still
  ingests. This matches the module's existing no-silent-drops invariant, where unmatched
  criteria become ``unresolved`` rather than disappearing.
"""

from __future__ import annotations

from client_boq.ingest import pdfops
from client_boq.models import (
    PART_CATEGORIES,
    RULE_ALTERNATIVES_NOT_CONSIDERED,
    RULE_NO_ALTERATIONS,
    RULE_QUALIFICATIONS_PENALISED,
    RULE_QUERY_CUTOFF,
    RULE_SUBMISSION_DEADLINE,
    RULE_TWO_ENVELOPE,
    PartContext,
    PartSpec,
)
from pipeline.llm_client import LLMClient, demo_mode
from client_boq.llm import make_client

DEMO_FIXTURE = "cases/client_boq/ingest_interpret_part.json"

# How much of a part's text to send. A part is already one coherent section, so the head of
# it carries the definition; the review stage reads the whole thing later, chunked.
MAX_TEXT_CHARS = 24000
# Vision pages for a scanned part. Deliberately small: enough to identify and summarise the
# part, not to transcribe it.
MAX_SCAN_PAGES = 6

_SYSTEM = (
    "You are a construction contract analyst writing an orientation note for a colleague "
    "who has never seen this tender. You explain what a document part is and what it "
    "requires, in plain language, for a reader with no construction-law background. "
    "You never invent content: if the text does not say something, you do not say it. "
    "You read and summarise; you never judge, price, or decide. "
    "Return ONLY JSON matching the schema."
)

_INSTRUCTION = f"""Write the context card for this part of a tender document.

Return:
- summary: 2-4 sentences. What this part IS and why it exists in the tender. Plain language.
- key_points: the specific, concrete facts a reader needs (named parties, dates, sums,
  durations, percentages, reference numbers). Quote figures exactly as printed.
- obligations: what this part requires OF THE CONTRACTOR, one per line.
- commercial_flags: anything here that bears on price or carries commercial risk — caps,
  liquidated damages, insurance limits, retention, payment terms, termination rights.
  Describe them; do not rate or judge them.
- category: one of {", ".join(PART_CATEGORIES)}.
- strategy_flags: conditions that change how the tender must be BID rather than what it costs.
  Look specifically for, and quote exactly if present:
    * "{RULE_QUALIFICATIONS_PENALISED}" — any statement that qualifying the tender, or qualifying
      the tender documents, may cause the tender to be rejected or disqualified.
    * "{RULE_NO_ALTERATIONS}" — any prohibition on altering or erasing the text of the documents.
    * "{RULE_ALTERNATIVES_NOT_CONSIDERED}" — alternative or uninvited tenders will not be considered.
    * "{RULE_TWO_ENVELOPE}" — technical and price submissions must be separately sealed.
    * "{RULE_QUERY_CUTOFF}" — the deadline for submitting questions or requests for clarification.
    * "{RULE_SUBMISSION_DEADLINE}" — the tender closing date and time.
  Give each one its clause reference as printed, its page, and the clause's own words verbatim.
  Quote, never paraphrase: a person will check these against the document. Return an empty list
  when the part contains none of them, which is the normal case for most parts.
- notes: anything you could not read or were unsure of.

If the content is unreadable or too fragmentary to summarise, say so in `notes` and leave
the other fields empty. An honest blank is correct; a plausible guess is not.

=== PART ==="""


def _header(part: PartSpec, source_doc: str) -> str:
    return (
        f"\ntitle: {part.title}\n"
        f"source document: {source_doc}\n"
        f"pages: {part.start}-{part.end} of the source ({part.page_count()} pages)\n"
        f"draft category: {part.category}\n\n=== TEXT ===\n"
    )


def interpret_part(
    part: PartSpec, part_bytes: bytes, source_doc: str = "", source_bytes: bytes = b"",
) -> PartContext:
    """Produce one part's context card. Never raises: an unreadable or failing part comes
    back flagged, because one bad part must not sink the whole ingest."""
    client = make_client()  # app-wide model setting applied here (client_boq/llm.py)
    base = PartContext(part_id=part.part_id, title=part.title, category=part.category)

    # Read the part FIRST, in every mode. Whether a part has usable text is a measurement, and
    # it decides honesty: a part we cannot read must come back flagged even in DEMO, or the
    # offline demo quietly fabricates content for a scan — the one thing this stage must never
    # do. Only a part that really is readable gets the DEMO fixture.
    text = pdfops.page_text(part_bytes, 1, part.page_count()) if part_bytes else ""

    if demo_mode():
        if not text.strip():
            return base.model_copy(update={
                "readable": False,
                "notes": (
                    f"This part ({part.page_count()} pages, {part.start}-{part.end}) is image-only "
                    f"with no readable text. Reading it needs vision, which DEMO mode does not "
                    f"call. It is catalogued but its content has not been read."
                ),
            })
        context = client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION, target_model=PartContext,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-ingest-interpret",
        )
        # The fixture is one generic card; stamp it with this part's real identity so the
        # DEMO output is still navigable per part.
        return context.model_copy(update={
            "part_id": part.part_id, "title": part.title, "category": part.category,
        })

    images: list[str] = []
    if len(text.strip()) < pdfops.SCANNED_CHAR_THRESHOLD * max(1, part.page_count() // 4):
        # Little or no text layer: give it its one look through vision before giving up.
        try:
            from pipeline.documents import to_images

            images = to_images(part_bytes, "application/pdf", max_pages=MAX_SCAN_PAGES)
        except Exception as exc:  # noqa: BLE001 — vision is the fallback, not a requirement
            if not text.strip():
                return base.model_copy(update={
                    "readable": False,
                    "notes": (
                        f"This part ({part.page_count()} pages, {part.start}-{part.end}) has no "
                        f"text layer and could not be rendered for visual reading ({exc}). It is "
                        f"catalogued but its content has not been read."
                    ),
                })

    if not text.strip() and not images:
        return base.model_copy(update={
            "readable": False,
            "notes": (
                f"This part ({part.page_count()} pages, {part.start}-{part.end}) is image-only "
                f"with no readable text. It is catalogued but its content has not been read."
            ),
        })

    user = _INSTRUCTION + _header(part, source_doc) + text[:MAX_TEXT_CHARS]
    try:
        context = client.complete_json(
            system=_SYSTEM, user=user, target_model=PartContext,
            images=images or None, purpose="client_boq-ingest-interpret",
        )
    except Exception as exc:  # noqa: BLE001 — a flagged card, never a failed job
        return base.model_copy(update={
            "readable": False,
            "notes": f"Interpreting this part failed ({exc}). It is catalogued but not summarised.",
        })

    category = context.category if context.category in PART_CATEGORIES else part.category
    return context.model_copy(update={
        "part_id": part.part_id, "title": part.title or context.title, "category": category,
        "readable": True,
    })


def card_markdown(part: PartSpec, context: PartContext, source_doc: str) -> str:
    """The human-readable context card written beside the part PDF.

    Deliberately a file on disk as well as a row in SQLite: the point of the interpreted
    context is that a person can open the folder and read what the tender says.
    """
    lines = [
        "---",
        f"part_id: {part.part_id}",
        f"title: {part.title}",
        f"category: {context.category}",
        f"source: {source_doc}",
        f"pages: {part.start}-{part.end}",
        f"readable: {str(context.readable).lower()}",
        "---",
        "",
        f"# {part.n:02d} {part.title}",
        "",
    ]
    if not context.readable:
        lines += ["> **Not read.** " + (context.notes or "No readable content."), ""]
        return "\n".join(lines)

    if context.summary:
        lines += [context.summary, ""]
    for heading, values in (
        ("Key points", context.key_points),
        ("What it requires of the contractor", context.obligations),
        ("Commercial and pricing content", context.commercial_flags),
    ):
        if values:
            lines += [f"## {heading}", ""]
            lines += [f"- {v}" for v in values]
            lines.append("")
    if context.notes:
        lines += ["## Notes", "", context.notes, ""]
    return "\n".join(lines)
