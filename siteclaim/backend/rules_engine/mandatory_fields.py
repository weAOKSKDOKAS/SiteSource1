"""Mandatory payment-claim particulars — SOPO s.18 (Layer 1, deterministic).

Iterates ``sopo_config.MANDATORY_CLAIM_PARTICULARS`` (the SOURCED s.18 list:
in_writing / identifies_work / states_amount_and_basis) and verifies each is
present and non-empty. Missing any is ``FATAL``.

A few additional completeness checks (parties identified, reference date) are
included as ``WARNING`` — they are needed for a usable claim but are NOT part of
the grounded s.18 content list, so they are deliberately not treated as statutory
knock-outs. (The original Phase-1 brief listed more particulars under "s.13";
Phase 0c grounded the actual content requirement to these three s.18 items.)
"""

from typing import Optional

from schemas.models import Check, ClaimDraft, ExtractedFacts, Severity

from . import sopo_config
from ._common import check

_S18_REF = "SOPO s.18"
_COMPLETENESS_REF = "SOPO Cap.652 (claim completeness)"


def check_mandatory_fields(facts: ExtractedFacts, draft: Optional[ClaimDraft] = None) -> list[Check]:
    """Verify each s.18 particular (fatal if missing) plus completeness (warnings)."""
    evaluated = _evaluate_s18(facts, draft)

    checks: list[Check] = []
    for key, description in sopo_config.MANDATORY_CLAIM_PARTICULARS:
        ok, detail = evaluated[key]  # KeyError here is intentional: a new s.18 particular must be taught to _evaluate_s18
        checks.append(
            check(
                name=f"mandatory.{key}",
                passed=ok,
                severity=Severity.INFO if ok else Severity.FATAL,
                sopo_reference=_S18_REF,
                explanation=f"s.18 requires that {description}. {detail}",
            )
        )
    checks.extend(_completeness_checks(facts))
    return checks


def _evaluate_s18(facts: ExtractedFacts, draft: Optional[ClaimDraft]) -> dict[str, tuple[bool, str]]:
    work_period = facts.work_period.value
    has_work_period = bool(work_period and (work_period.start or work_period.end))
    has_lines = bool(facts.line_items) or bool(draft and draft.line_items)
    has_docs = bool(facts.supporting_doc_refs)
    has_basis_text = bool(draft and (draft.basis_of_calculation or "").strip())
    amount = facts.claimed_amount.value

    in_writing = bool(facts.claim_in_writing.value) or bool(draft and draft.rendered_markdown.strip())
    identifies_work = has_work_period or has_lines or has_docs
    amount_ok = amount is not None and amount > 0
    has_basis = has_lines or has_basis_text
    states_amount_and_basis = amount_ok and has_basis

    return {
        "in_writing": (
            in_writing,
            "Present." if in_writing else "MISSING — the claim is not recorded as being in writing.",
        ),
        "identifies_work": (
            identifies_work,
            "Present." if identifies_work else "MISSING — no work period, line items, or supporting documents identify the work.",
        ),
        "states_amount_and_basis": (
            states_amount_and_basis,
            "Present."
            if states_amount_and_basis
            else (
                "MISSING — the claimed amount is absent."
                if not amount_ok
                else "MISSING — the claimed amount is given but its basis/calculation is not shown."
            ),
        ),
    }


def _completeness_checks(facts: ExtractedFacts) -> list[Check]:
    claimant = facts.parties.claimant.value
    respondent = facts.parties.respondent.value
    parties_ok = bool(claimant and claimant.name) and bool(respondent and respondent.name)
    reference_ok = facts.reference_date.value is not None

    return [
        check(
            name="mandatory.parties_identified",
            passed=parties_ok,
            severity=Severity.INFO if parties_ok else Severity.WARNING,
            sopo_reference=_COMPLETENESS_REF,
            explanation=(
                "Claimant and respondent are identified."
                if parties_ok
                else "Claimant and/or respondent not identified. Not part of the grounded s.18 list, but a claim is unusable without naming the parties — confirm."
            ),
        ),
        check(
            name="mandatory.reference_date",
            passed=reference_ok,
            severity=Severity.INFO if reference_ok else Severity.WARNING,
            sopo_reference=_COMPLETENESS_REF,
            explanation=(
                "A reference date is recorded."
                if reference_ok
                else "No reference date recorded; it anchors the claim period and the deadline clock. (Reference-date rules are UNVERIFIED in sopo_config.)"
            ),
        ),
    ]
