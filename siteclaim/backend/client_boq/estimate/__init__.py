"""ESTIMATE workflow stages (s01–s06). See ../CONTEXT.md for the bucket of each stage.

Rounding rule (applied uniformly across the deterministic spine): every monetary value is rounded to
**2 decimal places with Python's round (round half-to-even)** at each step — each resource line
amount, each activity total (the sum of its already-rounded line amounts), each indirect amount, and
each total/price. Summing already-rounded parts means a human can add up the displayed line amounts
by hand and get the displayed activity/total, and re-running with the same inputs is byte-identical.
"""

from __future__ import annotations


def money(x: float) -> float:
    """Round a monetary value to 2 dp (round half-to-even). The single rounding point for the spine."""
    return round(float(x), 2)
