"""REVIEW stage 01 — ingest the client's document set.

Bucket (client_boq_layer_mapping.md tasks 1a/1c): **Deterministic + AI**. Deterministic text/page
extraction reuses ``pipeline.documents.extract_document`` (pymupdf + Tesseract); the AI half
structures the extracted text into typed clauses with **stable clause ids** and page/locus
references — the identities s08 later verifies citations against. Reading, not deciding.

DEMO stays fully offline: ``complete_json`` short-circuits to the fixture ``ParsedDocumentSet`` and
no extraction/network runs (the fixture already *is* a structured parse). The caller (``run.py``)
assigns the set identity and persists the result; this stage only produces the parse.
"""

from __future__ import annotations

from typing import Optional

from client_boq.models import ParsedDocumentSet, RawUpload
from pipeline.documents import extract_document
from pipeline.llm_client import LLMClient, demo_mode
from pipeline.workspace import Workspace

DEMO_FIXTURE = "cases/client_boq/review_ingest.json"

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


def ingest_review_documents(
    uploads: list[RawUpload], project_name: str = "", *, workspace: Optional[Workspace] = None,
) -> ParsedDocumentSet:
    """Extract and structure the document set into a :class:`ParsedDocumentSet`.

    Live: save each original to the Workspace, extract its text, then one AI structuring pass. DEMO:
    return the fixture parse offline. Set identity/persistence are the caller's job.
    """
    client = LLMClient()
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
