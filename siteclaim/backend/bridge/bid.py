"""The FIRST decision: do we pursue this tender at all? — decision + record, and a brief.

Beside ``bridge/submission.py`` and ``bridge/closeout.py``, in the same family and the same shape:
a per-tender human verdict keyed on ``run_ref``, lazy DDL, ``decided_by``/``decided_at`` provenance,
validated before it is written. It goes here rather than in a module of its own because it IS that
pattern for the fourth time — the store is thirty lines, and a new subsystem for a thirty-line store
would be the wrong answer to the same question three files have already answered.

WHERE IT SITS. After the contract review (Register) and before Route. The system used to assume
every tender was pursued: routing, sourcing and pricing all began without anybody recording that
the decision to bid had been made. That is not a missing screen — it is a missing decision, and the
estimator's earliest real one.

THE AUTHORSHIP MODEL, and it is the whole design:

* **navy — the signals.** Deterministic reads of artifacts that already exist: the review's approval
  flag, the register's own line counts, the close date, the open questions, the coverage lists.
  Nothing here is computed for this purpose; every one names where it came from.
* **brass — the recommendation.** A DETERMINISTIC RULE over those signals (:func:`recommend`), shown
  with the reasons that drove it, and freely overridable. It is a proposal, not a finding.
* **the verdict is the human's.** :func:`confirm_bid` is the sole writer, called only from the
  confirm endpoint. Nothing in this module records a decision on anybody's behalf.

WHAT THIS MODULE WILL NOT DO, and the refusal is the point
----------------------------------------------------------
It does not compute a win probability, a capacity score, or a strategic-fit score. Those are the
three numbers a bid/no-bid screen most wants to show and the three this machine has no basis for.
A fabricated figure that looks like a fact is exactly the failure class the rest of this product is
built to kill — it would arrive in the same typeface as the deterministic counts beside it, and it
would be believed. They are **human-entered**, carried in ``factors_json`` as the operator's own
words, and a signal nobody can read is the string ``"unknown"`` rather than a placeholder number.

AND THE RULE NEVER RECOMMENDS ``no_bid``. "Do not pursue this" is a business judgement about
workload, relationship, risk appetite and what else is in the office that month. None of that is in
this database. The rule can say "we cannot price this yet" (``clarify``) and it can say "nothing is
in the way" (``bid``); the decision not to chase a job is the human's alone, and there is no code
path here that proposes it.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Optional

from bridge.identity import bridge_conn, run_ref_for

# The three verdicts. `clarify` is not indecision — it is "we have questions the client must answer
# before we can price this", which is a real position with a real next action (the RFI letter).
BID = "bid"
NO_BID = "no_bid"
CLARIFY = "clarify"
BID_VERDICTS = (BID, NO_BID, CLARIFY)

# The two that must say why. A `bid` needs no rationale — proceeding is the default posture and the
# brief already records what was in the way. Declining or pausing a tender is a decision somebody
# will be asked about in three months, and "no_bid" with no reason is not a decision anybody can
# act on or defend. Same rule, same words, as `submission.confirm_final_approval`'s `revise`.
_RATIONALE_REQUIRED = (NO_BID, CLARIFY)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row["n"])


# ---------------------------------------------------------------------------
# The store — one verdict per tender
# ---------------------------------------------------------------------------
def ensure_bid_table(conn: sqlite3.Connection) -> None:
    """Create ``bridge_bid_decisions`` if absent (lazy DDL, idempotent).

    ``set_id`` is the PRIMARY KEY: one bid decision per tender, re-deciding updates in place. A
    tender that was marked ``clarify`` and later becomes a ``bid`` is the same decision revisited,
    not two decisions — and the ``decided_at`` moves with it so the record is of the position now
    held rather than the first one taken.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_bid_decisions (
            set_id       TEXT PRIMARY KEY,
            verdict      TEXT NOT NULL,                    -- 'bid' | 'no_bid' | 'clarify'
            rationale    TEXT NOT NULL DEFAULT '',         -- REQUIRED for 'no_bid' and 'clarify'
            factors_json TEXT NOT NULL DEFAULT '{}',       -- the HUMAN's strategic factors
            decided_by   TEXT NOT NULL DEFAULT 'operator',
            decided_at   TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _decision_row(row: sqlite3.Row) -> dict:
    try:
        factors = json.loads(row["factors_json"] or "{}")
    except (TypeError, ValueError):
        # A factors blob that will not parse is the operator's own words, damaged. It is reported
        # rather than dropped: losing somebody's stated reasoning silently is worse than showing
        # that it is unreadable.
        factors = {"_unreadable": row["factors_json"]}
    return {
        "set_id": row["set_id"], "verdict": row["verdict"],
        "rationale": row["rationale"] or "", "factors": factors,
        "decided_by": row["decided_by"] or "operator", "decided_at": row["decided_at"] or "",
    }


def confirm_bid(set_id: str, verdict: str, rationale: str = "",
                factors: Optional[dict] = None, *, decided_by: str = "operator") -> dict:
    """Record the human's bid/no-bid verdict. THE sole writer of this row.

    Mirrors ``submission.confirm_final_approval``: validates before it writes, keys on
    ``run_ref_for`` at the boundary, upserts, stamps who and when. ``factors`` is the operator's own
    strategic judgement (fit, capacity, win probability, notes) and is stored verbatim — nothing in
    this module computes, checks or fills any of it.
    """
    ref = run_ref_for(set_id)
    if verdict not in BID_VERDICTS:
        raise ValueError(f"verdict must be one of {list(BID_VERDICTS)}; got {verdict!r}")
    text = (rationale or "").strip()
    if verdict in _RATIONALE_REQUIRED and not text:
        raise ValueError(
            f"a {verdict!r} verdict must say why — rationale is required. Somebody will be asked "
            f"about this decision months from now, and a verdict with no reason is not one they "
            f"can defend."
        )

    conn = bridge_conn()
    try:
        ensure_bid_table(conn)
        conn.execute(
            """
            INSERT INTO bridge_bid_decisions
                (set_id, verdict, rationale, factors_json, decided_by, decided_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(set_id) DO UPDATE SET
                verdict = excluded.verdict, rationale = excluded.rationale,
                factors_json = excluded.factors_json,
                decided_by = excluded.decided_by, decided_at = excluded.decided_at
            """,
            (ref, verdict, text, json.dumps(factors or {}), decided_by, _now()),
        )
        conn.commit()
        return load_bid_decision(ref) or {}
    finally:
        conn.close()


def load_bid_decision(set_id: str) -> Optional[dict]:
    """The persisted verdict for a tender, or ``None`` — a pure read. "Not yet decided" is a STATE,
    not an error, and it is the state every tender starts in."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_bid_decisions"):
            return None
        row = conn.execute(
            "SELECT * FROM bridge_bid_decisions WHERE set_id = ?", (ref,)).fetchone()
        return _decision_row(row) if row else None
    finally:
        conn.close()
