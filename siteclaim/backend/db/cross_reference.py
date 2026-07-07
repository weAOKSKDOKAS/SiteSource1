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
from db.register_loader import direct_trades
from rules_engine.ranking import rank_candidates
from rules_engine.risk_scoring import score_firm
from rules_engine.taxonomy import parent_trade

# A specialty pool thinner than this widens to the parent trade so there are enough bidders to
# compete (a lone specialist plus the parent pool, specialist ranked first) — not a pool of one.
MIN_POOL = 5


def _warning_count(flags: list) -> int:
    """How many WARNING-severity flags a firm carries (used to order the public pool)."""
    return sum(1 for f in flags if f.severity is Severity.WARNING)


def _direct_specialties(firm: FirmProfile) -> set[str]:
    """The trades a firm's registered specialties map to DIRECTLY (before the GI discovery
    expansion) — an exact specialty match, from :func:`db.register_loader.direct_trades`. A firm
    with no ``registered_trades`` (the illustrative demo firms) yields the empty set and is treated
    as non-direct — never a crash."""
    rts = [{"code": rt.code, "group": rt.group, "specialty": rt.specialty} for rt in (firm.registered_trades or [])]
    return direct_trades(rts)


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
    specialty: str | None = None,
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
    pool_for = store.firms_for_trade if include_public else store.shortlistable_firms_for_trade

    # ``specialty`` (a GI sub-trade like ``field_testing``) shortlists the section against its own
    # specialist pool instead of the coarse parent. A too-thin specialty pool widens to the parent
    # (``parent_trade``) so there are enough bidders — the specialist(s) are KEPT and parent-only
    # firms appended (union), then ranked below them by the specialist-first term. Without a
    # specialty this is exactly the prior behaviour (pool = ``trade``).
    section_trade = specialty or trade
    firms = pool_for(conn, section_trade)
    if specialty:
        parent = parent_trade(section_trade)
        if parent != section_trade and len(firms) < MIN_POOL:
            seen = {f.firm_id for f in firms}
            firms = firms + [f for f in pool_for(conn, parent) if f.firm_id not in seen]

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
    if specialty:
        # Specialist-first: a firm whose registered specialties DIRECTLY include this section's
        # specialty ranks above one surfaced only through the parent fallback. Folded in AFTER the
        # warning demotion, so the hard clean-first rule (rank_candidates) still wins.
        is_direct = {c.firm.firm_id: section_trade in _direct_specialties(c.firm) for c in candidates}
        candidates.sort(key=lambda c: (_warning_count(c.risk_flags), not is_direct[c.firm.firm_id], -c.match_score, c.firm.name))
    else:
        candidates.sort(key=lambda c: (_warning_count(c.risk_flags), -c.match_score, c.firm.name))

    ranked = rank_candidates(candidates)
    return ranked[:k] if k is not None else ranked
