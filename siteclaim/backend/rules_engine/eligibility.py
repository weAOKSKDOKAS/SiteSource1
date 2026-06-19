"""Eligibility checks — does SOPO apply, and is this claimant covered? (Layer 1).

Deterministic, no LLM. Where the law is genuinely contested — most notably *what
counts* toward the application threshold — the check returns a ``WARNING`` with an
explanation, NOT a confident ``FATAL``. We flag the edge; we do not pretend
certainty.
"""

from datetime import date
from decimal import Decimal

from schemas.models import Check, ContractType, ExtractedFacts, Severity

from . import sopo_config
from ._common import check

# Heuristic (NOT a statutory value): how close to the threshold is treated as a
# contested edge rather than a clear pass/fail. Lives here, not in sopo_config,
# precisely because it is an engineering judgement, not law.
_THRESHOLD_EDGE_RATIO = Decimal("0.05")

_COVERED_CONTRACT_TYPES = frozenset(
    {
        ContractType.MAIN_CONSTRUCTION,
        ContractType.SUBCONTRACT_CONSTRUCTION,
        ContractType.SUPPLY_GOODS_AND_SERVICES,
    }
)

_APPLICATION_REF = "SOPO Cap.652 (application)"
_THRESHOLD_REF = "SOPO Cap.652 (application threshold)"
_COMMENCEMENT_REF = "SOPO commencement (28 Aug 2025)"


def check_eligibility(facts: ExtractedFacts) -> list[Check]:
    """Run every eligibility check and return the resulting Checks."""
    checks: list[Check] = [
        _check_construction_contract(facts),
        _check_commencement(facts),
    ]
    checks.extend(_check_threshold(facts))
    return checks


def _check_construction_contract(facts: ExtractedFacts) -> Check:
    ct = facts.contract_type.value
    if ct is None:
        return check(
            name="eligibility.construction_contract",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_APPLICATION_REF,
            explanation="Contract type is unknown, so SOPO coverage cannot be confirmed — needs human/QS confirmation.",
        )
    if ct in _COVERED_CONTRACT_TYPES:
        return check(
            name="eligibility.construction_contract",
            passed=True,
            severity=Severity.INFO,
            sopo_reference=_APPLICATION_REF,
            explanation=f"Contract type '{ct.value}' is within SOPO's construction-contract scope.",
        )
    if ct is ContractType.CONSULTANCY:
        return check(
            name="eligibility.construction_contract",
            passed=True,
            severity=Severity.WARNING,
            sopo_reference=_APPLICATION_REF,
            explanation=(
                "Whether consultancy / professional-services contracts are covered is a contested edge case — "
                "confirm with a construction lawyer (the consultancy threshold is UNVERIFIED in sopo_config). "
                "Not treated as a knock-out."
            ),
        )
    return check(
        name="eligibility.construction_contract",
        passed=False,
        severity=Severity.FATAL,
        sopo_reference=_APPLICATION_REF,
        explanation=f"Contract type '{ct.value}' does not appear to be a construction contract under SOPO; the Ordinance likely does not apply.",
    )


def _check_commencement(facts: ExtractedFacts) -> Check:
    contract_date = facts.contract_date.value
    commencement = date.fromisoformat(sopo_config.COMMENCEMENT_DATE)
    if contract_date is None:
        return check(
            name="eligibility.commencement",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_COMMENCEMENT_REF,
            explanation=f"Contract date unknown; SOPO applies only to contracts entered into on/after {commencement}. Confirm the contract date.",
        )
    if contract_date < commencement:
        return check(
            name="eligibility.commencement",
            passed=False,
            severity=Severity.FATAL,
            sopo_reference=_COMMENCEMENT_REF,
            explanation=f"Contract dated {contract_date} predates SOPO commencement ({commencement}); the Ordinance does not apply to it.",
        )
    return check(
        name="eligibility.commencement",
        passed=True,
        severity=Severity.INFO,
        sopo_reference=_COMMENCEMENT_REF,
        explanation=f"Contract dated {contract_date} is on/after SOPO commencement ({commencement}).",
    )


def _check_threshold(facts: ExtractedFacts) -> list[Check]:
    ct = facts.contract_type.value
    total = facts.contract_sum.value

    # Subcontracts within a covered chain have no minimum value (SOURCED CIC Q5/Q11).
    if ct is ContractType.SUBCONTRACT_CONSTRUCTION:
        return [
            check(
                name="eligibility.threshold",
                passed=True,
                severity=Severity.INFO,
                sopo_reference=_THRESHOLD_REF,
                explanation="Subcontracts within a covered chain have no minimum value (sopo_config.SUBCONTRACT_HAS_OWN_THRESHOLD is False; SOURCED CIC Q5/Q11).",
            )
        ]

    if total is None:
        return [
            check(
                name="eligibility.threshold",
                passed=False,
                severity=Severity.WARNING,
                sopo_reference=_THRESHOLD_REF,
                explanation="Contract sum unknown — cannot assess the application threshold. Note that WHAT counts toward the threshold (variations, fluctuations, provisional sums, related contracts) is itself contested.",
            )
        ]

    key = ct.value if ct is not None else ""
    threshold = sopo_config.THRESHOLD_BY_CONTRACT_TYPE.get(key, sopo_config.THRESHOLD_CONSTRUCTION_HKD)
    band = threshold * _THRESHOLD_EDGE_RATIO

    if total >= threshold + band:
        return [
            check(
                name="eligibility.threshold",
                passed=True,
                severity=Severity.INFO,
                sopo_reference=_THRESHOLD_REF,
                explanation=f"Contract sum HK${total:,} clearly meets the HK${threshold:,} threshold for '{key}'.",
            )
        ]
    if total <= threshold - band:
        return [
            check(
                name="eligibility.threshold",
                passed=False,
                severity=Severity.FATAL,
                sopo_reference=_THRESHOLD_REF,
                explanation=f"Contract sum HK${total:,} is below the HK${threshold:,} threshold for '{key}'; SOPO likely does not apply.",
            )
        ]
    # Within the edge band: contested, not a clean pass/fail.
    return [
        check(
            name="eligibility.threshold_edge",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_THRESHOLD_REF,
            explanation=(
                f"Contract sum HK${total:,} is within ~5% of the HK${threshold:,} threshold for '{key}'. WHAT counts toward "
                "the threshold (variations, fluctuations, provisional sums, retention, multiple related contracts) is a "
                "genuinely contested question under SOPO — this is NOT a clear knock-out; obtain a QS/legal view before "
                "relying on eligibility."
            ),
        )
    ]
