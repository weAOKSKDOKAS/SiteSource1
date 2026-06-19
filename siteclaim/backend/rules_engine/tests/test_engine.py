"""Spec for the orchestrator: one sorted report with deadlines attached."""

from datetime import date

from rules_engine._common import SEVERITY_RANK
from rules_engine.deadlines import clock
from rules_engine.engine import run_validation
from rules_engine.tests._helpers import ff
from schemas.models import ContractType, FactField, Severity


def test_a_clean_claim_has_no_fatal_and_attaches_the_deadline_set(compliant_facts, today):
    report = run_validation(compliant_facts, today)
    assert report.is_valid and not report.has_fatal
    assert report.deadlines is not None
    assert len(report.deadlines.deadlines) == 3


def test_a_missing_mandatory_field_makes_the_report_invalid(compliant_facts, today):
    compliant_facts.claimed_amount = FactField(value=None)
    report = run_validation(compliant_facts, today)
    assert report.has_fatal and not report.is_valid


def test_findings_are_sorted_fatal_then_warning_then_info(compliant_facts, today):
    compliant_facts.contract_type = ff(ContractType.OTHER)  # -> fatal eligibility
    compliant_facts.service.proof_retained = ff(False)  # -> warning
    report = run_validation(compliant_facts, today)
    ranks = [SEVERITY_RANK[c.severity] for c in report.checks]
    assert ranks == sorted(ranks)
    assert report.checks[0].severity is Severity.FATAL


def test_a_breached_deadline_surfaces_in_the_attached_deadline_set(compliant_facts):
    today = date(2026, 3, 2)
    compliant_facts.claim_served_date = ff(date(2026, 1, 1))
    report = run_validation(compliant_facts, today)
    assert clock(report.deadlines, today).any_breached
