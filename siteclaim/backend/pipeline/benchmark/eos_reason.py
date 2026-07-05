"""EOS → variance reason candidates (Phase P2b — Layer 2, suggestion only).

Given a project's EOS field narrative plus the variance records that actually moved,
propose one reason code (from the fixed ten-code vocabulary) per line and quote the
supporting sentence from the narrative as evidence. One batched ``complete_json`` call
(purpose ``reason-from-eos``). It PROPOSES; the human confirm gate
(``POST /benchmark/{id}/variance/{record_id}/reason``) stays the sole writer of the code.

The narrative is where the *why* lives that the deterministic shape cannot know: a rate
that moved because the rig stood idle reads as ``rate_reprice`` from the numbers alone, but
the EOS says ``standing_time``. So the model reads the report; a deterministic FALLBACK
(the shape-based ``matcher.suggest_reason`` hint plus a keyword snippet search) guarantees a
candidate still surfaces with no key / no network / a line the model didn't cover. DEMO
reads a baked fixture — fully offline.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import ValidationError

from db.benchmark import REASON_CODES, REASON_CODE_SET
from pipeline.benchmark.matcher import suggest_reason
from pipeline.llm_client import LLMClient, demo_mode
from schemas.benchmark import ReasonCandidateSet

EOS_REASON_FIXTURE = "cases/benchmark/eos_reason_candidates.json"

_CODE_LINES = "\n".join(f"  - {c['code']}: {c['description']}" for c in REASON_CODES)
_SYSTEM = (
    "You read a Hong Kong construction project's End-of-Site (EOS) field report — the "
    "narrative account of what happened on site — and explain WHY each priced line moved "
    "between the tendered price and the final-account outturn. For each variance line you "
    "are given, attribute exactly ONE reason code from this fixed vocabulary and quote the "
    "single supporting sentence from the report verbatim as the snippet:\n"
    f"{_CODE_LINES}\n"
    "Attribute a line only when the report supports it — skip a line the narrative does not "
    "explain. You PROPOSE only; a human confirms the code. Return JSON: "
    '{"candidates": [{"item_ref": <string>, "granularity": "item"|"section"|"project", '
    '"reason_code": <one of the codes above>, "snippet": <the supporting sentence>}]}.'
)

# Keywords per code — used by the deterministic fallback to find a supporting sentence (and,
# for a shapeless line, as a last-resort code guess). Ordered by specificity.
_CODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ground_conditions": ("ground condition", "rock", "obstruction", "strata", "boulder", "hard material"),
    "standing_time": ("standing", "stood idle", "stood waiting", "stood", "idle", "waiting", "breakdown"),
    "weather": ("weather", "rain", "typhoon", "storm", "amber", "black rain"),
    "access_restriction": ("access", "restricted", "blocked", "no entry", "possession"),
    "quantity_remeasure": ("remeasure", "remeasured", "additional", "extra", "beyond the tendered quantity"),
    "rate_reprice": ("reprice", "repriced", "renegotiat", "rate was corrected", "star rate"),
    "scope_variation": ("variation", "instructed", "additional scope", "vo ", "architect's instruction"),
    "omission_at_tender": ("not priced", "omission", "omitted", "missing from the tender", "unpriced", "not in the tender"),
    "additional_testing": ("testing", "test", "laboratory", "in-situ", "sample tested"),
    "provisional_sum_adjustment": ("provisional sum", "prime cost", "pc sum", "reconciled"),
}


def _sentences(narrative: str) -> list[str]:
    """Split a narrative into sentences (on . ! ? or newlines), trimmed and non-empty."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", narrative or "") if s.strip()]


def _snippet_for(narrative: str, record: dict, code: str) -> str:
    """Find a supporting sentence for ``record``/``code`` in the narrative: prefer one that
    names the item_ref, else one carrying a keyword for the code. Empty when nothing fits."""
    sents = _sentences(narrative)
    ref = (record.get("item_ref") or "").strip().lower()
    if ref:
        for s in sents:
            if ref in s.lower():
                return s
    for kw in _CODE_KEYWORDS.get(code, ()):
        for s in sents:
            if kw in s.lower():
                return s
    return ""


