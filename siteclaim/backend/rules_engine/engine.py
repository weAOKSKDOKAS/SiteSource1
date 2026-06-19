"""Rules Engine orchestrator (Layer 1, deterministic — NO LLM).

``run_validation`` runs every check module over the facts, attaches the computed
deadline set, and returns one :class:`ValidityReport` with findings sorted
fatal -> warning -> info. This is the single entry point Stage 02 calls.
"""

from datetime import date

from schemas.models import ExtractedFacts, ValidityReport

from . import deadlines as deadlines_mod
from ._common import SEVERITY_RANK
from .eligibility import check_eligibility
from .mandatory_fields import check_mandatory_fields
from .notice_validity import check_notice_validity
from .set_off import detect_set_off_trap


def run_validation(facts: ExtractedFacts, today: date) -> ValidityReport:
    """Run all Layer 1 checks and attach the deadline set, as one sorted report."""
    checks = [
        *check_eligibility(facts),
        *check_mandatory_fields(facts),
        *check_notice_validity(facts),
        *detect_set_off_trap(facts),
    ]
    # Sort fatal -> warning -> info; within a severity, failures before passes, then by name.
    checks.sort(key=lambda c: (SEVERITY_RANK[c.severity], c.passed, c.name))

    deadline_set = deadlines_mod.compute_deadlines(facts, today)
    return ValidityReport(checks=checks, deadlines=deadline_set)
