"""The cross-reference — the join that makes the recommendation defensible.

Given a trade and a scope query, fuse three things into ranked :class:`Candidate`
objects:

1. **Who does the trade** — :func:`db.store.firms_for_trade`.
2. **How well their closeout history matches the scope** — a *feature*, from
   :func:`db.store.semantic_closeout_matches` (cosine over baked vectors, offline).
3. **What risk they carry** — adjudicated by :func:`rules_engine.risk_scoring.score_firm`.

The semantic score is a soft feature; the risk demotion is hard and deterministic
(:func:`rules_engine.ranking.rank_candidates`). This is pure Layer 1 over the
database — no LLM is asked to rank, so the same input always yields the same
shortlist. It is what a generic chatbot cannot do: it has no access to this data.
"""

from __future__ import annotations

import sqlite3

from schemas.models import Candidate, Evidence, FirmProfile, Severity, SignalType
from db import store
from rules_engine.ranking import rank_candidates
from rules_engine.risk_scoring import score_firm


def _warning_count(flags: list) -> int:
    """How many WARNING-severity flags a firm carries (used to order the public pool)."""
    return sum(1 for f in flags if f.severity is Severity.WARNING)


def _grounding_evidence(firm: FirmProfile) -> list[Evidence]:
    """Citable evidence for *why this firm is a candidate* (distinct from risk)."""
    evidence: list[Evidence] = []
    if firm.closeout_summary:
        evidence.append(Evidence(
            source="Project closeout (EOS)",
            signal_type=SignalType.CLOSEOUT_PERFORMANCE,
            snippet=firm.closeout_summary,
            reference=f"EOS:{firm.firm_id}",
        ))
    if firm.award_history:
        evidence.append(Evidence(
            source="Public award history",
            signal_type=SignalType.AWARD_HISTORY,
            snippet="; ".join(firm.award_history[:3]),
            reference=f"AWARDS:{firm.firm_id}",
        ))
    return evidence


def cross_reference(
    conn: sqlite3.Connection,
    trade: str,
    scope_query: str,
    k: int | None = None,
    *,
    include_public: bool = False,
) -> list[Candidate]:
    """Return ranked candidates for ``trade`` against ``scope_query``.

    Two shortlist populations, one code path:

    * ``include_public=False`` (default) — only firms with an **assessable EOS
      closeout record** are shortlisted. The wider public-record pool is the
      discovery/coverage layer, screened and counted but not auto-shortlisted. This
      is the assessed-firm behaviour the baked demo scenarios rely on, so it stays
      the default.
    * ``include_public=True`` — the shortlist is opened to the **full screened pool**
      for the trade (:func:`db.store.firms_for_trade`). Every registered firm is a
      candidate, ordered by the public risk screen: fatal-flagged firms demoted last
      by ranking, and among clean firms the spotless ones ahead of those carrying a
      warning. The closeout semantic match stays a soft enrichment feature and is 0
      for a firm with no closeout history. This is the live-engine path — real firms
      carry no closeout record until a partner-contractor archive lands, so the
      screen and registration are what order them for now.

    In both modes no firm is silently dropped: ``match_score`` is the semantic
    relevance of any closeout history to the scope, ``risk_flags`` are the
    deterministic adjudication of the firm's signals, and the list is ordered
    clean-first by ranking. ``k`` optionally caps the result.
    """
    firms = (
        store.firms_for_trade(conn, trade)
        if include_public
        else store.shortlistable_firms_for_trade(conn, trade)
    )
    scores = dict(store.semantic_closeout_matches(conn, scope_query, trade, k=len(firms) or 1))

    candidates = [
        Candidate(
            firm=firm,
            trade=trade,
            match_score=scores.get(firm.firm_id, 0.0),
            evidence=_grounding_evidence(firm),
            risk_flags=score_firm(firm),
        )
        for firm in firms
    ]

    # In the public pool most firms share match_score 0 (no closeout yet), so order the
    # input by screen quality first — spotless clean firms ahead of clean-but-warned —
    # then by name for stability. rank_candidates then applies the hard clean-first /
    # fatal-last rule as a stable sort, so this ordering survives among match ties and
    # is harmlessly superseded by a real closeout match when one exists.
    candidates.sort(key=lambda c: (_warning_count(c.risk_flags), -c.match_score, c.firm.name))

    ranked = rank_candidates(candidates)
    return ranked[:k] if k is not None else ranked
