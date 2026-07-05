"""Rate-primary variance math (Layer 1 — pure, deterministic).

Between a priced tender line and an actual outturn line, compute the variance the same
rate-first way the leveling engine computes amounts (mirrors
``rules_engine.leveling.computable_amount``):

* **rate_delta always** when both a tender rate and an actual rate exist;
* **amounts only where computable** — an amount exists when qty·rate is available (or a
  stated lump-sum amount with no rate) — never fabricated for a rate-only line;
* when **both sides carry qty + rate**, ``amount_delta`` decomposes exactly into a
  **qty-driven** and a **rate-driven** component:
  ``amount_delta_qty = (actual_qty − tender_qty)·tender_rate``,
  ``amount_delta_rate = actual_qty·(actual_rate − tender_rate)``,
  and ``amount_delta_qty + amount_delta_rate = amount_delta`` (exactly).

Either side may be ``None`` (a Tier-3 unmatched line): an omission-at-tender has no
tender side, an arrived-unpriced / coarse actual has no matching tender.
"""

from __future__ import annotations

from typing import Optional

_EPSILON = 0.005  # currency tolerance (mirrors leveling._EPSILON)


def computable_amount(qty: Optional[float], rate: Optional[float], amount: Optional[float]) -> Optional[float]:
    """The line's amount where one can be computed — never ``None * float`` (mirrors
    ``leveling.computable_amount`` on raw values)."""
    if qty is not None and rate is not None:
        return round(qty * rate, 2)
    if rate is None and amount is not None:
        return round(amount, 2)
    return None


def _f(item: Optional[dict], key: str) -> Optional[float]:
    if not item:
        return None
    v = item.get(key)
    return float(v) if isinstance(v, (int, float)) else None


def variance_between(tender: Optional[dict], actual: Optional[dict]) -> dict:
    """Return the variance fields between a tender item and an actual item (either may be
    ``None``). Keys mirror the ``variance_records`` columns."""
    t_qty, t_rate, t_amt = _f(tender, "qty"), _f(tender, "rate"), _f(tender, "amount")
    a_qty, a_rate, a_amt = _f(actual, "qty"), _f(actual, "rate"), _f(actual, "amount")

    tender_amount = computable_amount(t_qty, t_rate, t_amt)
    actual_amount = computable_amount(a_qty, a_rate, a_amt)

    rate_delta = rate_delta_pct = None
    if t_rate is not None and a_rate is not None:
        rate_delta = round(a_rate - t_rate, 4)
        if abs(t_rate) > _EPSILON:
            rate_delta_pct = round((a_rate - t_rate) / t_rate * 100.0, 2)

    amount_delta = amount_delta_qty = amount_delta_rate = None
    if t_qty is not None and t_rate is not None and a_qty is not None and a_rate is not None:
        # Both sides fully quantified -> decompose (exactly additive).
        amount_delta_qty = round((a_qty - t_qty) * t_rate, 2)
        amount_delta_rate = round(a_qty * (a_rate - t_rate), 2)
        amount_delta = round(amount_delta_qty + amount_delta_rate, 2)
    elif tender_amount is not None and actual_amount is not None:
        # A computable amount on each side but not both fully quantified (e.g. lump sums).
        amount_delta = round(actual_amount - tender_amount, 2)

    return {
        "tender_qty": t_qty, "actual_qty": a_qty,
        "tender_rate": t_rate, "actual_rate": a_rate,
        "tender_amount": tender_amount, "actual_amount": actual_amount,
        "rate_delta": rate_delta, "rate_delta_pct": rate_delta_pct,
        "amount_delta": amount_delta,
        "amount_delta_qty": amount_delta_qty, "amount_delta_rate": amount_delta_rate,
    }
