"""ESTIMATE stage 02 — pricing-schedule setup.

Bucket (mapping doc estimate tasks 3/4): **AI propose → deterministic structure**. The AI drafts a
breakdown of the scope into activities; the pricing schedule itself is a deterministic data
structure, and direct-vs-indirect classification is rule-based (known categories, fuzzy ones
AI-suggested). Structure is human-confirmed downstream.
"""

from __future__ import annotations

from client_boq.models import PricingSchedule, ScopeReviewResult

DEMO_FIXTURE = "cases/client_boq/estimate_schedule.json"


def build_schedule(scope_review: ScopeReviewResult) -> PricingSchedule:
    """Propose the activity breakdown and classify direct/indirect. Not implemented yet."""
    raise NotImplementedError("client_boq ESTIMATE s02 (schedule) — scaffold only")
