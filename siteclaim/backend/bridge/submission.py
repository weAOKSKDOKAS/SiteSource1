"""The back of the tender funnel: final approval, then submission — decision + record.

Two stores, both beside ``bridge/decisions.py`` and both the same shape as ``bridge_route_decisions``:
a per-tender human decision keyed on ``run_ref``, lazy DDL, ``decided_by``/``decided_at`` provenance.

* ``bridge_final_approvals`` — the last human gate before the tender goes out: ``approve`` or
  ``revise``. A ``revise`` MUST say what to correct (node 47). The machine never writes this row;
  the operator does, through the confirm endpoint, exactly as a route decision is recorded.
* ``bridge_tender_submissions`` — the act of submitting. It FREEZES the offer letter at the moment
  it goes out (an immutable snapshot, so a later letter edit never rewrites what was submitted),
  records the proof the operator supplies, and refuses outright unless an ``approve`` exists. You
  cannot submit a tender nobody approved — a hard precondition, not a soft warning.

What this does NOT do: it does not build the letter (``estimate/s06_offer.py`` owns that, and is
off-limits), does not send anything, and does not invent a deadline or a proof. An unknown deadline
makes ``on_time`` NULL, shown as "deadline unknown" — never a fabricated pass.

Table names carry the ``bridge_`` prefix to match ``bridge_route_decisions``; the brief wrote
``tender_submissions`` and this reconciles it with the module's real convention.
"""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from typing import Optional

from bridge.identity import bridge_conn, run_ref_for

# The two verdicts a final approval can carry. `revise` is not a rejection of the tender — it is a
# note that something must be corrected before it goes out (node 47), so it REQUIRES a rationale.
APPROVE = "approve"
REVISE = "revise"
FINAL_VERDICTS = (APPROVE, REVISE)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row["n"])


