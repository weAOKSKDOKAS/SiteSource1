"""Build the leveling :class:`BidReply` set from the firms approved in dispatch.

The Level step is **approval-driven**: the columns shown (and exported) are always
the firms the human approved at the dispatch gate, never a fixed fixture list. A
section's priced Schedules of Rates come from a small template bank
(``cases/scenarios/drainage_sor.json``):

* the tender's own scheduled rates ride as the fixed **benchmark** (always the first
  column, ``firm_id`` ``tender-scheduled-rates``);
* a firm with a **pinned real offer** (Sixense's geophysical survey, Kai Wai's field
  installations) prices over that real offer;
* every other approved firm prices over the **next representative template** for that
  section, assigned in approval order.

Each section is capped at the benchmark plus two firms. Firm display names are
resolved from the database downstream (Stage 04), so the columns carry the approved
firm's real DB-profile name.
"""

from __future__ import annotations

import json
from pathlib import Path

from schemas.models import BidLineItem, BidReply

_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

BENCHMARK_ID = "tender-scheduled-rates"
SECTION_CAP = 2  # benchmark + at most two approved firms per section


def load_sor_templates(fixture: str) -> dict:
    """Load the per-section SoR template bank from ``backend/fixtures/<fixture>``."""
    return json.loads((_FIXTURES_DIR / fixture).read_text(encoding="utf-8"))


def _reply(firm_id: str, trade: str, sor: dict) -> BidReply:
    return BidReply(
        firm_id=firm_id,
        trade=trade,
        line_items=[BidLineItem.model_validate(li) for li in sor.get("line_items", [])],
        exclusions=list(sor.get("exclusions", [])),
        claimed_total=sor.get("claimed_total"),
    )


def build_replies_from_approvals(
    approvals: dict[str, list[str]], sor: dict, *, cap: int = SECTION_CAP
) -> list[BidReply]:
    """Return the leveling replies for the firms approved in dispatch.

    For each section present in both ``approvals`` and the template bank ``sor``, emit
    the benchmark first, then up to ``cap`` approved firms (in approval order): a firm
    with a pinned real offer uses it; any other firm takes the next representative
    template. Sections with no approved firm are skipped (nothing to level); the
    ``tender-scheduled-rates`` id is never treated as an approved firm.
    """
    replies: list[BidReply] = []
    for trade, section in sor.items():
        approved = [fid for fid in approvals.get(trade, []) if fid != BENCHMARK_ID][:cap]
        if not approved:
            continue
        replies.append(_reply(BENCHMARK_ID, trade, section["benchmark"]))
        pinned = section.get("pinned", {})
        templates = section.get("templates", [])
        next_template = 0
        for firm_id in approved:
            if firm_id in pinned:
                replies.append(_reply(firm_id, trade, pinned[firm_id]))
            elif templates:
                replies.append(_reply(firm_id, trade, templates[next_template % len(templates)]))
                next_template += 1
    return replies
