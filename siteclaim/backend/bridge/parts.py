"""Selecting the bill part(s) from a client_boq set — a human gate, never automatic.

``PartSpec.category`` is written by an AI interpretation stage. Letting it silently decide which
document produces every priced row in a tender is exactly the class of thing this codebase gates,
so the bridge PROPOSES and a human CONFIRMS.

The confirmation is a **set** of part ids, not one: a real tender can carry a bill of quantities
AND a separate daywork or provisional-items schedule, and both are priceable (``PART_CATEGORIES``
defines ``pricing`` as "bills of quantities, schedules of rates, fee proposals" — a family). Every
confirmed part yields items; every unconfirmed part — including a ``pricing`` part the human left
out — becomes context only. Two pricing parts is therefore not an error, it is a choice.

The confirmation lives in a table in THIS package, keyed by ``set_id``. No column is added to any
``client_boq_*`` table. The UNIQUE constraint is on ``(set_id, part_id)`` from the start: adding
it later would cost a migration.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3

# The one place that decides which of a part's two categories is authoritative. Imported rather
# than reimplemented so the Route proposal and the review's skip-list can never disagree about
# what a part IS — they read the same answer from the same function.
from client_boq.review.s01_ingest import effective_category

BILL_CATEGORY = "pricing"  # PART_CATEGORIES value that proposes a part as the priced bill


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the bridge's bill-part table if absent (lazy DDL, idempotent).

    UNIQUE ``(set_id, part_id)`` is deliberate and present from the first version: a
    re-confirmation must update in place, never accumulate duplicate rows that would each be
    read back as another bill part.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_bill_parts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id TEXT NOT NULL,
            part_id TEXT NOT NULL,
            confirmed_by TEXT NOT NULL DEFAULT 'operator',
            confirmed_at TEXT NOT NULL,
            UNIQUE(set_id, part_id)
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_bill_parts_set ON bridge_bill_parts(set_id);
        """
    )
    conn.commit()


def _set_parts(conn: sqlite3.Connection, set_id: str) -> list[tuple]:
    """The set's parts at their latest revision — client_boq's operative view, read-only."""
    from client_boq import store as cb_store

    return cb_store.load_parts(conn, set_id)


def _describe(spec, pdf_path: str, proposed: set[str], confirmed: set[str]) -> dict:
    return {
        "part_id": spec.part_id,
        "n": spec.n,
        "title": spec.title,
        "category": spec.category,
        "pages": spec.page_count(),
        "scanned": bool(spec.scanned),
        # pdf_path can legitimately be "" (client_boq/store.py:649); a part with no cut pdf can
        # contribute no text, so the human sees that BEFORE choosing it as the bill.
        "has_pdf": bool(pdf_path),
        "source_doc": spec.source_doc,
        "rev": spec.rev,
        "proposed": spec.part_id in proposed,
        "confirmed": spec.part_id in confirmed,
    }


def candidates_on(conn: sqlite3.Connection, set_id: str) -> dict:
    """``bq_candidates`` against a caller-owned connection."""
    ensure_tables(conn)
    parts = _set_parts(conn, set_id)
    stored = {
        row["part_id"]
        for row in conn.execute(
            "SELECT part_id FROM bridge_bill_parts WHERE set_id = ?", (set_id,)
        ).fetchall()
    }
    live_ids = {spec.part_id for spec, _p, _c in parts}
    # The INTERPRETED category, not the planner's guess. The planner is shown a digest with no
    # body text, and on the first real bill it said `other` — so Route reported "No part is
    # categorised 'pricing', so nothing is proposed" about a 26-page bill of quantities and made
    # the operator find it by hand. The interpreter had read the pages and knew; its answer was
    # already the third element of every tuple here, discarded as `_c`.
    proposed = {
        spec.part_id for spec, _p, ctx in parts
        if effective_category(spec, ctx)[0] == BILL_CATEGORY
    }
    confirmed = stored & live_ids
    # A stored id whose part no longer exists (a re-split dropped or renamed it). Surfaced, never
    # silently discarded — the operator has to know their confirmation no longer covers the set.
    stale = sorted(stored - live_ids)

    if not parts:
        message = (
            f"No parts found for set {set_id!r} — ingest and approve the split manifest first."
        )
    elif not proposed:
        # Degrade honestly: never guess the bill from a title.
        message = (
            "No part is categorised 'pricing' — neither by the interpreter that read the pages "
            "nor by the planner that read the structure — so nothing is proposed. Choose the "
            "priced bill yourself from the full list below."
        )
    elif len(proposed) == 1:
        message = "One pricing part found and pre-selected. Confirm it, or choose a different set."
    else:
        message = (
            f"{len(proposed)} pricing parts found and pre-selected (a bill of quantities and a "
            "daywork or provisional-items schedule are both priceable). Confirm the set you want."
        )
    if stale:
        message += f" NOTE: {len(stale)} previously confirmed part(s) no longer exist in this set: {', '.join(stale)}."

    return {
        "set_id": set_id,
        "parts": [_describe(spec, path, proposed, confirmed) for spec, path, _c in parts],
        "proposed": sorted(proposed),
        "confirmed": [pid for pid in (s.part_id for s, _p, _c in parts) if pid in confirmed],
        "stale_confirmed": stale,
        "message": message,
    }


