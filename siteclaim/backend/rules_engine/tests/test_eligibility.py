"""Spec for SOPO eligibility (the test name states the rule)."""

from datetime import date
from decimal import Decimal

from rules_engine.eligibility import check_eligibility
from rules_engine.tests._helpers import by_name, fatals, ff
from schemas.models import ContractType, Severity


def test_a_covered_main_construction_contract_is_eligible(compliant_facts):
    checks = check_eligibility(compliant_facts)
    assert not fatals(checks)
    assert by_name(checks, "eligibility.construction_contract").passed
    assert by_name(checks, "eligibility.threshold").passed


def test_a_non_construction_contract_type_is_fatal(compliant_facts):
    compliant_facts.contract_type = ff(ContractType.OTHER)
    c = by_name(check_eligibility(compliant_facts), "eligibility.construction_contract")
    assert c.severity is Severity.FATAL and not c.passed


def test_a_contract_below_the_threshold_is_fatal(compliant_facts):
    compliant_facts.contract_sum = ff(Decimal(4_000_000))  # well below 5,000,000
    c = by_name(check_eligibility(compliant_facts), "eligibility.threshold")
    assert c.severity is Severity.FATAL and not c.passed


def test_a_contract_at_the_threshold_edge_is_a_warning_not_fatal(compliant_facts):
    compliant_facts.contract_sum = ff(Decimal(5_100_000))  # within ~5% of 5,000,000
    checks = check_eligibility(compliant_facts)
    assert not fatals(checks)
    assert by_name(checks, "eligibility.threshold_edge").severity is Severity.WARNING


def test_a_subcontract_has_no_minimum_value(compliant_facts):
    compliant_facts.contract_type = ff(ContractType.SUBCONTRACT_CONSTRUCTION)
    compliant_facts.contract_sum = ff(Decimal(50_000))  # tiny, but inside a covered chain
    c = by_name(check_eligibility(compliant_facts), "eligibility.threshold")
    assert c.passed and c.severity is Severity.INFO


def test_a_contract_predating_commencement_is_fatal(compliant_facts):
    compliant_facts.contract_date = ff(date(2025, 1, 1))  # before 2025-08-28
    c = by_name(check_eligibility(compliant_facts), "eligibility.commencement")
    assert c.severity is Severity.FATAL and not c.passed


def test_a_consultancy_contract_is_a_contested_warning_not_fatal(compliant_facts):
    compliant_facts.contract_type = ff(ContractType.CONSULTANCY)
    checks = check_eligibility(compliant_facts)
    assert not fatals(checks)
    assert by_name(checks, "eligibility.construction_contract").severity is Severity.WARNING