def _movement(r: dict) -> str:
    """A compact description of what moved on a variance line, for the prompt."""
    if r.get("tender_item_id") and not r.get("actual_item_id"):
        return "priced in the tender but with no actual line (a possible omission / not-required item)"
    if r.get("actual_item_id") and not r.get("tender_item_id"):
        return "arrived on site with no tender line (unpriced / instructed)"
    parts: list[str] = []
    rd = r.get("rate_delta")
    if rd:
        parts.append(f"rate {'up' if rd > 0 else 'down'} by {abs(rd):g}")
    dq = r.get("amount_delta_qty")
    if dq:
        parts.append(f"quantity-driven amount {'up' if dq > 0 else 'down'} by {abs(dq):g}")
    return "; ".join(parts) or "moved between tender and outturn"


def _prompt(narrative: str, records: list[dict]) -> str:
    lines = [
        f"- item_ref={r.get('item_ref') or '(none)'} granularity={r.get('granularity', 'item')} "
        f"| {_movement(r)}"
        for r in records
    ]
    return (
        "EOS field report:\n" + (narrative or "").strip() + "\n\n"
        "Variance lines that moved between tender and outturn:\n" + "\n".join(lines) +
        "\n\nAttribute a reason code and quote the supporting sentence for each line the "
        "report explains."
    )


def fallback_candidate(narrative: str, record: dict) -> Optional[dict]:
    """A deterministic reason candidate from a variance record's shape (``suggest_reason``)
    plus a keyword snippet from the narrative. ``None`` when the shape implies no code (e.g.
    a zero-variance line needs no reason)."""
    code = suggest_reason(record)
    if code not in REASON_CODE_SET:
        return None
    return {
        "item_ref": record.get("item_ref") or "",
        "granularity": record.get("granularity", "item"),
        "reason_code": code,
        "snippet": _snippet_for(narrative, record, code),
        "source": "fallback",
        "record_id": record.get("id"),
    }


def extract_reason_candidates(
    narrative: str, variance_records: list[dict], *,
    demo_fixture: Optional[str] = None, client: Optional[LLMClient] = None,
) -> list[dict]:
    """Return a reason candidate per variance line the report explains — each
    ``{item_ref, granularity, reason_code, snippet, source, record_id}``. ``source`` is
    ``reason-from-eos`` when the model attributed it, else ``fallback``. Proposes only; the
    human confirm gate remains the sole writer of the code."""
    client = client or LLMClient()
    index: dict[tuple, tuple[str, str]] = {}
    if narrative and (demo_fixture or not demo_mode()):
        try:
            drafted = client.complete_json(
                system=_SYSTEM, user=_prompt(narrative, variance_records),
                target_model=ReasonCandidateSet, demo_fixture=demo_fixture, purpose="reason-from-eos",
            )
            index = {
                (c.item_ref, c.granularity or "item"): (c.reason_code, c.snippet)
                for c in drafted.candidates if c.reason_code in REASON_CODE_SET
            }
        except (RuntimeError, FileNotFoundError, ValidationError, ValueError):
            index = {}

    out: list[dict] = []
    for r in variance_records:
        key = (r.get("item_ref") or "", r.get("granularity", "item"))
        hit = index.get(key)
        if hit:
            out.append({
                "item_ref": r.get("item_ref") or "", "granularity": r.get("granularity", "item"),
                "reason_code": hit[0], "snippet": (hit[1] or _snippet_for(narrative, r, hit[0])),
                "source": "reason-from-eos", "record_id": r.get("id"),
            })
        else:
            fb = fallback_candidate(narrative, r)
            if fb:
                out.append(fb)
    return out