def bq_candidates(set_id: str) -> dict:
    """Every part in the set with what a human needs to choose the bill, and what is proposed.

    Read-only — it does not register the set (a GET must not write). ``proposed`` is every part
    whose category is ``pricing``; when there is none, the full list comes back with nothing
    proposed and a message saying so, rather than a guess from the title.
    """
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        return candidates_on(conn, run_ref_for(set_id))
    finally:
        conn.close()


def confirm_on(
    conn: sqlite3.Connection, set_id: str, part_ids: list[str], *, confirmed_by: str = "operator"
) -> dict:
    """``confirm_bill_parts`` against a caller-owned connection."""
    ensure_tables(conn)
    wanted = [pid.strip() for pid in (part_ids or []) if pid and pid.strip()]
    if not wanted:
        raise ValueError(
            "Confirm at least one bill part — the priced bill is what produces every item, so an "
            "empty confirmation cannot be stored."
        )
    parts = _set_parts(conn, set_id)
    if not parts:
        raise LookupError(f"No parts found for set {set_id!r} — ingest the set first.")

    live_ids = {spec.part_id for spec, _p, _c in parts}
    unknown = [pid for pid in wanted if pid not in live_ids]
    if unknown:
        # Never store a phantom part: it would read back as a bill part and then fail, or worse,
        # quietly shrink the bill.
        raise ValueError(
            f"Unknown part id(s) for set {set_id!r}: {', '.join(sorted(unknown))}. "
            f"Valid ids: {', '.join(sorted(live_ids))}."
        )

    stamp = _now()
    # Replace the whole confirmation: this is a set, and re-confirming means "these, not those".
    conn.execute("DELETE FROM bridge_bill_parts WHERE set_id = ?", (set_id,))
    conn.executemany(
        "INSERT INTO bridge_bill_parts (set_id, part_id, confirmed_by, confirmed_at) "
        "VALUES (?, ?, ?, ?)",
        [(set_id, pid, confirmed_by, stamp) for pid in dict.fromkeys(wanted)],
    )
    conn.commit()
    return candidates_on(conn, set_id)


def confirm_bill_parts(
    set_id: str, part_ids: list[str], *, confirmed_by: str = "operator"
) -> dict:
    """Record the human's chosen SET of bill parts for ``set_id`` and return the stored state.

    Rejects an id that is not a real part of the set, and rejects an empty selection. Replaces any
    previous confirmation. Registers the tender's umbrella row — this is the bridge's first
    mutating touch of the set.
    """
    from bridge.identity import bridge_conn, register_set_on, run_ref_for

    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        out = confirm_on(conn, ref, part_ids, confirmed_by=confirmed_by)
        register_set_on(conn, ref)
        return out
    finally:
        conn.close()


def confirmed_bill_parts(conn: sqlite3.Connection, set_id: str) -> list[str]:
    """The confirmed bill ``part_id``s for ``set_id``, in document order — empty when unconfirmed.

    Ordered by client_boq's own part ordering rather than by insertion, so the assembled
    ``doc_text`` follows the document rather than the order a human happened to click.
    """
    ensure_tables(conn)
    stored = {
        row["part_id"]
        for row in conn.execute(
            "SELECT part_id FROM bridge_bill_parts WHERE set_id = ?", (set_id,)
        ).fetchall()
    }
    if not stored:
        return []
    return [spec.part_id for spec, _p, _c in _set_parts(conn, set_id) if spec.part_id in stored]
