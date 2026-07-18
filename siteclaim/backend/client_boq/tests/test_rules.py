"""Unit tests for the deterministic threshold rules (client_boq/rules.py).

Every one of the 8 rules gets an explicit breaching and non-breaching value, and we assert the rule
ids implemented here exactly match the 'Deterministic threshold checks' table in review_criteria.md
(so a change to the doc is caught, not silently diverged). The rules are the numeric decision layer —
these tests are the guarantee that a breach flag is deterministic and reproducible.
"""

from __future__ import annotations

import pytest

from client_boq import rules
from client_boq.criteria_loader import load_criteria

# (criterion_id, breaching_value, non_breaching_value)
CASES = [
    ("TP-03", "notified within 3 business days", "notified within 10 business days"),
    ("TP-04", "liquidated damages uncapped", "liquidated damages capped at 8% of contract"),
    ("PS-01", "assessed within 30 business days", "assessed within 14 business days"),
    ("PS-04", "retention 10%, released at Final Certificate", "retention 5%, 2.5% released at Practical Completion"),
    ("PS-05", "security called without notice", "5 business days' notice before calling security"),
    ("LR-01", "liability uncapped", "liability capped at the Subcontract value"),
    ("LR-05", "remedied within 5 days", "cure period of 14 days"),
    ("SQD-05", "defects liability period 24 months", "defects liability period 12 months"),
]


@pytest.mark.parametrize("cid,breach,ok", CASES)
def test_threshold_breach(cid: str, breach: str, ok: str) -> None:
    assert rules.is_threshold_criterion(cid)
    assert rules.evaluate_threshold(cid, breach) is True, f"{cid} should flag {breach!r}"
    assert rules.evaluate_threshold(cid, ok) is False, f"{cid} should NOT flag {ok!r}"


def test_absent_arms_flag() -> None:
    # The rules whose threshold table row includes an "or none/absent" arm must flag on absence.
    assert rules.evaluate_threshold("TP-04", "no cap") is True
    assert rules.evaluate_threshold("PS-05", "none") is True
    assert rules.evaluate_threshold("LR-01", "no liability cap") is True
    assert rules.evaluate_threshold("LR-05", "no cure period") is True
    # ...while the number-only rules do not treat a missing value as a breach.
    assert rules.evaluate_threshold("TP-03", "no notice requirement stated") is False
    assert rules.evaluate_threshold("SQD-05", "defects period unspecified") is False


def test_non_threshold_criterion_raises() -> None:
    assert not rules.is_threshold_criterion("SQD-06")
    with pytest.raises(KeyError):
        rules.evaluate_threshold("SQD-06", "anything")


def test_implemented_ids_match_the_doc() -> None:
    lib = load_criteria()
    assert rules.known_threshold_ids() == lib.threshold_ids(), (
        "rules.py threshold ids diverge from review_criteria.md's threshold table"
    )
