"""ESTIMATE stage 05 — estimate validation.

Bucket (mapping doc estimate task 12): **Rule-based flags**. Threshold checks — scope coverage,
quantity sense, rate benchmarking — raise flags against benchmark bands. The flags are rule-raised;
the verdict stays human. No AI decision value.
"""

from __future__ import annotations

from client_boq.models import CostBuildup, IndirectsResult, PricingSchedule, ValidationResult


def validate_estimate(
    schedule: PricingSchedule, direct: CostBuildup, indirects: IndirectsResult,
) -> ValidationResult:
    """Raise rule-based validation flags (scope coverage, quantity sense, rate benchmark).
    Not implemented yet."""
    raise NotImplementedError("client_boq ESTIMATE s05 (validate) — scaffold only")
