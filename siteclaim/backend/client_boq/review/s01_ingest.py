"""REVIEW stage 01 — ingest the client's document set.

Bucket (client_boq_layer_mapping.md tasks 1a/1c): **Deterministic + AI**. Deterministic text/page
extraction reuses ``pipeline.documents.extract_document`` (pymupdf + Tesseract); the AI half
structures the extracted text into typed clauses with **stable clause ids** and page/locus
references — the identities s08 later verifies citations against. Reading, not deciding.

Two ways in:

* **From an ingested set** (the normal path once a tender has been through ``/ingest``): walk
  the approved parts, read each part's own pages, and structure them a part at a time. Each
  clause then carries the part it came from, so a citation points at a page range rather than
  a filename.
* **From raw uploads** (a single small document with nothing to split): the original path,
  unchanged.

The part-at-a-time path exists because the raw path cannot survive a real tender binder. It
concatenated every document into one prompt against an 8,000-token output ceiling, and
``extract_document`` silently stops at page 200 — so a 411-page binder lost half its pages and
then truncated. Splitting first turns one impossible call into a dozen ordinary ones.

DEMO stays fully offline: ``complete_json`` short-circuits to the fixture ``ParsedDocumentSet`` and
no extraction/network runs (the fixture already *is* a structured parse). The caller (``run.py``)
assigns the set identity and persists the result; this stage only produces the parse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from client_boq.models import ClauseItem, ParsedDocumentSet, PartSpec, RawUpload
from pipeline.documents import extract_document
from pipeline.llm_client import LLMClient, demo_mode
from client_boq.llm import make_client
from pipeline.workspace import Workspace

DEMO_FIXTURE = "cases/client_boq/review_ingest.json"

# One part's text is still too big for one call when the part is a 100-page appendix set, so
# chunk it. Mirrors the procurement ingest's MAX_CHUNK_CHARS, which exists for the same reason.
MAX_CHUNK_CHARS = 12000

_SYSTEM = (
    "You are a construction contract analyst. You read tender/contract documents and structure them "
    "into individual clauses for downstream review. You extract; you never judge, score, or decide. "
    "Return ONLY JSON matching the schema."
)

_INSTRUCTION = (
    "Structure the following contract document set into clauses.\n"
    "For every clause return: clause_id (the reference exactly as printed, e.g. '9.9' or '4.8.6'), "
    "ref (the printed label), heading (short title if present), text (the clause's full text), "
    "source_doc (the document filename it came from), and page (1-based page number if known).\n"
    "Preserve clause ids verbatim — later stages cite them. Do not invent clauses, do not merge "
    "distinct clauses, and do not drop any. Return {\"clauses\": [...]} plus the document names.\n\n"
    "=== DOCUMENTS ===\n"
)


def _chunk(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on page boundaries so a clause is never cut in half mid-sentence.

    ``extract_document`` and ``pdfops.page_text`` both prefix each page with ``[page N]``, which
    gives a natural, content-independent seam to break on.
    """
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n[page "):
        piece = block if not chunks and not current else "\n\n[page " + block
        if current and len(current) + len(piece) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current.strip():
        chunks.append(current)
    return chunks


def _structure(client: LLMClient, body: str, label: str) -> list[ClauseItem]:
    """One structuring call. A chunk that fails is reported and skipped, never fatal — losing
    one chunk of one part must not lose the whole document set."""
    try:
        parsed = client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION + body, target_model=ParsedDocumentSet,
            purpose=f"client_boq-review-ingest-{label}",
        )
    except Exception:  # noqa: BLE001 — a failed chunk is a gap, not a crash
        return []
    return list(parsed.clauses)


# Categories the review does NOT read for contractual positions.
#
# A bill of quantities has no contractual clauses. Reading one for them produced six structuring
# calls that each returned exactly 8,000 output tokens — two retried and still at the ceiling —
# and a register whose findings were "No letter of offer in the document set" and "No tender
# clarifications in the document set": true, and useless, because the set contained only a bill.
# A drawing set is geometry; its text layer is title blocks and annotations.
#
# A SKIP-list rather than an allow-list, deliberately. Every other category can carry a
# contractual position — safety requirements are obligations, bid forms carry the form of tender —
# and `other` is the honestly-uncategorised bucket, so excluding it would silently drop a
# contractual document the classifier failed to place, which is the exact failure this module
# exists to prevent. A skip-list also means a category added to PART_CATEGORIES later is read by
# default rather than dropped by omission. Spending a call is cheaper than losing a clause.
NON_CONTRACTUAL_CATEGORIES = frozenset({"pricing", "drawings"})


def effective_category(part: PartSpec, context: Optional[object] = None) -> tuple[str, str]:
    """``(category, whose)`` for one part — the INTERPRETED category when there is one.

    There are two categories in this system and they are not equally good.

    ``PartSpec.category`` comes from the planning call, which is shown a digest — filename, page
    count, bookmark outline, the draft split, the printed contents — and **no body text at all**.
    ``PartContext.category`` comes from the interpreter, which has read the part's pages and its
    images. On the first real bill of quantities the planner said ``other`` and the skip-list let a
    26-page pricing document through to be read as a contract, ten minutes and a dozen
    ceiling-hitting calls later.

    The interpreted answer was there the whole time — persisted to ``client_boq_part_contexts``,
    returned by ``store.load_parts`` as the third element of every tuple, and thrown away by both
    consumers. This function is the correction: prefer the reader over the guesser.

    An UNREADABLE part is the one case where the interpreter's answer is worth nothing — it did not
    read anything, so its category is its own default — and the planner's guess stands instead.
    """
    interpreted = (getattr(context, "category", "") or "").strip().lower()
    if context is not None and getattr(context, "readable", False) and interpreted:
        return interpreted, "interpreted"
    return (part.category or "").strip().lower(), "planned"


