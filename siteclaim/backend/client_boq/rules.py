"""Deterministic threshold rules for REVIEW s03 — the numeric decision layer.

The 8 rows of the 'Deterministic threshold checks' table in ``review_criteria.md`` are the ONLY
criteria the machine pre-flags. Each rule is a pure predicate over the value the AI extracted from
the contract (a string like ``"Retention 10%, released at final certificate"``); the rule parses the
number/keywords and returns whether the acceptable position is breached. The AI never runs these —
it only supplies the extracted string — so the flag is a deterministic decision, reproducible and
independent of the model.

Semantics come straight from the threshold table (note which rules include an "or none/absent" arm):

    TP-03  notice period < 5 business days                                  (number only)
    TP-04  LD cap absent, OR LD cap > 10%                                   (absent OR number)
    PS-01  payment assessment period > 20 business days                    (number only)
    PS-04  retention > 5%, OR no release at Practical Completion            (number OR keyword)
    PS-05  notice before calling security < 5 days, OR none                 (number OR absent)
    LR-01  no liability cap present                                         (absent only)
    LR-05  cure period < 7 days, OR none                                    (number OR absent)
    SQD-05 DLP > 12 months                                                  (number only)

A rule raises the flag; a human still confirms the departure (the verdict is never written here).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

# The first number in a string (percent, days, months — the unit is implied by the rule).
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")

# Keywords that mean "the protection is simply not there" — an absent cap / notice / cure / release.
_ABSENT_WORDS = (
    "uncapped", "no cap", "not capped", "no limit", "unlimited", "no ld cap",
    "no liability cap", "no notice", "without notice", "no prior notice", "no cure",
    "no cure period", "immediate termination", "without cure", "no release",
    "not released", "no pc release", "absent", "none", "nil", "not present", "not provided",
)


def _first_number(value: str) -> Optional[float]:
    """The first numeric token in ``value`` (percent/days/months), or None."""
    m = _NUMBER_RE.search(value or "")
    return float(m.group(1)) if m else None


def _mentions_absent(value: str, *extra: str) -> bool:
    """True when the value signals the protection is absent (base keywords + rule-specific extras)."""
    low = (value or "").lower()
    return any(w in low for w in (*_ABSENT_WORDS, *extra))


# --- the 8 predicates -------------------------------------------------------
def _tp03(v: str) -> bool:  # notice period < 5 business days
    n = _first_number(v)
    return n is not None and n < 5


def _tp04(v: str) -> bool:  # LD cap absent, or > 10%
    if _mentions_absent(v):
        return True
    n = _first_number(v)
    return n is not None and n > 10


def _ps01(v: str) -> bool:  # payment assessment period > 20 business days
    n = _first_number(v)
    return n is not None and n > 20


def _ps04(v: str) -> bool:  # retention > 5%, or no release at Practical Completion
    low = (v or "").lower()
    n = _first_number(v)
    if n is not None and n > 5:
        return True
    if "no release" in low or "not released" in low:
        return True
    # "released only at Final Certificate" = not released at Practical Completion → breach. But if PC
    # release IS mentioned, the Final-Certificate reference is the balance, not a breach.
    if ("final certificate" in low or "released at final" in low) and "practical completion" not in low:
        return True
    return False


def _ps05(v: str) -> bool:  # notice before calling security < 5 days, or none
    if _mentions_absent(v):
        return True
    n = _first_number(v)
    return n is not None and n < 5


def _lr01(v: str) -> bool:  # no liability cap present (adequacy of a present cap is human-judged)
    return _mentions_absent(v)


def _lr05(v: str) -> bool:  # cure period < 7 days, or none
    if _mentions_absent(v):
        return True
    n = _first_number(v)
    return n is not None and n < 7


def _sqd05(v: str) -> bool:  # DLP > 12 months
    n = _first_number(v)
    return n is not None and n > 12


# criterion id → predicate. This IS the numeric decision layer.
THRESHOLD_PREDICATES: dict[str, Callable[[str], bool]] = {
    "TP-03": _tp03,
    "TP-04": _tp04,
    "PS-01": _ps01,
    "PS-04": _ps04,
    "PS-05": _ps05,
    "LR-01": _lr01,
    "LR-05": _lr05,
    "SQD-05": _sqd05,
}


def is_threshold_criterion(criterion_id: str) -> bool:
    """True when this criterion is one of the 8 the rule layer can pre-flag."""
    return criterion_id in THRESHOLD_PREDICATES


def evaluate_threshold(criterion_id: str, extracted_value: str) -> bool:
    """Run the deterministic rule for ``criterion_id`` over the extracted value. Returns True when the
    acceptable position is breached (→ ``rule_flagged``). Raises ``KeyError`` if the criterion is not
    a threshold criterion — callers must check :func:`is_threshold_criterion` first."""
    return THRESHOLD_PREDICATES[criterion_id](extracted_value or "")


def known_threshold_ids() -> set[str]:
    """The 8 threshold-criterion ids this module implements — asserted against the criteria file so a
    change to the doc's threshold table is caught rather than silently diverging."""
    return set(THRESHOLD_PREDICATES)
