"""INGEST stage 01 — plan the split.

Bucket: **AI propose -> Det validate**. Deterministic inspection has already produced a
draft manifest with arithmetically sound page ranges (from bookmarks, the contents page,
or divider detection). This stage asks the model to REFINE that draft: give each part a
useful title, assign it a canonical category, and merge or split where the document's own
structure misleads (a bookmark tree that buries the appendices inside "Conditions", say).

The model never invents ranges from nothing and never approves anything. Its proposal is
checked by ``pdfops.validate`` against the real page count; a proposal that fails is
rejected and the deterministic draft stands. That is the ingest expression of the module's
one principle: the LLM reads and proposes, code decides.
"""

from __future__ import annotations

from client_boq.ingest import pdfops
from client_boq.models import PART_CATEGORIES, InspectReport, PlannedSplit, SplitManifest
from pipeline.llm_client import LLMClient, demo_mode
from client_boq.llm import STAGE_INGEST, make_client

DEMO_FIXTURE = "cases/client_boq/ingest_plan_split.json"

_SYSTEM = (
    "You are a construction tender document analyst. You are given the structure of one "
    "combined tender binder — its bookmark outline, its page count, which pages carry no "
    "text layer, and a draft split derived from that structure. You refine the draft into "
    "the set of parts a quantity surveyor would actually file separately. "
    "You describe structure; you never judge, price, or decide anything. "
    "Return ONLY JSON matching the schema."
)

_INSTRUCTION = f"""Refine the draft split of this tender document.

Rules you must follow:
- Page ranges are 1-based inclusive PHYSICAL pages of the source PDF.
- The parts must cover every page from 1 to the page count, in order, with no gaps and no
  overlaps. Adjacent parts touch: one ends on page N, the next starts on page N+1.
- Keep the draft's boundaries unless the document's structure clearly argues otherwise.
  Good reasons to depart: a bookmark lumps a body of clauses together with its appendices
  (split them); several bookmarks are one continuous document (merge them); a part is a
  single cover or divider page (fold it into the part it introduces).
- Give every part a `category` from exactly this list: {", ".join(PART_CATEGORIES)}.
  Use "other" honestly when nothing fits. Do not force a fit.
- `abbr` is a short upper-case tag (2-4 characters) used as a folder name, e.g. CT, BQ, DRG.
- `slug` is lower-case kebab-case, under 32 characters.
- `title` is what the document itself calls this part.
- Number the parts `n` from 1 in page order.
- Put anything the human reviewing this split should know in `notes`.

=== DOCUMENT ===
"""


def _digest(report: InspectReport, max_outline: int = 220) -> str:
    """A compact, faithful description of the document for the planning prompt.

    Only structure goes in: titles, page numbers, the draft, and where the text layer is
    missing. Never the body text — this call decides boundaries, not content, and sending
    400 pages of prose to place 12 cuts is exactly the waste this stage exists to prevent.
    """
    lines = [
        f"filename: {report.filename}",
        f"pages: {report.pages}",
        f"title metadata: {report.metadata.get('title', '') or '(none)'}",
        f"pages with no text layer: {report.scanned_pages or '(none)'}",
        "",
        f"bookmark outline ({len(report.outline)} entries"
        + (f", showing the first {max_outline}" if len(report.outline) > max_outline else "")
        + "):",
    ]
    if report.outline:
        for node in report.outline[:max_outline]:
            indent = "  " * (node.depth - 1)
            lines.append(f"  {indent}p{node.page or '?'}  {node.title}")
    else:
        lines.append("  (the PDF declares no bookmarks)")

    lines += ["", f"draft split (tier {report.draft.tier}: {report.draft.tier_reason}):"]
    for part in report.draft.parts:
        lines.append(f"  {part.n:>2}. p{part.start}-{part.end}  {part.title}")

    if report.toc_text:
        lines += ["", "the document's own contents page:", report.toc_text[:4000]]
    return "\n".join(lines)


def _renumber(manifest: SplitManifest) -> SplitManifest:
    """Order the parts by first page and renumber from 1, so ``part_id`` is stable and the
    folder names sort in document order however the model happened to emit them."""
    manifest.parts.sort(key=lambda p: (p.start, p.end))
    for index, part in enumerate(manifest.parts, start=1):
        part.n = index
        part.abbr = (part.abbr or pdfops.abbreviate(part.title)).upper()[:4]
        part.slug = pdfops.slugify(part.slug or part.title)
        if part.category not in PART_CATEGORIES:
            part.category = "other"
    return manifest


def plan_split(report: InspectReport, set_id: str = "") -> SplitManifest:
    """Refine the deterministic draft into the operative manifest.

    Degrades rather than fails: if the model's proposal does not validate against the real
    page count, the deterministic draft is kept and the reason is recorded on the manifest
    for the human at the gate to see.
    """
    # The document-reading stage picks its own provider: EXTRACTION_PROVIDER, or the
    # ingest setting, before the app-wide one (client_boq/llm.py).
    client = make_client(stage=STAGE_INGEST)
    draft = report.draft.model_copy(deep=True)
    draft.set_id = set_id

    if demo_mode():
        planned = client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION, target_model=PlannedSplit,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-ingest-plan-split",
        )
    else:
        planned = client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION + _digest(report), target_model=PlannedSplit,
            purpose="client_boq-ingest-plan-split",
        )

    if not planned.parts:
        draft.tier_reason += " | the planning call returned no parts; kept the draft split"
        return draft

    proposed = _renumber(draft.model_copy(deep=True, update={"parts": list(planned.parts)}))
    errors, warnings = pdfops.validate(proposed, report.pages)
    if errors:
        draft.tier_reason += (
            " | the planning call proposed a split that does not fit the document ("
            + "; ".join(errors[:3]) + ") so the deterministic draft was kept"
        )
        return draft

    # Re-stamp the measured facts. The planner may rename, merge and split; it may not decide
    # whether a page has a text layer.
    pdfops.mark_scanned(proposed.parts, report.scanned_pages)
    if planned.notes:
        proposed.tier_reason += f" | planner: {planned.notes}"
    if warnings:
        proposed.tier_reason += " | " + "; ".join(warnings[:3])
    return proposed
