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
from typing import Optional

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


def ingest_from_parts(
    parts: list[tuple[PartSpec, str]], project_name: str = "",
) -> ParsedDocumentSet:
    """Structure an already-split set, one part at a time.

    ``parts`` pairs each part with the path of its cut PDF. Reading the part's own file means
    the 200-page extraction cap applies per part instead of per binder, so nothing is dropped.
    """
    from client_boq.ingest import pdfops  # local import: keeps the review path light

    client = make_client()  # app-wide model setting applied here (client_boq/llm.py)
    clauses: list[ClauseItem] = []
    doc_names: list[str] = []

    for part, pdf_path in parts:
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
