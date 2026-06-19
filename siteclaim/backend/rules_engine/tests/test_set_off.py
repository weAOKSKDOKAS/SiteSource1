"""Spec for the payer-side set-off trap (CIC Q25)."""

from rules_engine.set_off import detect_set_off_trap
from rules_engine.tests._helpers import by_name
from schemas.models import FactField, Severity


def test_a_served_payment_response_preserves_set_off(compliant_facts):
    # The compliant fixture records a served response.
    c = by_name(detect_set_off_trap(compliant_facts), "set_off.response_served")
    assert c.passed and c.severity is Severity.INFO


def test_a_missing_payment_response_flags_the_set_off_trap(compliant_facts):
    compliant_facts.payment_response.served = FactField(value=False)
    c = by_name(detect_set_off_trap(compliant_facts), "set_off.response_missing")
    assert c.severity is Severity.WARNING and not c.passed
