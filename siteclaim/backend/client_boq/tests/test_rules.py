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
    # The rules whose threshold table row includes an "or none/absent" arm must flag on absence. Each
    # rule detects absence with FIELD-SPECIFIC phrasing (not a shared generic token like "none", which
    # caused cross-field false positives), so these use realistic extracted values.
    assert rules.evaluate_threshold("TP-04", "no cap") is True
    assert rules.evaluate_threshold("PS-05", "no prior notice before calling the security") is True
    assert rules.evaluate_threshold("LR-01", "no liability cap") is True
    assert rules.evaluate_threshold("LR-05", "no cure period") is True
    # ...while the number-only rules do not treat a missing value as a breach.
    assert rules.evaluate_threshold("TP-03", "no notice requirement stated") is False
    assert rules.evaluate_threshold("SQD-05", "defects period unspecified") is False


def test_ps04_no_release_arm_at_or_below_cap() -> None:
    # The "no release at Practical Completion" arm must flag independently of the >5% cap arm — i.e.
    # for a retention AT or BELOW 5% that is still not released at PC (regression guard: the >5% arm
    # must not be the only thing tested).
    assert rules.evaluate_threshold("PS-04", "Retention 5%, released only at Final Certificate") is True
    assert rules.evaluate_threshold("PS-04", "Retention 4%, no release until end of the DLP") is True
    # ...but a <=5% retention that IS released at PC is compliant, even with the balance at Final
    # Certificate, and even when PC is written as the "PC" abbreviation (the fix for the flagged bug).
    assert rules.evaluate_threshold("PS-04", "Retention 5%, half released at PC and half at Final Certificate") is False
    assert rules.evaluate_threshold("PS-04", "5% retention, 2.5% released at PC") is False


def test_lr01_present_cap_with_carveout_is_not_flagged() -> None:
    # A liability cap IS present — a standard fraud/PI carve-out that is "unlimited" must NOT be read
    # as "no cap present" (adequacy of a present cap is a human judgement, not a rule flag).
    assert rules.evaluate_threshold("LR-01", "Total liability capped at the Subcontract value; save for fraud, which is unlimited") is False
    assert rules.evaluate_threshold("LR-01", "Liability limited to the Contract Sum") is False
    # A genuinely absent cap still flags.
    assert rules.evaluate_threshold("LR-01", "The Subcontractor's liability is unlimited") is True


def test_absent_keywords_do_not_bleed_across_fields() -> None:
    # A PS-05 phrase appearing in an LD-cap value must not flag TP-04 as "LD cap absent" (the shared
    # word list that caused cross-field bleed is gone).
    assert rules.evaluate_threshold("TP-04", "LD cap 8% of contract; the Employer may call security without notice") is False


def test_non_threshold_criterion_raises() -> None:
    assert not rules.is_threshold_criterion("SQD-06")
    with pytest.raises(KeyError):
        rules.evaluate_threshold("SQD-06", "anything")


def test_implemented_ids_match_the_doc() -> None:
    lib = load_criteria()
    assert rules.known_threshold_ids() == lib.threshold_ids(), (
        "rules.py threshold ids diverge from review_criteria.md's threshold table"
    )
