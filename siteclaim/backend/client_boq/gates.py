"""How hard the review→downstream gate bites. Read from the environment, decided per deployment.

**THIS IS A DELIBERATE V1 DEPARTURE FROM A LOCKED DECISION.** The locked decision is that the
review register must be human-approved before routing or pricing may run, enforced as a 409 — the
reasoning being that you cannot sensibly choose self-perform vs sublet, or put a price on a job,
without knowing what the contract makes you responsible for. That reasoning has not changed and
the enforcement is not deleted: ``REVIEW_GATE=hard`` restores it byte-for-byte.

What changed is the DEFAULT, and only for V1 demo purposes. Approving a register on a real tender
pack means working through every finding, and a demo that cannot show the routing or the estimate
until that is done cannot show them at all. So the default became ``soft``: downstream steps run,
and every one of them says loudly that it is running on terms nobody has read.

The line this holds: soft does not mean silent. A gate that stops being a gate and says nothing is
worse than no gate at all, because the absence of a warning reads as approval. Every soft-mode
bypass carries :data:`SOFT_GATE_WARNING` on the response or the job, and the UI renders it in
amber. Nothing is approved, nothing is inferred, and the register still says exactly what it said.

Why not ``client_boq/rules.py``: that module is the eight deterministic THRESHOLD rules for review
s03 — pure numeric predicates over strings the model extracted, one per row of the criteria table's
threshold section. A deployment-mode switch read from the environment is not a threshold rule and
would be the only thing in there that touched ``os.getenv``. It lives here instead.
"""

from __future__ import annotations

import os

# The one sentence every soft-mode bypass says, verbatim, wherever it surfaces. One string so the
# operator sees the same words on the Route tab, on an estimate job, and in a log — three different
# phrasings of one condition would read as three different conditions.
SOFT_GATE_WARNING = (
    "Review register not approved — routing/pricing is proceeding on UNREAD contract terms "
    "(REVIEW_GATE=soft)."
)

_HARD = "hard"
_SOFT = "soft"


def review_gate_mode() -> str:
    """``'soft'`` (default, V1) or ``'hard'``.

    ``'soft'``: an unapproved review register does not block downstream steps — it warns.
    ``'hard'``: the original behaviour, a 409 until the register is approved.

    Read dynamically from ``REVIEW_GATE`` so tests can toggle it, the same pattern as
    ``demo_mode()``. Case-insensitive. Anything unrecognised is ``'soft'`` — this is the V1 default
    and an unreadable setting must not silently produce the stricter behaviour, because a demo that
    409s for a reason nobody typed is the harder failure to diagnose. The warning fires either way,
    so the unrecognised case is loud rather than quiet.
    """
    return _HARD if os.getenv("REVIEW_GATE", "").strip().lower() == _HARD else _SOFT


def review_gate_is_soft() -> bool:
    """Convenience for the call sites, which all ask the same yes/no question."""
    return review_gate_mode() == _SOFT
