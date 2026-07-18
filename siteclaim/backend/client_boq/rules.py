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

Design note (why absence is checked PER RULE, not from one shared word list): "absent" means a
different thing for each rule — an absent LD cap, an absent liability cap, no notice before a
security call, no cure period, no release at PC. A single shared substring list produced false
positives (e.g. an LR-01 value "capped at contract value, unlimited for fraud" tripping on
"unlimited" even though a cap is plainly present) and cross-field bleed (a phrase meant for one
field flagging another). So each rule carries its own tailored keywords and, where relevant, a
presence guard that wins over an absence keyword.

A rule raises the flag; a human still confirms the departure (the verdict is never written here).
"""

from __future__ import annotations

import re
from typing import Callable, Optional

# The first number in a string (percent, days, months — the unit is implied by the rule).
_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")

# Release at Practical Completion, written either in full or as the near-universal "PC" abbreviation
# (\bpc\b so it never matches inside another word). Used by PS-04 so a PC release written "at PC" is
# recognised, not mistaken for "released only at Final Certificate".
_PC_RELEASE_RE = re.compile(r"\bpractical completion\b|\bpc\b", re.IGNORECASE)


def _first_number(value: str) -> Optional[float]:
    """The first numeric token in ``value`` (percent/days/months), or None."""
    m = _NUMBER_RE.search(value or "")
    return float(m.group(1)) if m else None


def _has_any(value: str, words: tuple[str, ...]) -> bool:
    low = (value or "").lower()
    return any(w in low for w in words)


def _released_at_pc(value: str) -> bool:
    """True when the value says retention is released at Practical Completion ('Practical Completion'
    or 'PC')."""
    return bool(_PC_RELEASE_RE.search(value or ""))


# --- the 8 predicates -------------------------------------------------------
def _tp03(v: str) -> bool:  # notice period < 5 business days
    n = _first_number(v)
    return n is not None and n < 5


# LD cap is absent — keywords specific to a liquidated-damages cap (no cross-field bleed).
_TP04_ABSENT = ("uncapped", "no cap", "no aggregate cap", "not capped", "without cap", "unlimited", "no limit")


def _tp04(v: str) -> bool:  # LD cap absent, or > 10%
    n = _first_number(v)
    if n is not None and n > 10:
        return True
    return _has_any(v, _TP04_ABSENT)


def _ps01(v: str) -> bool:  # payment assessment period > 20 business days
    n = _first_number(v)
    return n is not None and n > 20


def _ps04(v: str) -> bool:  # retention > 5%, or no release at Practical Completion
    low = (v or "").lower()
    n = _first_number(v)
    if n is not None and n > 5:
        return True
    if "no release" in low or "not released" in low or "never released" in low:
        return True
    # "released only at Final Certificate" = NOT released at Practical Completion → breach. But if a
    # PC release IS mentioned (in full or as "PC"), a Final-Certificate reference is just the balance.
    if ("final certificate" in low or "released at final" in low) and not _released_at_pc(v):
        return True
    return False


# No notice before a call on security — keywords specific to that field.
_PS05_ABSENT = ("no notice", "without notice", "no prior notice", "immediately", "at any time", "any time without")


def _ps05(v: str) -> bool:  # notice before calling security < 5 days, or none
    n = _first_number(v)
    if n is not None and n < 5:
        return True
    return _has_any(v, _PS05_ABSENT)


# A liability cap is stated as present — these win over an absence keyword (adequacy is human-judged),
# so a present cap with a carve-out ("capped at X, unlimited for fraud") is NOT flagged as absent.
_LR01_PRESENT = ("capped at", "cap of", "limited to", "liability cap of", "maximum liability", "aggregate liability of", "cap is")
_LR01_ABSENT = ("uncapped", "no cap", "no liability cap", "not capped", "no limit on liability", "unlimited liability", "liability is unlimited", "without limit")


def _lr01(v: str) -> bool:  # no liability cap present (adequacy of a present cap is human-judged)
    if _has_any(v, _LR01_PRESENT):
        return False
    return _has_any(v, _LR01_ABSENT)


_LR05_ABSENT = ("no cure", "no cure period", "without cure", "immediate termination", "terminate immediately", "no opportunity to remedy", "no right to remedy")


def _lr05(v: str) -> bool:  # cure period < 7 days, or none
    n = _first_number(v)
    if n is not None and n < 7:
        return True
    return _has_any(v, _LR05_ABSENT)


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
