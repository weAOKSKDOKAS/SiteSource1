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


# ---------------------------------------------------------------------------
# The brief — navy signals, and a brass recommendation over them
# ---------------------------------------------------------------------------
# READ-ONLY, and no model call anywhere. Every signal is a deterministic read of an artifact that
# already exists; the recommendation is a rule over those reads. Nothing is written.
UNKNOWN = "unknown"


def _deadline_signal(conn: sqlite3.Connection, set_id: str) -> dict:
    """Days remaining, or ``"unknown"`` — the SAME honesty rule ``submission.deadline_for`` applies.

    A close date is only KNOWN when the reader found it or a human confirmed it. ``reading`` and
    ``not_found`` both mean "we do not have one", and a deadline we do not have must never become a
    number somebody plans around. That rule already governs whether a submission counts as on time;
    it governs the bid brief for the identical reason.
    """
    from bridge import submission

    date, known = submission.deadline_for(conn, set_id)
    if not known:
        from client_boq import store as cb_store

        status = (cb_store.load_set_meta(conn, set_id).get("close_date_status") or "").strip()
        return {"close_date": UNKNOWN, "days_remaining": UNKNOWN,
                "source": "client_boq_set_meta.close_date",
                "why_unknown": (f"the close date's status is {status or 'unset'!r}; only 'found' "
                                f"or 'confirmed' is trusted. A date nobody read is not a deadline.")}
    try:
        days = (_dt.date.fromisoformat(date[:10]) - _dt.date.fromisoformat(_now()[:10])).days
    except ValueError:
        # A stored date that will not parse is a read failure, not a deadline. Same posture as
        # `_on_time`: degrade to unknown rather than to a plausible number.
        return {"close_date": date, "days_remaining": UNKNOWN,
                "source": "client_boq_set_meta.close_date",
                "why_unknown": f"the stored close date {date!r} is not a date this can read"}
    return {"close_date": date, "days_remaining": days,
            "source": "client_boq_set_meta.close_date (status found/confirmed)"}


def _register_signals(conn: sqlite3.Connection, set_id: str) -> tuple[dict, dict]:
    """``(departures, scope_gaps)`` from the review register — the one place both actually live.

    Scope alignment has no store of its own: s04's findings are assembled INTO the register as
    ``DepartureItem`` rows tagged ``source="scope_alignment"``, with ``kind="input_missing"`` for
    the case where the contract did not give us something we need to price. So both signals are one
    read of one artifact, which is also why neither can drift from what the Register tab shows.
    """
    from client_boq import models as cb_models
    from client_boq import store as cb_store

    register = cb_store.load_register(conn, set_id)
    if register is None:
        return ({"total": 0, "unresolved": 0, "source": "no review register yet"},
                {"gaps": 0, "inputs_missing": 0, "source": "no review register yet"})

    items = register.items
    still_open = {cb_models.STATUS_CANDIDATE, cb_models.STATUS_UNRESOLVED,
                  cb_models.STATUS_UNCOVERED, cb_models.STATUS_CITATION_FAILED,
                  cb_models.STATUS_RULE_FLAGGED}
    scope = [d for d in items if d.source == cb_models.SOURCE_SCOPE_ALIGNMENT]
    departures = {
        "total": len(items),
        # UNRESOLVED means nobody has ruled on it yet — a candidate the human has not judged, a
        # criterion no clause answered, a citation that failed. `confirmed` and `dismissed` are the
        # two a person HAS ruled on, and only the approve endpoint writes them.
        "unresolved": sum(1 for d in items if d.status in still_open),
        "source": "client_boq review register (s07), status vocabulary in client_boq/models.py",
    }
    gaps = {
        "gaps": len(scope),
        "inputs_missing": sum(1 for d in scope if d.kind == "input_missing"),
        "source": "review register lines tagged source='scope_alignment' (s04)",
    }
    return departures, gaps