# ---------------------------------------------------------------------------
# Final approval — the last human gate before submission (node 46/47)
# ---------------------------------------------------------------------------
def ensure_final_approval_table(conn: sqlite3.Connection) -> None:
    """Create ``bridge_final_approvals`` if absent (lazy DDL, idempotent).

    ``set_id`` is the PRIMARY KEY: one final verdict per tender, re-deciding updates in place — the
    same idempotence ``bridge_route_decisions`` gets from its UNIQUE constraint, here at tender
    granularity because there is exactly one tender to approve.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_final_approvals (
            set_id      TEXT PRIMARY KEY,
            verdict     TEXT NOT NULL,                       -- 'approve' | 'revise'
            rationale   TEXT NOT NULL DEFAULT '',            -- REQUIRED for 'revise' (what to correct)
            approved_by TEXT NOT NULL DEFAULT 'operator',
            approved_at TEXT NOT NULL,
            -- WHAT THE ARITHMETIC SAID AT THE MOMENT SOMEBODY SIGNED. Frozen, not looked up: the
            -- model moves after an approval, and "was this tender conserved when it was approved"
            -- must not become "is it conserved now".
            conservation TEXT NOT NULL DEFAULT ''
        );
        """
    )
    _add_column(conn, "bridge_final_approvals", "conservation", "TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _add_column(conn: sqlite3.Connection, table: str, column: str, spec: str) -> None:
    """Add a column to a table that already exists. Idempotent, applied by shape.

    ``CREATE TABLE IF NOT EXISTS`` never alters an existing table and this repo has no migration
    framework, so a database created before a column has to be brought forward here. Additive only,
    and with a DEFAULT: a row written before the column existed must read back as something honest.
    """
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if existing and column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {spec}")


def _approval_row(row: sqlite3.Row) -> dict:
    return {
        "set_id": row["set_id"], "verdict": row["verdict"], "rationale": row["rationale"] or "",
        "approved_by": row["approved_by"] or "operator", "approved_at": row["approved_at"] or "",
        # What the conservation check said when this verdict was given. Empty on a verdict recorded
        # before the column existed, or one where the costing could not be built — and the sentence
        # itself says which, because "" and "it was clean" must never be the same reading.
        "conservation": (row["conservation"] if "conservation" in row.keys() else "") or "",
    }


def confirm_final_approval(set_id: str, verdict: str, rationale: str = "", *,
                           approved_by: str = "operator") -> dict:
    """Record the human's final verdict on the whole tender. THE sole writer of this row.

    Mirrors ``decisions.confirm_routes``: validates before it writes, keys on ``run_ref_for`` at the
    boundary, upserts (re-deciding replaces), stamps who and when. ``revise`` without a rationale is
    refused — node 47 is "what to correct", and a revise verdict that says nothing to correct is not
    a decision anybody can act on.

    IT ALSO FREEZES THE CONSERVATION VERDICT, and does not block on it. That is a decision, so it is
    stated: an unconserved model **warns and is recorded, it does not refuse**. A basis nothing
    claims may genuinely not be required by this contract, and refusing a correct tender because
    arithmetic cannot tell which is the case would make the product wrong more often than the
    estimator is. But the failure this closes is that a HK$3,038,117 leak reached a screen reporting
    `unpriced: []` and `placeholders: []` — everything priced, nothing missing, a third of the cost
    gone. So the verdict is put in front of the person signing and frozen ON the signature: an
    approval given over an unconserved model becomes a fact on the record instead of a memory.

    Frozen rather than looked up, for the same reason the letter is: the model moves after an
    approval, and *was this tender conserved when it was approved* must not silently become *is it
    conserved now*.
    """
    ref = run_ref_for(set_id)
    if verdict not in FINAL_VERDICTS:
        raise ValueError(f"the verdict must be 'approve' or 'revise'; got {verdict!r}")
    text = (rationale or "").strip()
    if verdict == REVISE and not text:
        raise ValueError("a 'revise' verdict must say what to correct — rationale is required.")

    conn = bridge_conn()
    try:
        ensure_final_approval_table(conn)
        conn.execute(
            """
            INSERT INTO bridge_final_approvals
                (set_id, verdict, rationale, approved_by, approved_at, conservation)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(set_id) DO UPDATE SET
                verdict = excluded.verdict, rationale = excluded.rationale,
                approved_by = excluded.approved_by, approved_at = excluded.approved_at,
                conservation = excluded.conservation
            """,
            (ref, verdict, text, approved_by, _now(), conservation_sentence(ref)),
        )
        conn.commit()
        return load_final_approval(ref) or {}
    finally:
        conn.close()


def conservation_sentence(set_id: str) -> str:
    """One line saying whether this tender's cost is recovered exactly once. Never raises.

    Reads the single owner of that verdict (``client_boq.router.conservation_state``) rather than
    re-deriving it: three implementations of one law is how two of them come to disagree. A check
    that could not run says so — it is a different state from one that ran and came out clean, and
    this string is going onto a signature.
    """
    try:
        from client_boq.router import conservation_state

        state = conservation_state(set_id)
    except Exception as exc:  # noqa: BLE001 — an approval must never fail on a read-only check
        return f"the conservation check could not be run ({exc})"
    if not state.get("checked"):
        return (f"the conservation check could not be run: "
                f"{state.get('not_checked_because') or 'no reason given'}")
    return state.get("headline", "")


def load_final_approval(set_id: str) -> Optional[dict]:
    """The persisted final verdict for a tender, or ``None`` — a pure read. "Not yet decided" is a
    STATE, not an error."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_final_approvals"):
            return None
        row = conn.execute(
            "SELECT * FROM bridge_final_approvals WHERE set_id = ?", (ref,)).fetchone()
        return _approval_row(row) if row else None
    finally:
        conn.close()


def is_approved(set_id: str) -> bool:
    """True when the tender carries an ``approve`` final verdict — the submission precondition."""
    approval = load_final_approval(set_id)
    return bool(approval and approval["verdict"] == APPROVE)


# ---------------------------------------------------------------------------
# Submission — freeze the final version + record the proof (node 48)
# ---------------------------------------------------------------------------
class NotApproved(RuntimeError):
    """The tender has no ``approve`` final verdict, so it cannot be submitted — a HARD precondition.

    Distinct from ``decisions.ReviewNotApproved`` (the soft review gate): this one never softens.
    A tender that goes out the door without a final sign-off is precisely what this gate exists to
    make impossible, so there is no ``REVIEW_GATE=soft`` equivalent here.
    """


def ensure_submission_table(conn: sqlite3.Connection) -> None:
    """Create ``bridge_tender_submissions`` if absent (lazy DDL, idempotent). ``set_id`` PK: one
    submission of record per tender."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_tender_submissions (
            set_id          TEXT PRIMARY KEY,
            submitted_at    TEXT NOT NULL,
            deadline        TEXT NOT NULL DEFAULT '',        -- from set meta; '' when none parsed
            on_time         INTEGER,                          -- 1/0/NULL(unknown deadline)
            letter_snapshot TEXT NOT NULL DEFAULT '{}',       -- FROZEN LetterOfOffer JSON, immutable
            price_snapshot  REAL,                             -- the price at submission (from the letter)
            price_str       TEXT NOT NULL DEFAULT '',
            approval_ref    TEXT NOT NULL DEFAULT '',         -- who/when authorised (from the approval row)
            proof           TEXT NOT NULL DEFAULT '',         -- operator-supplied; never fabricated
            submitted_by    TEXT NOT NULL DEFAULT 'operator'
        );
        """
    )
    conn.commit()


def deadline_for(conn: sqlite3.Connection, set_id: str) -> tuple[str, bool]:
    """``(deadline, known)`` from the client_boq set meta.

    The deadline is the tender's close date (``client_boq/ingest/close_date.py`` writes it), and it
    is only KNOWN when a human confirmed it or the reader found it — ``reading`` / ``not_found``
    both mean "we do not have one", and an empty string means the same. A deadline we do not have
    must never become a fabricated on-time pass; the caller turns ``known=False`` into ``on_time``
    NULL, shown as "deadline unknown".
    """
    from client_boq import store as cb_store

    meta = cb_store.load_set_meta(conn, set_id)
    date = (meta.get("close_date") or "").strip()
    known = bool(date) and (meta.get("close_date_status") in {"found", "confirmed"})
    return (date if known else ""), known


def _on_time(submitted_at: str, deadline: str, known: bool) -> Optional[int]:
    """1 when submitted on or before the deadline, 0 when after, ``None`` when the deadline is
    unknown. ISO strings compare lexicographically in UTC, which is how ``_now`` and the close-date
    parser both write them; a malformed either-side degrades to unknown rather than a false pass."""
    if not known or not deadline:
        return None
    try:
        # Compare on the DATE the tender is due against the date it went out — a close date is a
        # day ("30 September 2026"), not a clock time, so comparing timestamps would call a 9am
        # submission "late" against a same-day deadline stored as midnight.
        return 1 if submitted_at[:10] <= deadline[:10] else 0
    except (TypeError, IndexError):
        return None


def _submission_row(row: sqlite3.Row) -> dict:
    return {
        "set_id": row["set_id"], "submitted_at": row["submitted_at"],
        "deadline": row["deadline"] or "", "on_time": row["on_time"],
        "letter_snapshot": json.loads(row["letter_snapshot"] or "{}"),
        "price_snapshot": row["price_snapshot"], "price_str": row["price_str"] or "",
        "approval_ref": row["approval_ref"] or "", "proof": row["proof"] or "",
        "submitted_by": row["submitted_by"] or "operator",
    }


def record_submission(set_id: str, *, proof: str = "", submitted_by: str = "operator") -> dict:
    """Freeze the offer at the moment it goes out and record the proof. THE writer of this row.

    Three things, in order:

    1. **Refuses unless a final ``approve`` exists.** A hard precondition — you cannot submit an
       unapproved tender — raised as :class:`NotApproved`, never softened.
    2. **Freezes the current ``LetterOfOffer``** into ``letter_snapshot`` + ``price_snapshot``. The
       snapshot is immutable: a later letter edit re-runs the estimate and rewrites
       ``client_boq_letters``, but this row is what was actually submitted and must not move with
       it. That is the whole reason it is a copy and not a foreign key.
    3. **Computes ``on_time``** against the tender's deadline, NULL when the deadline is unknown.

    ``proof`` is stored verbatim — a portal reference, a filename, whatever the operator supplies —
    and is never invented. Re-submitting replaces (upsert), which is the honest model of a
    corrected re-submission before the deadline; the frozen letter is re-frozen from the current
    one at that later moment, which is correct because that later letter is what went out.
    """
    ref = run_ref_for(set_id)

    if not is_approved(ref):
        raise NotApproved(
            "This tender has no final approval yet — record it in the approval panel on the "
            "Offer screen, just above Submit. A tender cannot go out unapproved."
        )

    conn = bridge_conn()
    try:
        from client_boq import store as cb_store

        letter = cb_store.load_letter(conn, ref)
        if letter is None:
            raise NotApproved(
                "This tender is approved but has no offer letter to submit — run the estimate "
                "on the Price tab first; it assembles the letter of offer."
            )
        approval = conn.execute(
            "SELECT approved_by, approved_at FROM bridge_final_approvals WHERE set_id = ?", (ref,)
        ).fetchone()
        approval_ref = (f"{approval['approved_by']} @ {approval['approved_at']}"
                        if approval else "")

        deadline, known = deadline_for(conn, ref)
        submitted_at = _now()
        on_time = _on_time(submitted_at, deadline, known)

        ensure_submission_table(conn)
        conn.execute(
            """
            INSERT INTO bridge_tender_submissions
                (set_id, submitted_at, deadline, on_time, letter_snapshot, price_snapshot,
                 price_str, approval_ref, proof, submitted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(set_id) DO UPDATE SET
                submitted_at = excluded.submitted_at, deadline = excluded.deadline,
                on_time = excluded.on_time, letter_snapshot = excluded.letter_snapshot,
                price_snapshot = excluded.price_snapshot, price_str = excluded.price_str,
                approval_ref = excluded.approval_ref, proof = excluded.proof,
                submitted_by = excluded.submitted_by
            """,
            (ref, submitted_at, deadline, on_time, letter.model_dump_json(), letter.price,
             letter.price_str, approval_ref, (proof or "").strip(), submitted_by),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bridge_tender_submissions WHERE set_id = ?", (ref,)).fetchone()
        return _submission_row(row)
    finally:
        conn.close()


def load_submission(set_id: str) -> Optional[dict]:
    """The submission record for a tender, or ``None`` — a pure read. The frozen snapshot inside it
    is what went out, whatever the live letter says now."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_tender_submissions"):
            return None
        row = conn.execute(
            "SELECT * FROM bridge_tender_submissions WHERE set_id = ?", (ref,)).fetchone()
        return _submission_row(row) if row else None
    finally:
        conn.close()


def is_submitted(set_id: str) -> bool:
    return load_submission(set_id) is not None


def submission_state(set_id: str) -> dict:
    """Everything the Offer/Submit surface reads in one call — approval, submission, deadline, and
    whether a letter exists to submit. A pure read; the step chip and the panel share it.

    ``letter_ready`` is the deterministic precondition the UI shows before approval is even offered:
    there is nothing to approve until the estimate has assembled a letter of offer.
    """
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        from client_boq import store as cb_store

        letter = cb_store.load_letter(conn, ref)
        deadline, known = deadline_for(conn, ref)
    finally:
        conn.close()
    return {
        "set_id": ref,
        "approval": load_final_approval(ref),
        "submission": load_submission(ref),
        "deadline": deadline,
        "deadline_known": known,
        "letter_ready": letter is not None,
        # THE LIVE CONSERVATION VERDICT, beside the frozen one on the approval. Both, deliberately:
        # the frozen one says what was true when somebody signed, this one says what is true now,
        # and a model edited after approval is exactly the case where those differ and somebody
        # needs to see that they do. It warns; it never blocks — see `confirm_final_approval`.
        "conservation": conservation_sentence(ref),
    }
