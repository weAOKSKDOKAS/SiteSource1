"""REVIEW stage 01 — ingest the client's document set.

Bucket (per client_boq_layer_mapping.md, tasks 1a/1b/1c): **Deterministic + AI**.
Deterministic text/page extraction reuses ``pipeline.documents.extract_document`` (pymupdf +
Tesseract via ``pipeline.ocr``); the AI half structures the extracted text into clauses/scope lines
via ``llm_client.complete_json`` against :class:`ParsedDocumentSet`. Reading, not deciding — no
decision value is produced here.

The result is persisted as the shared parsed-document store both workflows read (via the Workspace
artifacts subtree, keyed by the document-set slug).
"""

from __future__ import annotations

from client_boq.models import ParsedDocumentSet, RawUpload

# DEMO fixture (offline path) — resolved relative to backend/fixtures/ by llm_client.
DEMO_FIXTURE = "cases/client_boq/review_ingest.json"


def ingest_review_documents(
    uploads: list[RawUpload], project_name: str = "",
) -> ParsedDocumentSet:
    """Extract and structure the client's document set into a :class:`ParsedDocumentSet`.

    Deterministic extraction then one AI structuring pass (strict schema). Not implemented yet.
    """
    raise NotImplementedError("client_boq REVIEW s01 (ingest) — scaffold only")