def _coverage_signal(conn: sqlite3.Connection, set_id: str) -> dict:
    """Which bills have no item-coverage list, and how many items are waiting on one.

    A tender whose coverage lists are missing is a tender whose rates cannot be checked for
    completeness — and under Particular Preamble ¶12/¶4A a head missed out of the item coverage
    cannot be claimed later. That is a bid-brief signal, not a pricing detail.

    ``"unknown"`` until a bill is imported: coverage is per bill item, so with no bill there is
    nothing to have coverage OF. Saying "0 bills without a list" then would be true and useless.
    """
    from client_boq import store as cb_store
    from client_boq.boq import coverage as boq_coverage

    bill = cb_store.load_bill(conn, set_id)
    if bill is None or not bill.items:
        return {"bills_without_list": UNKNOWN, "waiting": UNKNOWN,
                "source": "client_boq/boq/coverage.py::bill_summary",
                "why_unknown": "no bill of quantities is imported yet, so there is nothing to "
                               "have item coverage of"}
    summary = boq_coverage.bill_summary(bill, cb_store.load_coverage_ticks(conn, set_id, bill.rev))
    return {
        "bills_without_list": summary["bills_without_a_list"],
        "waiting": summary["no_list"],
        "partial": summary["partial"],
        "unmatched_clauses": len(summary["unmatched_rules"]),
        "source": "client_boq/boq/coverage.py::bill_summary",
    }


def signals_for(set_id: str) -> dict:
    """Every hard signal behind a bid decision, each naming where it came from. NAVY.

    Deterministic reads of artifacts that already exist. Nothing here is computed for this screen,
    nothing is a score, and anything that cannot be read honestly is the string ``"unknown"``.
    """
    from client_boq import store as cb_store

    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        departures, scope_gaps = _register_signals(conn, ref)
        return {
            "deadline": _deadline_signal(conn, ref),
            "open_clarifications": {
                "count": cb_store.open_rfi_count(conn, ref),
                "source": "client_boq_rfi_items with an open status (store.open_rfi_count)",
            },
            "review_approved": {
                "value": cb_store.review_is_approved(conn, ref),
                "source": "client_boq_review_registers.approved (store.review_is_approved)",
            },
            "departures": departures,
            "scope_gaps": scope_gaps,
            "coverage": _coverage_signal(conn, ref),
        }
    finally:
        conn.close()


def recommend(signals: dict) -> dict:
    """A DETERMINISTIC rule over the signals, with the reasons that drove it. BRASS — a proposal.

    THE RULE, in full, and deliberately small enough to hold in your head:

        any open clarification, scope gap, or missing input  -> clarify   (we cannot price it yet)
        else if the review register is not approved          -> clarify   (never bid on unread terms)
        else                                                 -> bid      (nothing is in the way)

    It NEVER recommends ``no_bid``. Declining a tender is a judgement about workload, relationship,
    risk appetite and what else is in the office that month; none of that is in this database, and
    a machine that proposed it would be guessing at the one decision that is most obviously a
    person's. The rule can say "we cannot price this yet" and it can say "nothing is in the way".
    It cannot say "do not chase this".

    Every reason names the navy signal that produced it, so the UI shows the recommendation's
    evidence beside it rather than asking to be believed. A recommendation with no visible reasons
    is an opinion; one that lists its inputs is an argument somebody can disagree with.

    Coverage and the deadline are reported as signals but do NOT drive the verdict: a missing
    coverage list is a completeness risk to weigh, and a tight deadline is a capacity question —
    both are the estimator's to judge, and neither is a reason a machine should propose pausing.
    """
    reasons: list[str] = []

    clarifications = signals.get("open_clarifications", {}).get("count", 0)
    if clarifications:
        reasons.append(f"{clarifications} clarification(s) still with the client")

    gaps = signals.get("scope_gaps", {})
    if gaps.get("inputs_missing"):
        reasons.append(f"{gaps['inputs_missing']} input(s) the contract did not give us")
    if gaps.get("gaps"):
        reasons.append(f"{gaps['gaps']} scope-alignment finding(s) on the register")

    if reasons:
        return {"verdict": CLARIFY, "reasons": reasons,
                "basis": "open questions or scope gaps — this cannot be priced yet"}

    if not signals.get("review_approved", {}).get("value"):
        return {"verdict": CLARIFY,
                "reasons": ["the review register is not approved"],
                "basis": "never recommend bidding on terms nobody has read — the same posture as "
                         "the review gate"}

    return {"verdict": BID, "reasons": ["nothing on the register is unresolved and the review is "
                                        "approved"],
            "basis": "nothing found that stops this being priced. Whether to pursue it is still "
                     "yours — this rule never proposes no-bid."}


def bid_brief(set_id: str) -> dict:
    """The whole brief: navy signals, a brass recommendation, and the human's decision if any.

    A pure read. Opening this screen records nothing — the machine assembles and proposes, and the
    verdict arrives only through :func:`confirm_bid`.
    """
    signals = signals_for(set_id)
    return {
        "set_id": run_ref_for(set_id),
        "signals": signals,
        "recommendation": recommend(signals),
        "decision": load_bid_decision(set_id),
    }
