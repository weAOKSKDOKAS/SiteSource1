"""REVIEW stage 02 — condense the document set into a commercial-risk summary.

Bucket (mapping doc task 2): **AI draft** (human-reviewed). One ``complete_json`` pass produces the
structured summary the review doc specifies — scope responsibilities that affect price; testing /
inspection / certification / permit obligations; client assumptions and constraints; interfaces with
other trades; and items to clarify or exclude. A draft only: it grounds the later checks and decides
nothing. DEMO returns the fixture offline.
"""

from __future__ import annotations

from client_boq.models import ContextSummary, ParsedDocumentSet
from pipeline.llm_client import LLMClient, demo_mode

DEMO_FIXTURE = "cases/client_boq/review_context_summary.json"

_SYSTEM = (
    "You are an expert construction contract manager. You summarise a document set into a compact "
    "commercial-risk summary focused only on price and terms. You draft; you do not decide. "
    "Return ONLY JSON matching the schema."
)

_INSTRUCTION = (
    "From the clauses below, produce a structured commercial-risk summary. Populate:\n"
    "- summary: 2-4 sentences on what is being built and what drives commercial risk\n"
    "- scope_responsibilities: scope items that materially affect price\n"
    "- obligations: testing, inspection, certification or permit obligations\n"
    "- client_assumptions: client assumptions or constraints that shift risk to the contractor\n"
    "- interfaces: interfaces/dependencies with other trades\n"
    "- clarifications: items that could reasonably require clarification or exclusion\n"
    "Ignore generic descriptions. Focus only on what affects price, programme, or contractual "
    "exposure.\n\n=== CLAUSES ===\n"
)


def summarise_context(parsed: ParsedDocumentSet) -> ContextSummary:
    """Draft the structured commercial-risk summary from the parsed document set. Draft only."""
    client = LLMClient()
    if demo_mode():
        return client.complete_json(
            system=_SYSTEM, user=_INSTRUCTION, target_model=ContextSummary,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-review-summary",
        )
    lines = [f"[{c.source_doc} · {c.clause_id}] {c.heading}: {c.text}" for c in parsed.clauses]
    user = _INSTRUCTION + "\n".join(lines)
    return client.complete_json(
        system=_SYSTEM, user=user, target_model=ContextSummary,
        purpose="client_boq-review-summary",
    )
