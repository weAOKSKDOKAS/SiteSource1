"""REVIEW stage 05 — program & constructability check.

Bucket (mapping doc task 7): **AI propose → deterministic recompute**.
The AI flags candidate program risks — unrealistic durations, sequencing, mobilisation count,
milestones on the critical path (``llm_client.complete_json``); the critical-path and
liquidated-damages exposure are recomputed deterministically (math, not model). The verdict is
human-gated.
"""

from __future__ import annotations

from client_boq.models import ContextSummary, ParsedDocumentSet, ProgramFinding

DEMO_FIXTURE = "cases/client_boq/review_program_check.json"


def check_program(parsed: ParsedDocumentSet, summary: ContextSummary) -> list[ProgramFinding]:
    """Propose program risks; recompute durations / LD exposure deterministically. Not implemented yet."""
    raise NotImplementedError("client_boq REVIEW s05 (program check) — scaffold only")
