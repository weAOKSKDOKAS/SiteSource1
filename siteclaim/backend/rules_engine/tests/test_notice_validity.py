"""Spec for notice / service validity — where claims die on a technicality."""

from datetime import date

from rules_engine.notice_validity import check_notice_validity
from rules_engine.tests._helpers import by_name, fatals, ff
from schemas.models import FactField, Severity


def test_a_correctly_served_notice_passes(compliant_facts):
    checks = check_notice_validity(compliant_facts)
    assert not fatals(checks)
    assert by_name(checks, "notice.correct_party").passed
    assert by_name(checks, "notice.timing").passed


def test_service_on_the_wrong_party_is_fatal(compliant_facts):
    compliant_facts.service.served_on = ff("Totally Different Co Ltd")
    c = by_name(check_notice_validity(compliant_facts), "notice.correct_party")
    assert c.severity is Severity.FATAL and not c.passed


def test_serving_the_claim_before_its_reference_date_is_fatal(compliant_facts):
    # reference date is 2026-02-28; serving the day before is premature.
    compliant_facts.service.date_served = ff(date(2026, 2, 27))
    compliant_facts.claim_served_date = ff(date(2026, 2, 27))
    c = by_name(check_notice_validity(compliant_facts), "notice.timing")
    assert c.severity is Severity.FATAL and not c.passed


def test_an_unknown_service_method_is_a_warning_not_fatal(compliant_facts):
    compliant_facts.service.method = FactField(value=None)
    checks = check_notice_validity(compliant_facts)
    assert not fatals(checks)
    assert by_name(checks, "notice.method").severity is Severity.WARNING


def test_no_proof_of_service_is_a_warning(compliant_facts):
    compliant_facts.service.proof_retained = ff(False)
    c = by_name(check_notice_validity(compliant_facts), "notice.proof_of_service")
    assert c.severity is Severity.WARNING and not c.passed
