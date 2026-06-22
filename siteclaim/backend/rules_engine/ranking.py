"""Deterministic candidate ranking (Layer 1).

The single rule the demo turns on: **a firm with a fatal risk flag is demoted
below every clean firm regardless of price or match quality.** The LLM is never
asked to rank. Two entry points share one principle:

* :func:`rank_candidates` — shortlist ordering (Stage 02), by semantic
  ``match_score``; clean firms first, fatal-flagged firms after.
* :func:`rank_by_total` — price ordering (Stage 05), by ``corrected_total``;
  clean firms first (cheapest wins), fatal-flagged firms after and marked
  ``recommended_against`` with the citing rule. This is what catches the cheapest
  bidder that carries a winding-up petition.
"""

from __future__ import annotations

from schemas.models import Candidate, RankedFirm, Severity
from rules_engine.risk_scoring import has_fatal


def _fatal_reason(firm: RankedFirm) -> str:
    fatal = [f for f in firm.risk_flags if f.severity is Severity.FATAL]
    if not fatal:
        return firm.reason
    labels = "; ".join(f"{f.label} ({f.rule_ref})" for f in fatal)
    return f"Recommended against despite price: {labels}."


def rank_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Order candidates clean-first by descending ``match_score``; fatal-flagged last.

    Marks every fatal-flagged candidate ``recommended_against`` (so the shortlist
    screen can show the gotcha as recommend-against). Stable; returns a new list.
    """
    marked = [
        c.model_copy(update={"recommended_against": has_fatal(c.risk_flags)})
        for c in candidates
    ]
    return sorted(marked, key=lambda c: (c.recommended_against, -c.match_score))


def rank_by_total(firms: list[RankedFirm]) -> list[RankedFirm]:
    """Order firms clean-first by ascending **leveled** total; fatal-flagged last.

    Ranking is by ``normalized_total`` — the like-for-like basis that adds each bid's
    scope gaps back at the peer price — so a bid that left scope out can no longer win
    on the strength of the omission. When ``normalized_total`` is unset (0.0) the
    ranking falls back to ``corrected_total``, preserving the original behaviour for
    callers that don't carry the leveled figure. Marks every fatal-flagged firm
    ``recommended_against`` with a citing reason, so the cheapest-but-flagged firm
    sinks below a pricier clean firm.
    """
    marked = [
        firm.model_copy(
            update={
                "recommended_against": has_fatal(firm.risk_flags),
                "reason": _fatal_reason(firm) if has_fatal(firm.risk_flags) else firm.reason,
            }
        )
        for firm in firms
    ]
    return sorted(marked, key=lambda f: (f.recommended_against, f.normalized_total or f.corrected_total))