def ingest_from_parts(
    parts: list[tuple[PartSpec, str]], project_name: str = "",
    *, on_note: Optional[Callable[[str], None]] = None,
    contexts: Optional[dict] = None,
) -> ParsedDocumentSet:
    """Structure an already-split set, one part at a time.

    ``parts`` pairs each part with the path of its cut PDF. Reading the part's own file means
    the 200-page extraction cap applies per part instead of per binder, so nothing is dropped.

    ``contexts`` maps ``part_id`` to that part's interpreted :class:`PartContext`. Passed
    ALONGSIDE ``parts`` rather than folded into the tuple so the existing two-tuple signature keeps
    working; a caller that has no contexts gets exactly the old behaviour.

    A part is skipped when its category — the interpreted one where there is one, see
    :func:`effective_category` — is in :data:`NON_CONTRACTUAL_CATEGORIES`, and the skip is REPORTED
    with which category decided it. A silent skip and a silent read are equally opaque. When every
    part is skipped the set carries no contractual document at all, and that is said plainly rather
    than left to be inferred from a register full of findings about documents nobody uploaded.
    """
    from client_boq.ingest import pdfops  # local import: keeps the review path light

    client = make_client()  # app-wide model setting applied here (client_boq/llm.py)
    clauses: list[ClauseItem] = []
    doc_names: list[str] = []

    # One pass, two lists — partitioned by identity rather than by re-filtering, so two parts that
    # happen to compare equal cannot land in both.
    readable: list[tuple[PartSpec, str]] = []
    skipped: list[tuple[PartSpec, str, str]] = []   # (part, category, whose)
    for part, pdf_path in parts:
        category, whose = effective_category(part, (contexts or {}).get(part.part_id))
        if category in NON_CONTRACTUAL_CATEGORIES:
            skipped.append((part, category, whose))
        else:
            readable.append((part, pdf_path))
    if on_note and skipped:
        # Naming WHICH category decided it, because the two disagree and that disagreement is the
        # whole of this defect: a reader who sees a skip has to be able to tell whether a document
        # was skipped on evidence or on a guess.
        # `{part_id} ({category})` first and unchanged, then the authority — a superset of what
        # this note said before, so a reader (and a test) looking for the old shape still finds it.
        names = ", ".join(
            f"{p.part_id} ({cat}) on the "
            + ("interpreter's reading" if whose == "interpreted" else "planner's guess")
            for p, cat, whose in skipped[:8]
        )
        more = f" and {len(skipped) - 8} more" if len(skipped) > 8 else ""
        on_note(
            f"{len(skipped)} part(s) were NOT read for contractual positions — {names}{more}. A "
            "bill of quantities carries priced items, not clauses, and a drawing set carries "
            "geometry; reading them for contractual positions produces padding, not findings."
        )
    if on_note and parts and not readable:
        on_note(
            "This set contains NO contractual document — every part is pricing or drawings. The "
            "review has nothing to read, so it reports nothing. A finding that a letter of offer "
            "or a clarification is absent would be true and useless: neither was ever uploaded. "
            "Upload the conditions of contract, the specification or the tender conditions to "
            "review them."
        )

    for part, pdf_path in readable:
        source = part.source_doc or pdf_path
        if source not in doc_names:
            doc_names.append(source)
        path = Path(pdf_path)
        if not pdf_path or not path.is_file():
            continue
        data = path.read_bytes()
        text = pdfops.page_text(data, 1, part.page_count())
        if not text.strip():
            continue  # a scanned part contributes no clauses; ingest already flagged it
        for index, chunk in enumerate(_chunk(text), start=1):
            body = (
                f"=== {source} — part {part.n:02d} {part.title} "
                f"(source pages {part.start}-{part.end}) ===\n{chunk}"
            )
            for clause in _structure(client, body, f"{part.part_id}-{index}"):
                clause.part_id = part.part_id
                if not clause.source_doc:
                    clause.source_doc = source
                clauses.append(clause)

    return ParsedDocumentSet(name=project_name, documents=doc_names, clauses=clauses)


def ingest_review_documents(
    uploads: list[RawUpload], project_name: str = "", *, workspace: Optional[Workspace] = None,
) -> ParsedDocumentSet:
    """Extract and structure the document set into a :class:`ParsedDocumentSet`.

    Live: save each original to the Workspace, extract its text, then one AI structuring pass. DEMO:
    return the fixture parse offline. Set identity/persistence are the caller's job.
    """
    client = make_client()  # app-wide model setting applied here (client_boq/llm.py)
    if demo_mode():
        # Offline: the fixture is the structured parse. No file read, no network.
        return client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION, target_model=ParsedDocumentSet,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-review-ingest",
        )

    # Live: persist originals and extract text per document.
    doc_names: list[str] = []
    blocks: list[str] = []
    for filename, content_type, data in uploads:
        name = filename or "document"
        doc_names.append(name)
        if workspace is not None and project_name:
            workspace.save_upload(project_name, name, data)
        text, _page_images = extract_document(data, content_type, table_aware=True)
        blocks.append(f"=== {name} ===\n{text}")

    user = _INSTRUCTION + "\n\n".join(blocks) + f"\n\nDocument names: {doc_names}"
    parsed = client.complete_json(
        system=_SYSTEM, user=user, target_model=ParsedDocumentSet,
        purpose="client_boq-review-ingest",
    )
    if not parsed.documents:
        parsed = parsed.model_copy(update={"documents": doc_names})
    return parsed
