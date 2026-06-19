"""Test helpers + the compliant ``ExtractedFacts`` factory (shared, not collected).

``make_compliant_facts`` builds a fully-populated, SOPO-valid claim anchored to
``TODAY``; each test mutates a fresh copy to express the single rule under test.
"""

from datetime import date
from decimal import Decimal

from schemas.models import (
    Check,
    ContractType,
    ExtractedFacts,
    FactField,
    LineItem,
    Parties,
    Party,
    PaymentResponseFacts,
    Sector,
    ServiceDetails,
    Severity,
    WorkPeriod,
)

TODAY = date(2026, 3, 2)  # a Monday; not a HK public holiday in sopo_config


def ff(value, confidence: float = 0.95, span: str = "test-fixture") -> FactField:
    """Wrap a value in a high-confidence FactField (terse helper for fixtures)."""
    return FactField(value=value, confidence=confidence, source_span=span)


def make_compliant_facts() -> ExtractedFacts:
    """A fully-populated, SOPO-compliant claim anchored to TODAY."""
    served = TODAY
    reference = date(2026, 2, 28)
    return ExtractedFacts(
        contract_sum=ff(Decimal(8_000_000)),
        contract_type=ff(ContractType.MAIN_CONSTRUCTION),
        sector=ff(Sector.PRIVATE),
        parties=Parties(
            claimant=ff(Party(name="Acme Subcontracting Ltd", role="subcontractor")),
            respondent=ff(Party(name="BigBuild Main Contractor Ltd", role="main contractor")),
        ),
        reference_date=ff(reference),
        claimed_amount=ff(Decimal("1250000.00")),
        work_period=ff(WorkPeriod(start=date(2026, 2, 1), end=reference)),
        line_items=[LineItem(description="Rebar fixing to grid C-F", amount=Decimal("1250000.00"), confidence=0.9)],
        supporting_doc_refs=["invoice_42.pdf", "site_diary_feb.pdf"],
        contract_date=ff(date(2025, 9, 1)),  # after the 2025-08-28 commencement
        claim_served_date=ff(served),
        claim_in_writing=ff(True),
        service=ServiceDetails(
            method=ff("personal_delivery"),
            served_on=ff("BigBuild Main Contractor Ltd"),
            date_served=ff(served),
            proof_retained=ff(True),
        ),
        payment_response=PaymentResponseFacts(served=ff(True), date_served=ff(served)),
    )


def by_name(checks: list[Check], name: str) -> Check:
    """Return the single check with ``name`` (asserts exactly one exists)."""
    matches = [c for c in checks if c.name == name]
    assert len(matches) == 1, f"expected exactly one check named {name!r}, got {[c.name for c in checks]}"
    return matches[0]


def names(checks: list[Check]) -> set[str]:
    return {c.name for c in checks}


def fatals(checks: list[Check]) -> list[Check]:
    """The blocking findings: FATAL severity and not passed."""
    return [c for c in checks if c.severity is Severity.FATAL and not c.passed]
