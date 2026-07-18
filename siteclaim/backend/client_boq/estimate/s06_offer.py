"""ESTIMATE stage 06 — letter of offer.

Bucket (mapping doc estimate task 14): **AI draft**. Drafts the offer letter — qualifies scope,
states inclusions/exclusions, references documents relied upon (``llm_client.complete_json`` against
:class:`LetterOfOffer`). The PRICE is injected from the deterministic cost build-up (s03/s04) and is
NEVER written by the model — the draft is prose around a number the engine computed.
"""

from __future__ import annotations

from client_boq.models import Estimate, LetterOfOffer, ScopeReviewResult

DEMO_FIXTURE = "cases/client_boq/estimate_offer.json"


def draft_offer(scope_review: ScopeReviewResult, estimate: Estimate) -> LetterOfOffer:
    """Draft the letter of offer with the engine-computed price injected (never AI-written).
    Slice-2 stub — the deterministic ``estimate`` (incl. its price) already exists; this stage only
    drafts the prose around it."""
    raise NotImplementedError("client_boq ESTIMATE s06 (offer) — estimate slice 2")
