"""REVIEW stage 02 — condense the document set into a commercial-risk summary.

Bucket (mapping doc task 2): **AI draft** (human-reviewed). One ``llm_client.complete_json`` pass
against :class:`ContextSummary`. A draft only — it grounds the later checks, it decides nothing.
"""

from __future__ import annotations

from client_boq.models import ContextSummary, ParsedDocumentSet

DEMO_FIXTURE = "cases/client_boq/review_context_summary.json"


def summarise_context(parsed: ParsedDocumentSet) -> ContextSummary:
    """Draft a compact commercial-risk summary from the parsed document set. Not implemented yet."""
    raise NotImplementedError("client_boq REVIEW s02 (context summary) — scaffold only")
