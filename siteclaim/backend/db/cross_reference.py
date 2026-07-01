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

import re
import sqlite3

from schemas.models import Candidate, Evidence, FirmProfile, SignalType
from db import register_loader, store
from rules_engine.ranking import rank_candidates
from rules_engine.risk_scoring import score_firm

# Each work section surfaces a readable shortlist, not the whole register pool: keep
# the top clean matches (~12–15) and always append the fatal-flagged firms so the
# recommend-against gotcha stays visible at the bottom rather than being capped away.
SECTION_CAP = 14


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



_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _reg_recency(reg_date: str) -> float:
    """A 0–1 registration-recency feature from the CIC ``reg_date`` (e.g. "7 Oct
    2021"), at month precision so even a large recent cohort spreads rather than ties
    on the year alone. Newer registrations score a little higher; this is what keeps
    the register-only pool's match scores varying across a section. An unparseable or
    empty date is treated as mid-range so it neither tops nor sinks the list."""
    m = re.search(r"(19|20)\d{2}", reg_date or "")
    if not m:
        return 0.5
    year = int(m.group(0))
    month = next((_MONTHS[w] for w in re.findall(r"[A-Za-z]+", reg_date.lower()) if w in _MONTHS), 6)
    frac = year + (month - 0.5) / 12.0
    return max(0.0, min(1.0, (frac - 2008.0) / 19.0))  # ~2008 -> 0.0, ~2027 -> 1.0


def _match_score(firm: FirmProfile, trade: str, semantic: float) -> float:
    """How directly this firm matches the section, in [0, 1].

    Two bands keep the ranking honest and the curated/assessed firms near the top:

    * **Assessed / award-bearing firms** sit in the upper band [0.66, 0.97], lifted by
      the semantic relevance of their held closeout text and by public awards.
    * **Register-only firms** sit below, spread by how *directly* their registered
      specialty matches the section — an exact specialty (e.g. a materials-testing lab
      in field testing) outscores an incidental one (a GI contractor surfaced in field
      testing via the discovery expansion) — and by registration recency.
    """
    direct = register_loader.direct_trades(firm.registered_trades) or set(firm.trades)
    exact = trade in direct
    semantic = max(0.0, min(semantic, 1.0))

    if firm.closeout_summary or firm.award_history or semantic > 0.0:
        base = 0.80 if exact else 0.66
        base += 0.12 * semantic                              # held-closeout relevance
        base += min(0.04 * len(firm.award_history), 0.10)    # public award record
        return round(min(base, 0.97), 4)

    focus = 1.0 / max(len(direct), 1)                        # specialty precision
    recency = _reg_recency(firm.reg_date)
    if exact:
        return round(0.48 + 0.08 * focus + 0.08 * recency, 4)   # ~0.48–0.64
    return round(0.30 + 0.06 * focus + 0.10 * recency, 4)        # ~0.31–0.46


def cross_reference(
    conn: sqlite3.Connection, trade: str, scope_query: str, k: int | None = None
) -> list[Candidate]:
    """Return ranked candidates for ``trade`` against ``scope_query``.

    Firms that genuinely do the trade are shortlisted — those we can assess by a held
    closeout report or a public award, **plus the trade-matched real-register pool**
    (see :func:`db.store.shortlistable_firms_for_trade`). ``match_score`` reflects how
    directly each firm's registered specialty matches the section (with a bonus for
    assessable evidence, so curated/assessed firms surface near the top), ``risk_flags``
    are the deterministic adjudication of its signals, and the list is ordered
    clean-first by ranking with every fatal-flagged firm demoted below all clean firms.

    The result is capped to a readable section shortlist (``SECTION_CAP`` clean firms
    plus any fatal-flagged firms, so the recommend-against gotcha stays visible at the
    bottom). An explicit ``k`` overrides the cap.
    """
    firms = store.shortlistable_firms_for_trade(conn, trade)
    scores = dict(store.semantic_closeout_matches(conn, scope_query, trade, k=len(firms) or 1))

    candidates = [
        Candidate(
            firm=firm,
            trade=trade,
            match_score=_match_score(firm, trade, scores.get(firm.firm_id, 0.0)),
            evidence=_grounding_evidence(firm),
            risk_flags=score_firm(firm),
        )
        for firm in firms
    ]

    ranked = rank_candidates(candidates)
    if k is not None:
        return ranked[:k]
    clean = [c for c in ranked if not c.recommended_against]
    flagged = [c for c in ranked if c.recommended_against]
    return clean[:SECTION_CAP] + flagged
