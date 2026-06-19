"""Notice / service validity — "claims die on a technicality" (Layer 1).

The highest-value check in the engine: was (or will) the payment claim be served
strictly correctly — on the right party, by a permitted method, with correct
timing, and with proof? A void notice sinks an otherwise good claim.

Where the underlying rule is UNVERIFIED in ``sopo_config`` (permitted service
methods, deemed receipt), the check is graded ``WARNING`` rather than ``FATAL`` —
we flag the risk without asserting a rule we have not confirmed. The two places
the defect is unambiguous (wrong party; serving before the reference date) are
``FATAL``.
"""

from schemas.models import Check, ExtractedFacts, Severity

from . import sopo_config
from ._common import check

_PARTY_REF = "SOPO Cap.652 (service on the respondent)"
_METHOD_REF = "SOPO Cap.652 (method of service)"
_TIMING_REF = "SOPO Cap.652 (timing of the claim)"
_PROOF_REF = "SOPO Cap.652 (proof of service)"


def check_notice_validity(facts: ExtractedFacts) -> list[Check]:
    """Flag every way the claim's service could be void or unprovable."""
    return [
        _check_correct_party(facts),
        _check_method(facts),
        _check_timing(facts),
        _check_proof(facts),
    ]


def _norm(text: str) -> str:
    return text.strip().lower()


def _check_correct_party(facts: ExtractedFacts) -> Check:
    served_on = facts.service.served_on.value
    respondent = facts.parties.respondent.value
    if served_on is None:
        return check(
            name="notice.correct_party",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_PARTY_REF,
            explanation="Who the claim was served on is unknown. A claim served on the wrong party is void — confirm it is served on the respondent.",
        )
    if respondent is None or not respondent.name:
        return check(
            name="notice.correct_party",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_PARTY_REF,
            explanation=f"Claim served on '{served_on}', but the respondent is not identified, so the correct-party requirement cannot be confirmed.",
        )
    if _norm(respondent.name) in _norm(served_on) or _norm(served_on) in _norm(respondent.name):
        return check(
            name="notice.correct_party",
            passed=True,
            severity=Severity.INFO,
            sopo_reference=_PARTY_REF,
            explanation=f"Claim served on '{served_on}', matching the respondent '{respondent.name}'.",
        )
    return check(
        name="notice.correct_party",
        passed=False,
        severity=Severity.FATAL,
        sopo_reference=_PARTY_REF,
        explanation=f"Claim served on '{served_on}', which does NOT match the respondent '{respondent.name}'. Service on the wrong party renders the notice void.",
    )


def _check_method(facts: ExtractedFacts) -> Check:
    method = facts.service.method.value
    if method is None:
        return check(
            name="notice.method",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_METHOD_REF,
            explanation="Service method unknown. Permitted methods are UNVERIFIED pending Cap.652 confirmation; verify the method is valid before serving.",
        )
    if method in sopo_config.PERMITTED_SERVICE_METHODS:
        return check(
            name="notice.method",
            passed=True,
            severity=Severity.INFO,
            sopo_reference=_METHOD_REF,
            explanation=f"Service method '{method}' is among the configured methods (note: sopo_config.PERMITTED_SERVICE_METHODS is UNVERIFIED — confirm against Cap.652).",
        )
    return check(
        name="notice.method",
        passed=False,
        severity=Severity.WARNING,
        sopo_reference=_METHOD_REF,
        explanation=f"Service method '{method}' is not in the (UNVERIFIED) permitted list; verify it is a valid method of service before relying on it.",
    )


def _check_timing(facts: ExtractedFacts) -> Check:
    served = facts.service.date_served.value or facts.claim_served_date.value
    reference = facts.reference_date.value
    if served is None:
        return check(
            name="notice.timing",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_TIMING_REF,
            explanation="Date of service unknown; timing cannot be checked. The service date anchors every downstream deadline — confirm it.",
        )
    if reference is not None and served < reference:
        return check(
            name="notice.timing",
            passed=False,
            severity=Severity.FATAL,
            sopo_reference=_TIMING_REF,
            explanation=f"Claim served on {served}, BEFORE its reference date {reference}. A claim cannot be validly served before the reference date it relates to.",
        )
    tail = f", on/after the reference date {reference}." if reference is not None else "; reference date unknown, so only basic timing is checked."
    return check(
        name="notice.timing",
        passed=True,
        severity=Severity.INFO,
        sopo_reference=_TIMING_REF,
        explanation=f"Claim served on {served}{tail}",
    )


def _check_proof(facts: ExtractedFacts) -> Check:
    proof = facts.service.proof_retained.value
    if proof is True:
        return check(
            name="notice.proof_of_service",
            passed=True,
            severity=Severity.INFO,
            sopo_reference=_PROOF_REF,
            explanation="Proof of service is retained.",
        )
    if proof is False:
        return check(
            name="notice.proof_of_service",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_PROOF_REF,
            explanation="No proof of service retained. Without dated proof you cannot establish when deadlines began to run — keep evidence of service.",
        )
    return check(
        name="notice.proof_of_service",
        passed=False,
        severity=Severity.WARNING,
        sopo_reference=_PROOF_REF,
        explanation="Whether proof of service is retained is unknown — ensure dated proof of service is kept.",
    )
