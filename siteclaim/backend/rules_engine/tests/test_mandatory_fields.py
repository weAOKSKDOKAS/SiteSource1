"""Spec for SOPO s.18 mandatory payment-claim particulars."""

from rules_engine.mandatory_fields import check_mandatory_fields
from rules_engine.tests._helpers import by_name, fatals
from schemas.models import FactField, Severity


def test_a_complete_claim_satisfies_every_s18_particular(compliant_facts):
    checks = check_mandatory_fields(compliant_facts)
    assert not fatals(checks)
    for key in ("in_writing", "identifies_work", "states_amount_and_basis"):
        assert by_name(checks, f"mandatory.{key}").passed


def test_a_claim_missing_the_claimed_amount_is_fatal(compliant_facts):
    compliant_facts.claimed_amount = FactField(value=None)
    c = by_name(check_mandatory_fields(compliant_facts), "mandatory.states_amount_and_basis")
    assert c.severity is Severity.FATAL and not c.passed


def test_a_claim_that_does_not_identify_the_work_is_fatal(compliant_facts):
    compliant_facts.work_period = FactField(value=None)
    compliant_facts.line_items = []
    compliant_facts.supporting_doc_refs = []
    c = by_name(check_mandatory_fields(compliant_facts), "mandatory.identifies_work")
    assert c.severity is Severity.FATAL and not c.passed


def test_an_amount_without_a_stated_basis_is_fatal(compliant_facts):
    compliant_facts.line_items = []  # remove the basis; the amount remains
    c = by_name(check_mandatory_fields(compliant_facts), "mandatory.states_amount_and_basis")
    assert c.severity is Severity.FATAL and not c.passed


def test_unnamed_parties_are_a_warning_not_fatal(compliant_facts):
    compliant_facts.parties.claimant = FactField(value=None)
    compliant_facts.parties.respondent = FactField(value=None)
    checks = check_mandatory_fields(compliant_facts)
    assert not fatals(checks)
    assert by_name(checks, "mandatory.parties_identified").severity is Severity.WARNING
