"""Deterministic bid leveling (Layer 1).

Implements ``references/rubrics/leveling_rules.md``. The LLM parses a reply into a
:class:`BidReply`; **every calculation and judgement below is pure Python**, never
the model.

A returned Schedule of Rates is compared **rate-first**: the unit rate for each item is
lined up across firms as the primary comparison, and it works even when nothing on the
schedule carries a quantity (a rate-only SoR). Amounts are computed only where a quantity
exists to extend them, so a rate-only line is never forced through ``qty x rate``:

* the **computable amount** of a line is ``qty x rate`` when both are present (recomputed —
  the recomputed value is authoritative, and *is* the arithmetic correction), a stated
  lump-sum ``amount`` when there is no rate to extend, and otherwise **nothing** — a
  rate-only line is compared by rate, not by amount;
* an :class:`ArithmeticFinding` (warning) is raised only where there is a computable
  ``qty x rate`` to check a stated amount against — a rate-only line is never a discrepancy;
* ``corrected_total`` = the sum of the computable line amounts (rate-only lines contribute
  nothing to it);
* a line with **no price signal at all** (no rate and no stated amount) is a **scope gap** —
  recorded, never treated as zero, never silently filled;
* a **stated exclusion** is a flagged, non-comparable item — recorded, never used to
  silently lower the price;
* ``normalized_total`` puts every bid on the **same scope basis**: it starts from
  ``corrected_total`` and adds, for each scope gap, the peer median price of that item
  across the other bids that did price it — so a bid that left scope out is compared
  like-for-like. Scope differences are surfaced, never absorbed.

``claimed_total`` (the bidder's own total, on :class:`BidReply`) is recorded upstream but
never used for ranking — only ``corrected_total`` is.
"""

from __future__ import annotations

from statistics import median
from typing import Optional

from schemas.models import ArithmeticFinding, BidLineItem, BidReply, ItemRate, LevelledBid, Severity

_EPSILON = 0.005  # currency tolerance for the qty*rate vs stated-amount comparison


def computable_amount(line: BidLineItem) -> Optional[float]:
    """The line's amount, only where one can be computed — never ``None * float``.

    * both ``qty`` and ``rate`` present -> ``qty x rate``, **recomputed** (this is the
      leveling correction; the recomputed value is authoritative over any stated amount);
    * a stated lump-sum ``amount`` with no ``rate`` to extend -> taken as stated;
    * a **rate-only** line (a rate but no quantity) or a wholly unpriced line -> ``None``:
      it is compared by rate and contributes no amount.
    """
    if line.qty is not None and line.rate is not None:
        return round(line.qty * line.rate, 2)
    if line.rate is None and line.amount is not None:
        return round(line.amount, 2)
    return None


def peer_item_reference(replies: list[BidReply]) -> dict[str, float]:
    """For each item_ref, the median computable amount across bids that priced it.

    Used to value another bid's scope gaps at a fair peer price for ``normalized_total``.
    Rate-only lines contribute no amount here, so a gap is valued only where peers actually
    extended that item to an amount.
    """
    amounts: dict[str, list[float]] = {}
    for reply in replies:
        for line in reply.line_items:
            amount = computable_amount(line)
            if amount is not None:
                amounts.setdefault(line.item_ref, []).append(amount)
    return {item_ref: float(median(values)) for item_ref, values in amounts.items() if values}


def level_reply(
    reply: BidReply,
    firm_name: str,
    peer_reference: dict[str, float] | None = None,
    *,
    unpriced_scope: list[tuple[str, str, float]] | None = None,
) -> LevelledBid:
    """Level one :class:`BidReply` into a :class:`LevelledBid` (pure, deterministic).

    ``unpriced_scope`` puts the bid on the tender's COMMON SCOPE BASIS: the canonical items of this
    reply's routed unit the firm did NOT return, each as ``(item_ref, description, peer_value)``.
    They are recorded as scope gaps (so a return that priced only part of its enquiry is honest) and
    valued at ``peer_value`` in ``normalized_total`` — a bid that left scope out is compared
    like-for-like. Supplied by the scope-aware caller (:func:`level_bids` with a scope); ``None``
    keeps the reply-anchored behaviour. Pure Layer 1 — no model, no pipeline import here."""
    peer_reference = peer_reference or {}
    item_rates: list[ItemRate] = []
    findings: list[ArithmeticFinding] = []
    scope_gaps: list[str] = []
    gap_item_refs: list[str] = []
    corrected_total = 0.0

    for line in reply.line_items:
        amount = computable_amount(line)
        # The rate comparison is the foundation and is recorded for every line, whether or
        # not it has a quantity; the amount is only shown where it is computable.
        item_rates.append(ItemRate(
            item_ref=line.item_ref, description=line.description,
            unit=line.unit, rate=line.rate, amount=amount,
        ))

        if line.rate is None and line.amount is None:
            # No price signal at all -> scope gap. Never zero, never filled; valued at the
            # peer median in normalized_total below.
            desc = line.description or ""
            kind = "missing provisional sum" if "provisional" in desc.lower() else "missing rate"
            scope_gaps.append(f"{line.item_ref} — {desc} ({kind})")
            gap_item_refs.append(line.item_ref)
            continue

        # An arithmetic finding needs a recomputed qty*rate to check the stated amount
        # against — a rate-only line (no quantity) is never an arithmetic discrepancy.
        if line.qty is not None and line.rate is not None and line.amount is not None:
            recomputed = round(line.qty * line.rate, 2)
            if abs(line.amount - recomputed) > _EPSILON:
                findings.append(ArithmeticFinding(
                    location=f"line {line.item_ref}",
                    issue=f"stated amount {line.amount:,.0f} != qty x rate {recomputed:,.0f}",
                    corrected_value=recomputed,
                    severity=Severity.WARNING,
                ))

        # The total sums computable amounts only; a rate-only line adds nothing to it.
        if amount is not None:
            corrected_total += amount

    # Common-scope basis: canonical items of this unit the firm never returned are gaps too — listed
    # so partial coverage is visible, and valued at the peer price so bids compare like-for-like.
    normalized_extra = sum(peer_reference.get(ref, 0.0) for ref in gap_item_refs)
    for ref, desc, peer_value in unpriced_scope or []:
        scope_gaps.append(f"{ref} — {desc} (not returned)".rstrip())
        normalized_extra += peer_value

    corrected_total = round(corrected_total, 2)
    normalized_total = round(corrected_total + normalized_extra, 2)

    return LevelledBid(
        firm_id=reply.firm_id,
        firm_name=firm_name,
        trade=reply.trade,
        normalized_total=normalized_total,
        corrected_total=corrected_total,
        item_rates=item_rates,
        arithmetic_findings=findings,
        exclusions=list(reply.exclusions),  # flagged, non-comparable; never lowers the price
        scope_gaps=scope_gaps,
    )
