"""ESTIMATE stage 04 — indirect costs & allowances.

Bucket (mapping doc estimate task 11): **Deterministic**. Indirects are formula-driven
(duration × rate, % × value) off the direct costs from s03 — numbers are deterministic, no AI.
"""

from __future__ import annotations

from client_boq.models import CostBuildup, IndirectsResult


def build_indirects(direct: CostBuildup) -> IndirectsResult:
    """Compute indirect costs and allowances by formula from the direct total. Not implemented yet."""
    raise NotImplementedError("client_boq ESTIMATE s04 (indirects) — scaffold only")
