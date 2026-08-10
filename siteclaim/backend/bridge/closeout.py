"""After the tender goes out: the outcome, the lessons, a light change-control log, and — when we
win — a handover package. The only feedback edge in the whole workflow (nodes 49–53).

Every store here is the same shape as the rest of the bridge: a per-tender record keyed on
``run_ref``, lazy ``CREATE TABLE IF NOT EXISTS``, human provenance, written through ``bridge_conn``.

**The distinction this module exists to keep:** the TENDER OUTCOME is whether *we* won the tender
from the client. It is NOT the sublet award (which subcontractor wins a package — that is
package-level, lives in the procurement recommend flow, and one never writes the other). They are
named apart on purpose; conflating them is the failure this file is written to prevent.

Table names carry the ``bridge_`` prefix to match ``bridge_route_decisions``; the brief wrote
``tender_outcomes`` / ``tender_lessons`` / ``post_submission_events`` and this reconciles them with
the module's real convention.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import Optional

from bridge.identity import bridge_conn, run_ref_for

# The tender's lifecycle after it goes out. `submitted` is the resting state; `won`/`lost` are the
# outcomes that feed the corpus; `withdrawn` is a tender we pulled. A machine never writes these —
# a person records what the client decided.
SUBMITTED = "submitted"
WON = "won"
LOST = "lost"
WITHDRAWN = "withdrawn"
OUTCOME_STATUSES = (SUBMITTED, WON, LOST, WITHDRAWN)
# The two that trigger the corpus feedback loop — a resolved tender, won or lost, is what a future
# tender learns from. `submitted`/`withdrawn` record nothing to the corpus.
CORPUS_OUTCOMES = (WON, LOST)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row["n"])


# ---------------------------------------------------------------------------
# Tender outcome — did WE win the tender (node 49). NOT the sublet award.
# ---------------------------------------------------------------------------
def ensure_outcome_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_tender_outcomes (
            set_id        TEXT PRIMARY KEY,
            status        TEXT NOT NULL,                    -- submitted | won | lost | withdrawn
            outcome_notes TEXT NOT NULL DEFAULT '',         -- award value, competitor, why — human
            decided_by    TEXT NOT NULL DEFAULT 'operator',
            decided_at    TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _outcome_row(row: sqlite3.Row) -> dict:
    return {
        "set_id": row["set_id"], "status": row["status"], "outcome_notes": row["outcome_notes"] or "",
        "decided_by": row["decided_by"] or "operator", "decided_at": row["decided_at"] or "",
    }


def set_outcome(set_id: str, status: str, notes: str = "", *, decided_by: str = "operator") -> dict:
    """Record the tender outcome — THE sole writer of this row. Validates the status, keys on
    ``run_ref``, upserts. A ``won``/``lost`` outcome also feeds the corpus (see
    :func:`feed_outcome_to_corpus`), which the API layer calls after this returns.

    ``outcome_notes`` is the human's — award value, competitor, why we won or lost. The machine
    never drafts it.
    """
    ref = run_ref_for(set_id)
    if status not in OUTCOME_STATUSES:
        raise ValueError(
            f"the outcome must be 'submitted', 'won', 'lost' or 'withdrawn'; got {status!r}")

    conn = bridge_conn()
    try:
        ensure_outcome_table(conn)
        conn.execute(
            """
            INSERT INTO bridge_tender_outcomes (set_id, status, outcome_notes, decided_by, decided_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(set_id) DO UPDATE SET
                status = excluded.status, outcome_notes = excluded.outcome_notes,
                decided_by = excluded.decided_by, decided_at = excluded.decided_at
            """,
            (ref, status, (notes or "").strip(), decided_by, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    return load_outcome(ref) or {}


def load_outcome(set_id: str) -> Optional[dict]:
    """The tender outcome, or ``None`` — a pure read. "Not yet decided" is a state, not an error."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_tender_outcomes"):
            return None
        row = conn.execute(
            "SELECT * FROM bridge_tender_outcomes WHERE set_id = ?", (ref,)).fetchone()
        return _outcome_row(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Lessons learned — human-authored, never model-drafted (node 51)
# ---------------------------------------------------------------------------
# The categories a lesson can be filed under. Free enough to be useful, closed enough that a future
# read can group them; an unrecognised one falls to `other` rather than being refused, because a
# lesson worth writing must never be lost to a taxonomy quibble.
LESSON_CATEGORIES = ("pricing", "scope", "programme", "commercial", "other")


def ensure_lessons_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_tender_lessons (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id     TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT 'other',       -- pricing|scope|programme|commercial|other
            lesson     TEXT NOT NULL,                       -- the human's note; the machine never writes it
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_tender_lessons_set ON bridge_tender_lessons(set_id);
        """
    )
    conn.commit()


def add_lesson(set_id: str, category: str, lesson: str) -> dict:
    """Append one lesson. Human-authored — there is no model path into this table. An empty lesson
    is refused (nothing to record); an unrecognised category is filed as ``other`` rather than
    rejected, because the note is what matters and losing it to a category typo would be the worse
    outcome."""
    ref = run_ref_for(set_id)
    text = (lesson or "").strip()
    if not text:
        raise ValueError("a lesson needs text — an empty note records nothing.")
    cat = (category or "").strip().lower()
    if cat not in LESSON_CATEGORIES:
        cat = "other"

    conn = bridge_conn()
    try:
        ensure_lessons_table(conn)
        cur = conn.execute(
            "INSERT INTO bridge_tender_lessons (set_id, category, lesson, created_at) "
            "VALUES (?, ?, ?, ?)",
            (ref, cat, text, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bridge_tender_lessons WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _lesson_row(row)
    finally:
        conn.close()


def _lesson_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "set_id": row["set_id"], "category": row["category"] or "other",
        "lesson": row["lesson"] or "", "created_at": row["created_at"] or "",
    }


def list_lessons(set_id: str) -> list[dict]:
    """Every lesson for a tender, oldest first — a pure read."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_tender_lessons"):
            return []
        rows = conn.execute(
            "SELECT * FROM bridge_tender_lessons WHERE set_id = ? ORDER BY id", (ref,)).fetchall()
        return [_lesson_row(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Post-submission change-control log — LIGHT (nodes 49–50)
# ---------------------------------------------------------------------------
# A minimal append-only trail of what happened after submission: a clarification asked, a
# negotiation point, a change, a note. DELIBERATELY NOT a re-pricing engine — if a price or a bill
# moved, a human states that in `detail`; the log records the fact, it does not recompute anything.
# Actual client questions still go through the RFI machinery where that already fits; this is the
# tender-level trail beside it.
EVENT_KINDS = ("clarification", "negotiation", "change", "note")


def ensure_events_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_post_submission_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id     TEXT NOT NULL,
            kind       TEXT NOT NULL DEFAULT 'note',        -- clarification|negotiation|change|note
            detail     TEXT NOT NULL,                       -- what changed / was asked — human-stated
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_post_submission_events_set
            ON bridge_post_submission_events(set_id);
        """
    )
    conn.commit()


def log_event(set_id: str, kind: str, detail: str) -> dict:
    """Append one change-control entry. Append-only — nothing here edits or deletes a prior entry,
    because a negotiation trail you can rewrite is not a trail. An unrecognised kind falls to
    ``note``; an empty detail is refused."""
    ref = run_ref_for(set_id)
    text = (detail or "").strip()
    if not text:
        raise ValueError("an event needs a detail — an empty entry records nothing.")
    k = (kind or "").strip().lower()
    if k not in EVENT_KINDS:
        k = "note"

    conn = bridge_conn()
    try:
        ensure_events_table(conn)
        cur = conn.execute(
            "INSERT INTO bridge_post_submission_events (set_id, kind, detail, created_at) "
            "VALUES (?, ?, ?, ?)",
            (ref, k, text, _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM bridge_post_submission_events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _event_row(row)
    finally:
        conn.close()


def _event_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "set_id": row["set_id"], "kind": row["kind"] or "note",
        "detail": row["detail"] or "", "created_at": row["created_at"] or "",
    }


def list_events(set_id: str) -> list[dict]:
    """Every post-submission event for a tender, oldest first — a pure read."""
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        if not _table_exists(conn, "bridge_post_submission_events"):
            return []
        rows = conn.execute(
            "SELECT * FROM bridge_post_submission_events WHERE set_id = ? ORDER BY id", (ref,)
        ).fetchall()
        return [_event_row(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The feedback loop — feed a won/lost outcome into the EXISTING benchmark corpus (nodes 52–53)
# ---------------------------------------------------------------------------
def _corpus_narrative(outcome: dict, lessons: list[dict]) -> str:
    """The EoS-style narrative recorded on the benchmark project: the tender's result and the
    lessons behind it, so a future tender's benchmark read can see how the last job of this shape
    actually went. Human words only — the outcome notes and the lessons, verbatim."""
    lines = [f"# Tender outcome: {outcome['status'].upper()}"]
    if outcome.get("outcome_notes"):
        lines += ["", outcome["outcome_notes"]]
    lines += ["", f"## Lessons learned ({len(lessons)})"]
    if lessons:
        lines += [f"- [{l['category']}] {l['lesson']}" for l in lessons]
    else:
        lines.append("- None recorded.")
    return "\n".join(lines)


def feed_outcome_to_corpus(set_id: str) -> dict:
    """Record a WON/LOST tender's result + lessons into the benchmark corpus — HOOKING INTO the
    existing snapshot machinery, never duplicating it.

    The mechanism the procurement ``/estimate/{id}/to-benchmark`` already established: a tender's
    ``unified_projects`` umbrella row carries a ``benchmark_project_id``. This reuses that link when
    it exists (the estimate may already have been captured), and otherwise creates one benchmark
    project for the tender and links it. The outcome + lessons are recorded in the project's OWN
    outcome slot via :func:`db.benchmark.attach_project_outcome`, which REPLACES one-per-project —
    so re-setting an outcome records once, never twice.

    That slot is DELIBERATELY separate from ``project_eos`` (the operator's End-of-Site document):
    one project can carry both, so routing the outcome through ``attach_eos`` silently clobbered a
    real EoS upload and made ``get_eos`` return the wrong kind. See the crossing test in
    ``db/tests/test_benchmark_eos.py``.

    **Append-only across the corpus.** It touches only this tender's own umbrella row, its own
    benchmark project, and that project's outcome slot. It never deletes a project, never withdraws
    a prior entry, and never mutates another project's rows — a lost tender does not un-record a
    previously won one. ``submitted``/``withdrawn`` feed nothing; only ``won``/``lost`` reach here.

    Returns ``{"fed": bool, "benchmark_project_id": int|None, "reason": str}``. Not fed is a STATE
    (no resolved outcome yet), not an error.
    """
    from db import benchmark as bench
    from db import project as uproject
    from pipeline.llm_client import demo_mode

    from bridge.identity import set_name

    ref = run_ref_for(set_id)
    outcome = load_outcome(ref)
    if outcome is None or outcome["status"] not in CORPUS_OUTCOMES:
        return {"fed": False, "benchmark_project_id": None,
                "reason": "no won/lost outcome to record"}

    lessons = list_lessons(ref)
    provenance = "demo" if demo_mode() else "live"

    conn = bridge_conn()
    try:
        name = set_name(conn, ref) or ref
        up = uproject.get_or_create(conn, ref, name=name, provenance=provenance)
        pid = up.get("benchmark_project_id")
        # Reuse the estimate's captured project when it exists; otherwise create ONE for the tender.
        if not (pid and bench.get_project(conn, pid)):
            created = bench.create_project(
                conn, name=name, source="tender-outcome", provenance=provenance,
                notes=f"Tender outcome captured for {ref}.")
            pid = created["id"]
            uproject.link_benchmark(conn, ref, pid)
        # Idempotent replace of THIS tender's own outcome — into its OWN corpus slot
        # (project_outcomes), NEVER project_eos. That slot is the operator's End-of-Site document,
        # and one project can carry both: routing the outcome through attach_eos silently DELETEd a
        # real EoS upload (and vice versa), and get_eos then surfaced the wrong kind — including
        # into the variance reason-suggestion path. attach_project_outcome keeps them apart.
        bench.attach_project_outcome(
            conn, pid, status=outcome["status"], narrative=_corpus_narrative(outcome, lessons),
            source_doc="tender-outcome", provenance=provenance)
        return {"fed": True, "benchmark_project_id": pid, "reason": ""}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Handover package — assemble from existing artifacts, never re-enter (node 53)
# ---------------------------------------------------------------------------
def closeout_state(set_id: str) -> dict:
    """The Closeout tab's one read: outcome + lessons + events + whether a handover is meaningful.

    ``handover_ready`` is ``status == 'won'`` — a handover package is what you assemble for a job
    you are about to run, and there is nothing to hand over on a tender that lost.
    """
    ref = run_ref_for(set_id)
    outcome = load_outcome(ref)
    return {
        "set_id": ref,
        "outcome": outcome,
        "lessons": list_lessons(ref),
        "events": list_events(ref),
        "handover_ready": bool(outcome and outcome["status"] == WON),
    }


def assemble_handover(set_id: str) -> dict:
    """A READ-ONLY projection of everything a won tender hands to the delivery team — assembled from
    artifacts that already exist, never re-typed.

    Nothing here is authored: the scope of record, the confirmed bill parts, the review register's
    CONFIRMED positions, the priced estimate baseline, the sublet route decisions, and the approval
    + submission record are all read back and laid out. A piece that is absent is NAMED in
    ``missing`` — the "nothing leaves quietly" rule — rather than dropped, because a handover that
    silently omits the estimate looks complete and is not.

    ``ready`` is ``status == 'won'``. Before that the projection still assembles (it is useful to
    preview), but ``ready`` is false and ``pending`` says what the tender is still waiting for.
    """
    from client_boq import store as cb_store

    from bridge import decisions, parts as parts_mod, submission
    from bridge.identity import set_name

    ref = run_ref_for(set_id)
    outcome = load_outcome(ref)
    ready = bool(outcome and outcome["status"] == WON)

    conn = bridge_conn()
    try:
        name = set_name(conn, ref) or ref
        scope_items = cb_store.load_scope_items(conn, ref)
        register = cb_store.load_register(conn, ref)
        estimate = cb_store.load_estimate(conn, ref)
        letter = cb_store.load_letter(conn, ref)
        bill_parts = parts_mod.confirmed_bill_parts(conn, ref)
    finally:
        conn.close()

    decision_state = decisions.stored_decisions(ref)
    sublet = decision_state.get("sublet_packages", [])
    self_perform = decision_state.get("self_perform_packages", [])
    approval = submission.load_final_approval(ref)
    submitted = submission.load_submission(ref)
    confirmed_positions = (
        [it for it in register.items if it.status == "confirmed"] if register else [])

    missing: list[str] = []
    if not bill_parts:
        missing.append("confirmed bill part(s) — no bill was confirmed for this tender")
    if not scope_items:
        missing.append("scope of record — the Scope tab has no frozen lines")
    if estimate is None:
        missing.append("priced estimate baseline — the estimate has not been run")
    if register is None:
        missing.append("review register — the review never ran, so there are no confirmed positions")
    if submitted is None:
        missing.append("submission record — this tender was not recorded as submitted")

    sections = {
        "tender": {"name": name, "status": (outcome or {}).get("status", "no outcome recorded"),
                   "outcome_notes": (outcome or {}).get("outcome_notes", "")},
        "approval": approval,
        "submission": submitted,
        "price": {"price": letter.price if letter else None,
                  "price_str": letter.price_str if letter else ""},
        "estimate_totals": estimate.totals.model_dump() if estimate else None,
        "bill_parts": bill_parts,
        "scope_of_record": [
            {"section": s.section, "title": s.title, "text": s.text, "badge": s.badge}
            for s in scope_items],
        "confirmed_positions": [
            {"clause": p.clause, "criterion_id": p.criterion_id,
             "position": p.proposed_position or p.rationale} for p in confirmed_positions],
        "sublet_packages": sublet,
        "self_perform_packages": self_perform,
        "lessons": list_lessons(ref),
        "events": list_events(ref),
    }

    return {
        "set_id": ref,
        "name": name,
        "ready": ready,
        "status": (outcome or {}).get("status", "no outcome recorded"),
        "pending": "" if ready else (
            "This tender is not marked 'won' — a handover is a projection for a job about to run, "
            "so this is a preview. Record the outcome as 'won' on the Closeout tab."),
        "missing": missing,
        "sections": sections,
        "markdown": _handover_markdown(sections, ready, missing),
    }


def _handover_markdown(s: dict, ready: bool, missing: list[str]) -> str:
    """Render the handover projection as Markdown — the chosen deliverable format, consistent with
    the letter of offer. A pure function of what was assembled; it authors nothing."""
    from schemas.routing import SELF_PERFORM, SUBLET  # noqa: F401  (labels align with the store)

    t = s["tender"]
    out = [f"# Handover — {t['name']}", "", f"**Tender outcome:** {t['status']}"]
    if not ready:
        out += ["", "> PREVIEW — this tender is not marked 'won'. Nothing here is final."]
    if t["outcome_notes"]:
        out += ["", t["outcome_notes"]]

    if missing:
        out += ["", "## Not yet available", *[f"- {m}" for m in missing]]

    sub = s["submission"]
    if sub:
        on_time = ("on time" if sub["on_time"] == 1 else "after the deadline"
                   if sub["on_time"] == 0 else "deadline unknown")
        out += ["", "## Submission",
                f"- Submitted {sub['submitted_at']} by {sub['submitted_by']} ({on_time})",
                f"- Approved: {sub['approval_ref'] or '—'}",
                f"- Proof: {sub['proof'] or '—'}"]

    price = s["price"]
    if price["price"] is not None:
        out += ["", "## Price", f"- Tendered price: {price['price_str'] or price['price']}"]
    tot = s["estimate_totals"]
    if tot:
        out += [f"- Cost baseline: direct {tot['total_direct']}, indirect {tot['total_indirect']}, "
                f"total cost {tot['total_cost']}, margin {tot['margin_pct']}%"]

    if s["bill_parts"]:
        out += ["", "## Confirmed bill part(s)", *[f"- {p}" for p in s["bill_parts"]]]

    if s["scope_of_record"]:
        out += ["", "## Scope of record"]
        for line in s["scope_of_record"]:
            tag = "✎" if line["badge"] == "user" else "·"
            out.append(f"- {tag} **{line['title'] or line['section']}** — {line['text']}")

    if s["confirmed_positions"]:
        out += ["", "## Confirmed contractual positions (from the review register)"]
        for p in s["confirmed_positions"]:
            out.append(f"- **{p['clause'] or p['criterion_id']}** — {p['position']}")

    if s["sublet_packages"] or s["self_perform_packages"]:
        out += ["", "## Package routing"]
        if s["self_perform_packages"]:
            out.append(f"- Self-perform: {', '.join(s['self_perform_packages'])}")
        if s["sublet_packages"]:
            out.append(f"- Sublet (award per package downstream): {', '.join(s['sublet_packages'])}")

    if s["lessons"]:
        out += ["", "## Lessons learned", *[f"- [{l['category']}] {l['lesson']}" for l in s["lessons"]]]
    if s["events"]:
        out += ["", "## Post-submission change-control",
                *[f"- ({e['kind']}) {e['detail']}" for e in s["events"]]]

    return "\n".join(out) + "\n"
