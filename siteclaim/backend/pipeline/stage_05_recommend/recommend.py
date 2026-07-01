"""Stage 05 — recommend: LevelledBids + the database -> Recommendation.

Layer 1 ranks firms by ``corrected_total`` but reads each against the database: the
risk flags adjudicated from the firm's profile, the bid distribution across the
levelled bids, and the historical pricing band for the trade. **A firm with a fatal
flag is ``recommended_against`` regardless of price**; ``recommended_firm_id`` is the
cheapest clean firm. The deterministic ranking is produced by
:func:`rules_engine.ranking.rank_by_total` — the LLM does not choose the winner.

Layer 2 only **narrates**: it writes the rationale prose given the deterministic
ranking and evidence (DEMO_MODE reads a baked rationale; an offline template is the
fallback). Layer 4 (the human award/override) is recorded by the API/UI.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from pydantic import BaseModel

from db import store
from pipeline.llm_client import LLMClient, demo_mode
from rules_engine.ranking import rank_by_total
from rules_engine.risk_scoring import score_firm
from schemas.models import (
    BidDistributionPoint,
    HistoricalBand,
    LevelledBid,
    RankedFirm,
    Recommendation,
)

# The tender's own Schedule of Rates is carried in the levelled set as a baseline
# "bid" under this id. It is a benchmark, never a competing tenderer, so it is
# excluded from the ranking, the recommendation, and the bid distribution.
_BENCHMARK_ID = "tender-scheduled-rates"


class _Rationale(BaseModel):
    """The single string Layer 2 is allowed to produce — it never sets the ranking."""

    text: str


_NARRATE_SYSTEM = (
    "You are a buying-team analyst. Given a DETERMINISTIC ranking and the cited "
    "evidence, write a short, professional rationale for the recommendation. You do "
    "NOT choose the winner or invent any number — the ranking and flags are fixed. "
    "Name the recommended firm, explain why any firm is recommended against citing "
    "its risk flags, and note where the recommended price sits in the historical "
    "band. Return JSON matching {\"text\": <prose>}."
)


def recommend(
    levelled: list[LevelledBid],
    trade: str,
    demo_fixture: Optional[str] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
    client: Optional[LLMClient] = None,
) -> Recommendation:
    """Produce the risk-adjusted recommendation for ``trade``."""
    bids = [b for b in levelled if b.trade == trade and b.firm_id != _BENCHMARK_ID]
    own_conn = conn is None
    conn = conn or store.get_connection()
    try:
        ranked_input = [
            RankedFirm(
                firm_id=b.firm_id,
                firm_name=b.firm_name,
                corrected_total=b.corrected_total,
                normalized_total=b.normalized_total,
                risk_flags=score_firm(profile) if (profile := store.firm_profile(conn, b.firm_id)) else [],
            )
            for b in bids
        ]
        ranked = rank_by_total(ranked_input)  # marks recommended_against + reason, sorts
        recommended_id = next((r.firm_id for r in ranked if not r.recommended_against), None)
        band_values = store.historical_pricing(conn, trade)
    finally:
        if own_conn:
            conn.close()

    historical_band = (
        HistoricalBand(low=band_values[0], median=band_values[1], high=band_values[2])
        if band_values is not None
        else None
    )
    bid_distribution = [
        BidDistributionPoint(firm_name=b.firm_name, corrected_total=b.corrected_total) for b in bids
    ]
    rationale = _narrate(ranked, recommended_id, trade, historical_band, demo_fixture, client or LLMClient())

    return Recommendation(
        trade=trade,
        recommended_firm_id=recommended_id,
        ranked=ranked,
        rationale=rationale,
        bid_distribution=bid_distribution,
        historical_band=historical_band,
    )


def _narrate(ranked, recommended_id, trade, band, demo_fixture, client) -> str:
    if demo_fixture or not demo_mode():
        try:
            drafted = client.complete_json(
                system=_NARRATE_SYSTEM,
                user=_narrate_prompt(ranked, recommended_id, trade, band),
                target_model=_Rationale,
                demo_fixture=demo_fixture,
            )
            return drafted.text
        except (RuntimeError, FileNotFoundError):
            pass
    return _template_rationale(ranked, recommended_id, trade, band)


def _narrate_prompt(ranked, recommended_id, trade, band) -> str:
    lines = [
        f"- {r.firm_name} ({r.firm_id}): HK${r.corrected_total:,.0f}"
        + (f" — RECOMMENDED AGAINST: {r.reason}" if r.recommended_against else "")
        for r in ranked
    ]
    band_str = f"low HK${band.low:,.0f} / median HK${band.median:,.0f} / high HK${band.high:,.0f}" if band else "n/a"
    return (
        f"Trade: {trade}\nRecommended firm_id: {recommended_id}\n"
        f"Historical band: {band_str}\nRanking:\n" + "\n".join(lines)
    )


def _template_rationale(ranked, recommended_id, trade, band) -> str:
    """Deterministic, always-accurate fallback narration."""
    label = trade.replace("_", " ")
    rec = next((r for r in ranked if r.firm_id == recommended_id), None)
    parts: list[str] = []
    if rec is not None:
        parts.append(
            f"For the {label} package we recommend {rec.firm_name} ({rec.firm_id}) at "
            f"HK${rec.corrected_total:,.0f} — the lowest-priced firm carrying no fatal risk flag."
        )
        if band is not None:
            where = "within" if band.low <= rec.corrected_total <= band.high else "outside"
            near = "near the median" if abs(rec.corrected_total - band.median) <= (band.high - band.low) * 0.25 else ""
            parts.append(
                f"The chosen price sits {where} the historical band "
                f"(HK${band.low:,.0f}–HK${band.high:,.0f}; median HK${band.median:,.0f}){', ' + near if near else ''}."
            )
    for r in ranked:
        if r.recommended_against:
            parts.append(f"We recommend against {r.firm_name} ({r.firm_id}) despite its price of HK${r.corrected_total:,.0f}: {r.reason}")
    return " ".join(parts)
