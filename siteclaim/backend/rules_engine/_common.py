"""Shared internals for the Rules Engine modules (private — not a public API).

Convention for the two fields on :class:`~schemas.models.Check`:

* ``severity`` drives blocking — only ``FATAL`` + ``passed is False`` makes a
  claim invalid (see ``ValidityReport.has_fatal``).
* ``passed`` records whether that specific condition was satisfied. A ``WARNING``
  may be ``passed=True`` (satisfied, but with an unverified caveat) or
  ``passed=False`` (a non-blocking concern). ``INFO`` is advisory.
"""

from schemas.models import Check, Severity

# Lower rank sorts first: fatal -> warning -> info.
SEVERITY_RANK: dict[Severity, int] = {
    Severity.FATAL: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


def check(
    *,
    name: str,
    passed: bool,
    severity: Severity,
    sopo_reference: str,
    explanation: str,
) -> Check:
    """Construct a :class:`Check` (keyword-only for readable call sites)."""
    return Check(
        name=name,
        passed=passed,
        severity=severity,
        sopo_reference=sopo_reference,
        explanation=explanation,
    )
