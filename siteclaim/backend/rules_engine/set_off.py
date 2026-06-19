"""Set-off trap — payer-side risk (Layer 1, deterministic).

Flags where the RESPONDENT risks losing its set-off rights by not serving a
payment response in time. Under SOPO (``sopo_config.SET_OFF_FORFEIT_ON_NO_RESPONSE``,
CIC Q25), failing to serve a payment response by the s.20 deadline forfeits the
right to raise a set-off in any later adjudication.

This is graded ``WARNING`` (a risk flag for the payer), never ``FATAL`` — it does
not invalidate the claimant's claim.
"""

from schemas.models import Check, ExtractedFacts, Severity

from . import business_days, sopo_config
from ._common import check

_REF = "SOPO s.20 / CIC Q25"


def detect_set_off_trap(facts: ExtractedFacts) -> list[Check]:
    """Flag the respondent's set-off forfeiture risk from a missing/late response."""
    if not sopo_config.SET_OFF_FORFEIT_ON_NO_RESPONSE:
        return []  # rule disabled in config

    if facts.payment_response.served.value is True:
        return [
            check(
                name="set_off.response_served",
                passed=True,
                severity=Severity.INFO,
                sopo_reference=_REF,
                explanation="A payment response is recorded, so the respondent's set-off is preserved (subject to the response having been served within the s.20 window).",
            )
        ]

    served_date = facts.claim_served_date.value or facts.reference_date.value
    due_text = ""
    if served_date is not None:
        response_due = business_days.add_calendar_days(served_date, sopo_config.PAYMENT_RESPONSE_DAYS)
        due_text = (
            f" The response is due by {response_due} "
            f"({sopo_config.PAYMENT_RESPONSE_DAYS} days after service on {served_date})."
        )
    return [
        check(
            name="set_off.response_missing",
            passed=False,
            severity=Severity.WARNING,
            sopo_reference=_REF,
            explanation=(
                "PAYER-SIDE RISK: no payment response is recorded. Under SOPO, failing to serve a payment response by "
                "the s.20 deadline forfeits the respondent's right to raise a set-off in adjudication." + due_text
            ),
        )
    ]
