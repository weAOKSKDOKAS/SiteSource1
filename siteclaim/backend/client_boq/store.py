"""Persistence for the client_boq module — the ``client_boq_*`` tables and the Workspace artifacts.

Two homes, by design (a locked decision):

* **Workspace artifacts** (``artifacts/client_boq/parsed.json`` and ``register.json``) — a readable,
  per-tender file copy, reusing ``pipeline/workspace.py`` and its deterministic ``tender_slug``.
* **The ``client_boq_*`` tables** — the SOURCE OF TRUTH for the review→estimate gate. The register
  and its ``approved`` flag live here; the estimate gate check reads this, not the artifact file.

Everything is deterministic infra (no AI, no network beyond the local SQLite file). The DB connection
comes from the shared ``db.store.get_connection`` (honouring ``SITESOURCE_DB``); tables are created
lazily on first use via ``models.init_tables``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from client_boq import models
from client_boq.models import (
    BADGE_USER,
    ClientBill,
    ContextSummary,
    DepartureRegister,
    Estimate,
    EstimateSchedule,
    EstimateScope,
    ItemAssumption,
    LetterOfOffer,
    ParsedDocumentSet,
    PartContext,
    PartSpec,
    RFIBatch,
    RFIItem,
    ScheduleItem,
    ScopeReviewResult,
    SplitManifest,
)
from db import store as db_store
from pipeline.llm_client import demo_mode
from pipeline.workspace import Workspace

if TYPE_CHECKING:  # imported lazily at call sites — client_boq.boq pulls in the whole costing engine,
    from client_boq.boq.criteria import SiteCriteria   # and store has no business loading it to
    from client_boq.boq.georef import SheetRegistration  # save a row
    from client_boq.boq.groups import HoleGroup
    from client_boq.boq.model import CostingModel
    from client_boq.boq.outputs import OutputBook
    from client_boq.boq.schedule import StationSchedule
    from client_boq.boq.unbilled import UnbilledCost, UnbilledSweep


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def _demo_db_path() -> Path:
    """A gitignored scratch DB for DEMO runs — under the workspace out dir (``backend/fixtures/out/``,
    already gitignored), so a DEMO review never writes the committed ``sitesource.db`` (decision 4A)."""
    return Workspace().root.parent / "client_boq_demo.db"


def get_conn() -> sqlite3.Connection:
    """Open the DB the module's tables live in and ensure those tables exist (idempotent).

    Path: an explicit ``SITESOURCE_DB`` always wins (live, tests). Otherwise, in DEMO mode the module
    defaults to a gitignored scratch DB (decision 4A) so an offline demo leaves the committed
    ``sitesource.db`` byte-identical; live with no override uses the shared default DB as before.
    """
    if not os.getenv("SITESOURCE_DB", "").strip() and demo_mode():
        path = _demo_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            sqlite3.connect(str(path)).close()  # create the file so get_connection accepts it
        conn = db_store.get_connection(path)
    else:
        conn = db_store.get_connection()
    models.init_tables(conn)
    return conn


# ---------------------------------------------------------------------------
# Document set + parsed store + summary
# ---------------------------------------------------------------------------
def upsert_document_set(
    conn: sqlite3.Connection, *, set_id: str, name: str, slug: str, status: str,
    parsed_json: Optional[str] = None, summary_json: Optional[str] = None,
) -> None:
    """Create/update the document-set row. ``parsed_json``/``summary_json`` are only overwritten when
    provided (None leaves the stored value), so recording the summary never clobbers the parsed set."""
    conn.execute(
        """
        INSERT INTO client_boq_document_sets (set_id, name, slug, status, parsed_json, summary_json)
        VALUES (:set_id, :name, :slug, :status, COALESCE(:parsed, '{}'), COALESCE(:summary, '{}'))
        ON CONFLICT(set_id) DO UPDATE SET
            name = excluded.name,
            slug = excluded.slug,
            status = excluded.status,
            parsed_json = COALESCE(:parsed, client_boq_document_sets.parsed_json),
            summary_json = COALESCE(:summary, client_boq_document_sets.summary_json)
        """,
        {"set_id": set_id, "name": name, "slug": slug, "status": status,
         "parsed": parsed_json, "summary": summary_json},
    )
    conn.commit()


def load_set(conn: sqlite3.Connection, set_id: str) -> Optional[dict]:
    """The document set's own row (name, slug, status, created_at), or None.

    The ``name`` matters beyond display: it is the key ``Workspace`` slugifies to find the
    tender's directory, so anything reading artifacts off disk needs it rather than the set_id.
    """
    row = conn.execute(
        "SELECT set_id, name, slug, status, created_at FROM client_boq_document_sets WHERE set_id = ?",
        (set_id,),
    ).fetchone()
    return dict(row) if row else None


def _register_verdict_counts(register_blob: Optional[str]) -> tuple[int, int]:
    """(undecided, citation_failed) from a stored register JSON blob, without validating the
    whole model — the same economy as the price pluck below. Undecided = a line still waiting
    on a human verdict; a citation_failed line is counted separately because it cannot be
    confirmed (the approve endpoint 409s) and is therefore what BLOCKS, not what waits."""
    if not register_blob or register_blob == "{}":
        return 0, 0
    try:
        items = json.loads(register_blob).get("items") or []
    except (ValueError, AttributeError):
        return 0, 0
    undecided = failed = 0
    for it in items:
        status = (it or {}).get("status", "")
        if status == models.STATUS_CITATION_FAILED:
            failed += 1
        elif status not in models.HUMAN_VERDICTS:
            undecided += 1
    return undecided, failed


def _blocked(row: dict, meta: dict) -> bool:
    """Whether anything is stopping this tender moving — the desk's 'Blocked' filter.

    The definition must agree with what the gates actually refuse, or the filter lies:
    an unapproved manifest (nothing can run), a failed citation (cannot be confirmed),
    an unaccepted AI fallback (the freeze gate 409s), or an RFI still open past the
    query cut-off (the client can no longer be asked).
    """
    if not row["gates"]["manifest"] and row["parts"] == 0:
        return True  # uploaded but the split is not approved — the first gate is shut
    if row["counts"]["citation_failed"] > 0:
        return True
    if row["counts"]["unaccepted_fallbacks"] > 0:
        return True
    cutoff = meta.get("query_cutoff") or ""
    if row["counts"]["open_rfis"] > 0 and cutoff:
        from datetime import date
        try:
            if date.fromisoformat(cutoff) < date.today():
                return True
        except ValueError:
            pass  # an unparseable cut-off never silently blocks
    return False


_META_FIELDS = (
    "owner_id", "client", "package", "archived", "outcome",
    "close_date", "close_date_status", "close_date_clause", "close_date_page",
    "close_date_part_id", "close_date_quote", "close_date_confirmed_by",
    "query_cutoff", "last_touched_by", "last_touched_at",
)

_META_DEFAULTS = {
    "owner_id": "", "client": "", "package": "", "archived": False, "outcome": "live",
    "close_date": "", "close_date_status": "reading", "close_date_clause": "",
    "close_date_page": None, "close_date_part_id": "", "close_date_quote": "",
    "close_date_confirmed_by": "", "query_cutoff": "", "last_touched_by": "",
    "last_touched_at": None,
}


def list_sets(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    """Every document set, newest first, with its part count, gate states, desk metadata and
    the counts the home screen's cards and filters need.

    One query for the whole list: a dashboard needs to show where each tender has got to, and
    N+1 gate lookups for that is wasteful. The register-derived counts are computed here rather
    than client-side because the register blob only exists server-side — and the 'blocked'
    boolean must agree with what the gates refuse, which only this layer knows.

    Archived tenders leave the shelf by default (the shelf is only what still needs work) but
    stay reachable with ``include_archived=True`` — a lost tender's register is the best
    reference for the next bid to the same client.
    """
    marks = ",".join("?" for _ in models.RFI_OPEN)
    rows = conn.execute(
        f"""
        SELECT s.set_id, s.name, s.slug, s.status, s.created_at,
               (SELECT COUNT(*) FROM client_boq_parts p WHERE p.set_id = s.set_id) AS parts,
               COALESCE(m.approved, 0) AS manifest_approved,
               COALESCE(m.tier, 0)     AS tier,
               COALESCE(r.approved, 0) AS review_approved,
               r.register_json          AS register_json,
               COALESCE(sc.approved, 0) AS scope_approved,
               e.estimate_json          AS estimate_json,
               -- Whether the CURRENT engine has anything. `estimate_json` is written only by the
               -- retired resource-schedule engine (`save_estimate`), so a tender priced the normal
               -- way -- import the client's bill, settle the rates -- left every "has a price"
               -- flag false forever, and the app's next-action line never advanced past "build the
               -- price". An EXISTS rather than the engine: a list view must not run the costing.
               EXISTS (SELECT 1 FROM client_boq_bill_revisions br
                        WHERE br.set_id = s.set_id)  AS has_bill,
               (l.set_id IS NOT NULL)   AS has_letter,
               (SELECT COUNT(*) FROM client_boq_scope_items si
                 WHERE si.set_id = s.set_id AND si.is_fallback = 1 AND si.accepted = 0
               ) AS unaccepted_fallbacks,
               (SELECT COUNT(*) FROM client_boq_rfi_items q
                 WHERE q.set_id = s.set_id AND q.status IN ({marks})
               ) AS open_rfis,
               {", ".join(f"mt.{f}" for f in _META_FIELDS)}
        FROM client_boq_document_sets s
        LEFT JOIN client_boq_manifests        m  ON m.set_id  = s.set_id
        LEFT JOIN client_boq_review_registers r  ON r.set_id  = s.set_id
        LEFT JOIN client_boq_estimate_scope   sc ON sc.set_id = s.set_id
        LEFT JOIN client_boq_estimates        e  ON e.set_id  = s.set_id
        LEFT JOIN client_boq_letters          l  ON l.set_id  = s.set_id
        LEFT JOIN client_boq_set_meta         mt ON mt.set_id = s.set_id
        ORDER BY s.created_at DESC, s.set_id
        """,
        tuple(sorted(models.RFI_OPEN)),
    ).fetchall()

    out: list[dict] = []
    for row in rows:
        # Pull just the headline price out of the estimate blob rather than validating the whole
        # model: a list view needs one number, not the full cost build-up.
        price = None
        blob = row["estimate_json"]
        if blob and blob != "{}":
            try:
                price = (json.loads(blob).get("totals") or {}).get("price")
            except (ValueError, AttributeError):
                price = None
        undecided, citation_failed = _register_verdict_counts(row["register_json"])
        meta = {f: (row[f] if row[f] is not None else _META_DEFAULTS[f]) for f in _META_FIELDS}
        meta["archived"] = bool(meta["archived"])
        if not include_archived and meta["archived"]:
            continue
        entry = {
            "set_id": row["set_id"],
            "name": row["name"],
            "slug": row["slug"],
            "status": row["status"],
            "created_at": row["created_at"],
            "parts": row["parts"],
            "tier": row["tier"],
            "gates": {
                "manifest": bool(row["manifest_approved"]),
                "review": bool(row["review_approved"]),
                "scope": bool(row["scope_approved"]),
            },
            "price": price,
            # The retired engine's headline figure, or None. `has_bill` is the current engine's
            # evidence and is deliberately a separate field: they are different engines and one
            # having run says nothing about the other.
            "has_bill": bool(row["has_bill"]),
            "has_letter": bool(row["has_letter"]),
            "meta": meta,
            "counts": {
                "undecided": undecided,
                "citation_failed": citation_failed,
                "unaccepted_fallbacks": int(row["unaccepted_fallbacks"]),
                "open_rfis": int(row["open_rfis"]),
            },
        }
        entry["blocked"] = _blocked(entry, meta)
        out.append(entry)
    return out


def load_parsed(conn: sqlite3.Connection, set_id: str) -> Optional[ParsedDocumentSet]:
    """The persisted parsed document set for ``set_id`` (tables copy), or None."""
    row = conn.execute(
        "SELECT parsed_json FROM client_boq_document_sets WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["parsed_json"] or row["parsed_json"] == "{}":
        return None
    return ParsedDocumentSet.model_validate_json(row["parsed_json"])


def load_summary(conn: sqlite3.Connection, set_id: str) -> Optional[ContextSummary]:
    """The persisted s02 commercial-risk summary for ``set_id``, or None."""
    row = conn.execute(
        "SELECT summary_json FROM client_boq_document_sets WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["summary_json"] or row["summary_json"] == "{}":
        return None
    return ContextSummary.model_validate_json(row["summary_json"])


# ---------------------------------------------------------------------------
# The tender desk — team, per-set metadata, touch tracking
# ---------------------------------------------------------------------------
def list_team(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    """Every team member, oldest first (a stable roster order)."""
    where = "" if include_archived else "WHERE archived = 0"
    rows = conn.execute(
        f"SELECT member_id, name, initials, colour, role, archived, created_at "
        f"FROM client_boq_team_members {where} ORDER BY created_at, member_id"
    ).fetchall()
    return [{**dict(row), "archived": bool(row["archived"])} for row in rows]


def upsert_team_member(conn: sqlite3.Connection, *, member_id: str, name: str,
                       initials: str = "", colour: str = "", role: str = "",
                       archived: bool = False) -> None:
    """Create or update one member. Archiving keeps the row — the name is stamped on historical
    verdicts and ownership, so a member is never deleted."""
    conn.execute(
        """
        INSERT INTO client_boq_team_members (member_id, name, initials, colour, role, archived)
        VALUES (:member_id, :name, :initials, :colour, :role, :archived)
        ON CONFLICT(member_id) DO UPDATE SET
            name = excluded.name, initials = excluded.initials, colour = excluded.colour,
            role = excluded.role, archived = excluded.archived
        """,
        {"member_id": member_id, "name": name, "initials": initials, "colour": colour,
         "role": role, "archived": int(archived)},
    )
    conn.commit()


def load_set_meta(conn: sqlite3.Connection, set_id: str) -> dict:
    """The desk metadata for one set. Always returns a full dict — a set with no meta row yet
    reads as the defaults (owner unknown, close date still ``reading``), never as an error."""
    row = conn.execute(
        f"SELECT {', '.join(_META_FIELDS)} FROM client_boq_set_meta WHERE set_id = ?", (set_id,)
    ).fetchone()
    if row is None:
        return dict(_META_DEFAULTS)
    meta = {f: (row[f] if row[f] is not None else _META_DEFAULTS[f]) for f in _META_FIELDS}
    meta["archived"] = bool(meta["archived"])
    return meta


def upsert_set_meta(conn: sqlite3.Connection, set_id: str, **fields) -> dict:
    """Update named metadata fields for a set, creating the row if absent. Only the fields
    passed change; everything else keeps its stored value. Returns the merged result."""
    unknown = set(fields) - set(_META_FIELDS)
    if unknown:
        raise ValueError(f"unknown set_meta fields: {sorted(unknown)}")
    current = load_set_meta(conn, set_id)
    merged = {**current, **fields}
    merged["archived"] = int(bool(merged["archived"]))
    conn.execute(
        f"""
        INSERT INTO client_boq_set_meta (set_id, {', '.join(_META_FIELDS)})
        VALUES (:set_id, {', '.join(':' + f for f in _META_FIELDS)})
        ON CONFLICT(set_id) DO UPDATE SET
            {', '.join(f'{f} = excluded.{f}' for f in _META_FIELDS)}
        """,
        {"set_id": set_id, **merged},
    )
    conn.commit()
    merged["archived"] = bool(merged["archived"])
    return merged


def touch_set(conn: sqlite3.Connection, set_id: str, actor: str) -> None:
    """Stamp who last worked this tender and when — the desk card's footer. Cheap by design
    (called from every mutating route); an empty actor still moves the clock, because the work
    happened even if nobody said who they were."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_set_meta (set_id, last_touched_by, last_touched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(set_id) DO UPDATE SET
            last_touched_by = excluded.last_touched_by,
            last_touched_at = excluded.last_touched_at
        """,
        (set_id, actor, now),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# App-wide settings (key/value)
# ---------------------------------------------------------------------------
def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM client_boq_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str, actor: str = "") -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_settings (key, value, updated_by, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value, updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (key, value, actor, now),
    )
    conn.commit()


def list_settings(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT key, value, updated_by, updated_at FROM client_boq_settings ORDER BY key"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# The output book — what your company knows, as distinct from what a job needs
# ---------------------------------------------------------------------------
def load_output_book(conn: sqlite3.Connection) -> "OutputBook":
    """The company's norms. An empty table is not an error — it means nobody has overridden a
    default yet, and :func:`client_boq.boq.outputs.OutputBook.get` falls back to the declared one."""
    from client_boq.boq.outputs import OutputBook
    rows = conn.execute("SELECT key, value FROM client_boq_outputs").fetchall()
    return OutputBook(values={row["key"]: float(row["value"]) for row in rows})


def save_output_norm(conn: sqlite3.Connection, key: str, value: float, *,
                     unit: str = "", actor: str = "") -> None:
    """Write one norm. Editing one changes every future estimate; it never rewrites one already run —
    the same promise the rate book makes, and for the same reason."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_outputs (key, value, unit, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value, unit = excluded.unit,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (key, float(value), unit, actor, now),
    )
    conn.commit()


def output_norm_meta(conn: sqlite3.Connection) -> dict[str, dict]:
    """Who last touched each norm, and when. Keyed by norm; absent means never edited."""
    rows = conn.execute(
        "SELECT key, updated_by, updated_at FROM client_boq_outputs"
    ).fetchall()
    return {row["key"]: {"updated_by": row["updated_by"], "updated_at": row["updated_at"]}
            for row in rows}


# ---------------------------------------------------------------------------
# The pricing schedule — the INPUT a live estimate is run from
# ---------------------------------------------------------------------------
def load_schedule(conn: sqlite3.Connection, set_id: str) -> tuple[Optional[EstimateSchedule], float]:
    """The persisted schedule and margin for a set, or ``(None, 0.0)``.

    Returns the margin separately rather than folding it into the schedule because they are
    different kinds of fact: the schedule is quantities and resources, the margin is a commercial
    decision the person makes at the moment of pricing. ``/estimate/run`` takes them as two
    arguments for the same reason.
    """
    row = conn.execute(
        "SELECT schedule_json, margin_pct FROM client_boq_schedules WHERE set_id = ?", (set_id,)
    ).fetchone()
    if row is None or not row["schedule_json"]:
        return None, 0.0
    return EstimateSchedule.model_validate_json(row["schedule_json"]), float(row["margin_pct"] or 0)


def save_schedule(
    conn: sqlite3.Connection, set_id: str, schedule: EstimateSchedule, margin_pct: float,
    actor: str = "",
) -> None:
    """Persist the schedule a live estimate will be run from. Stamps who last touched it — a bill
    of quantities is somebody's work, and a price that rests on it should be able to say whose."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_schedules (set_id, schedule_json, margin_pct, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(set_id) DO UPDATE SET
            schedule_json = excluded.schedule_json, margin_pct = excluded.margin_pct,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (set_id, schedule.model_dump_json(), float(margin_pct), actor, now),
    )
    conn.commit()


def schedule_meta(conn: sqlite3.Connection, set_id: str) -> dict:
    """Who last saved the schedule, and when ('' / None when never saved)."""
    row = conn.execute(
        "SELECT updated_by, updated_at FROM client_boq_schedules WHERE set_id = ?", (set_id,)
    ).fetchone()
    return {"updated_by": row["updated_by"], "updated_at": row["updated_at"]} if row else {
        "updated_by": "", "updated_at": None
    }


# ---------------------------------------------------------------------------
# The client's bill of quantities — revisions, rates, and the assumptions behind them
# ---------------------------------------------------------------------------
def save_bill_revision(
    conn: sqlite3.Connection, bill: "ClientBill", *, doc_id: str = "",
) -> int:
    """Append a bill revision. Returns the rev written.

    Append-only, like ``save_parts``: a new revision leaves every earlier one readable, because the
    only way to see what an addendum did is to compare the two. Re-importing the SAME rev overwrites
    it (you corrected a bad read); a new rev never touches its predecessor.
    """
    conn.execute(
        """
        INSERT INTO client_boq_bill_revisions (set_id, rev, doc_id, source_file, bill_json, read_notes)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, rev) DO UPDATE SET
            doc_id = excluded.doc_id, source_file = excluded.source_file,
            bill_json = excluded.bill_json, read_notes = excluded.read_notes
        """,
        (bill.set_id, int(bill.rev), doc_id, bill.source_file, bill.model_dump_json(),
         json.dumps(bill.notes)),
    )
    conn.commit()
    return int(bill.rev)


def load_bill(conn: sqlite3.Connection, set_id: str, rev: Optional[int] = None) -> Optional["ClientBill"]:
    """The bill at ``rev``, or the OPERATIVE one (highest rev) when rev is None.

    Derived rather than flagged, for the same reason ``load_parts`` derives it: a stored
    "is_operative" column is one failed write away from pointing at a superseded bill, and you
    would price the wrong document without anything looking wrong.
    """
    if rev is None:
        row = conn.execute(
            "SELECT bill_json FROM client_boq_bill_revisions WHERE set_id = ? ORDER BY rev DESC LIMIT 1",
            (set_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT bill_json FROM client_boq_bill_revisions WHERE set_id = ? AND rev = ?",
            (set_id, int(rev)),
        ).fetchone()
    if row is None or not row["bill_json"]:
        return None
    return ClientBill.model_validate_json(row["bill_json"])


def list_bill_revisions(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    """Every bill revision held for a set, oldest first, with its cause and item count."""
    rows = conn.execute(
        """
        SELECT rev, doc_id, source_file, read_notes, created_at
        FROM client_boq_bill_revisions WHERE set_id = ? ORDER BY rev
        """,
        (set_id,),
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        bill = load_bill(conn, set_id, int(row["rev"]))
        out.append({
            "rev": int(row["rev"]),
            "doc_id": row["doc_id"],
            "source_file": row["source_file"],
            "created_at": row["created_at"],
            "items": len(bill.items) if bill else 0,
            "notes": json.loads(row["read_notes"] or "[]"),
        })
    return out


def next_bill_rev(conn: sqlite3.Connection, set_id: str) -> int:
    """The rev a newly imported bill should take."""
    row = conn.execute(
        "SELECT MAX(rev) AS r FROM client_boq_bill_revisions WHERE set_id = ?", (set_id,)
    ).fetchone()
    return 0 if row is None or row["r"] is None else int(row["r"]) + 1


def save_bill_rate(
    conn: sqlite3.Connection, set_id: str, rev: int, full_ref: str, *,
    rate: Optional[float] = None, amount: Optional[float] = None,
    build_up: Optional["ScheduleItem"] = None, basis: str = "", badge: str = BADGE_USER,
    needs_review: bool = False, review_note: str = "", actor: str = "",
) -> None:
    """Save one item's rate and its build-up, for one revision of the bill."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_bill_rates
            (set_id, rev, full_ref, rate, amount, buildup_json, basis, badge, needs_review,
             review_note, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, rev, full_ref) DO UPDATE SET
            rate = excluded.rate, amount = excluded.amount, buildup_json = excluded.buildup_json,
            basis = excluded.basis, badge = excluded.badge, needs_review = excluded.needs_review,
            review_note = excluded.review_note, updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (set_id, int(rev), full_ref, rate, amount,
         build_up.model_dump_json() if build_up is not None else "{}",
         basis, badge, 1 if needs_review else 0, review_note, actor, now),
    )
    conn.commit()


def load_bill_rates(conn: sqlite3.Connection, set_id: str, rev: int) -> dict[str, dict]:
    """full_ref → the stored rate row, for one revision."""
    rows = conn.execute(
        """
        SELECT full_ref, rate, amount, buildup_json, basis, badge, needs_review, review_note,
               updated_by, updated_at
        FROM client_boq_bill_rates WHERE set_id = ? AND rev = ?
        """,
        (set_id, int(rev)),
    ).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        build_up = None
        if row["buildup_json"] and row["buildup_json"] != "{}":
            build_up = ScheduleItem.model_validate_json(row["buildup_json"])
        out[row["full_ref"]] = {
            "full_ref": row["full_ref"],
            "rate": row["rate"],
            "amount": row["amount"],
            "build_up": build_up,
            "basis": row["basis"],
            "badge": row["badge"],
            "needs_review": bool(row["needs_review"]),
            "review_note": row["review_note"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"],
        }
    return out


def bill_review_pending(conn: sqlite3.Connection, set_id: str, rev: int) -> list[dict]:
    """Items in this revision whose carried rate still has to be looked at by a person.

    The forcing function for a revision: a rate carried onto a quantity that doubled is legal under
    GCT App C 2.2(v) and is not necessarily still the right estimate.
    """
    rows = conn.execute(
        """
        SELECT full_ref, review_note FROM client_boq_bill_rates
        WHERE set_id = ? AND rev = ? AND needs_review = 1 ORDER BY full_ref
        """,
        (set_id, int(rev)),
    ).fetchall()
    return [{"full_ref": row["full_ref"], "reason": row["review_note"]} for row in rows]


def save_item_assumption(
    conn: sqlite3.Connection, set_id: str, rev: int, assumption: "ItemAssumption", actor: str = "",
) -> None:
    """Save how one item's given quantity is assumed to split across working conditions."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_item_assumptions
            (set_id, rev, full_ref, assumption_json, basis, badge, source_part_id, source_page,
             updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, rev, full_ref) DO UPDATE SET
            assumption_json = excluded.assumption_json, basis = excluded.basis,
            badge = excluded.badge, source_part_id = excluded.source_part_id,
            source_page = excluded.source_page, updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (set_id, int(rev), assumption.full_ref, assumption.model_dump_json(), assumption.basis,
         assumption.badge, assumption.source_part_id, int(assumption.source_page), actor, now),
    )
    conn.commit()


def load_item_assumptions(conn: sqlite3.Connection, set_id: str, rev: int) -> dict[str, "ItemAssumption"]:
    """full_ref → the assumption behind that item's rate, for one revision."""
    rows = conn.execute(
        "SELECT full_ref, assumption_json FROM client_boq_item_assumptions WHERE set_id = ? AND rev = ?",
        (set_id, int(rev)),
    ).fetchall()
    return {
        row["full_ref"]: ItemAssumption.model_validate_json(row["assumption_json"])
        for row in rows if row["assumption_json"] and row["assumption_json"] != "{}"
    }


# ---------------------------------------------------------------------------
# The take-off — the station schedule, the site's rules, hole classes and groups
#
# The drawing's half of the estimate. Every table here answers a question the bill of quantities
# does not: where the holes are, what the specification says about them, which of them a rig can
# reach, and which of them drill alike.
# ---------------------------------------------------------------------------
def load_station_schedule(conn: sqlite3.Connection, set_id: str) -> tuple[Optional["StationSchedule"], dict]:
    """The schedule read off the drawing, and who (if anyone) has confirmed that reading.

    Returns the confirmation separately because it is not a property of the holes — it is a
    property of somebody having looked. An unconfirmed schedule is a machine's proposal and
    nothing prices from it.
    """
    from client_boq.boq.schedule import StationSchedule
    row = conn.execute(
        """
        SELECT schedule_json, source_sheet, confirmed_by, confirmed_at, updated_by, updated_at
        FROM client_boq_station_schedules WHERE set_id = ?
        """,
        (set_id,),
    ).fetchone()
    if row is None or not row["schedule_json"] or row["schedule_json"] == "{}":
        return None, {"confirmed_by": "", "confirmed_at": None, "source_sheet": ""}
    return StationSchedule.model_validate_json(row["schedule_json"]), {
        "confirmed_by": row["confirmed_by"],
        "confirmed_at": row["confirmed_at"],
        "source_sheet": row["source_sheet"],
        "updated_by": row["updated_by"],
        "updated_at": row["updated_at"],
    }


def save_station_schedule(conn: sqlite3.Connection, set_id: str, schedule: "StationSchedule", *,
                          source_sheet: str = "", confirmed: bool = False, actor: str = "") -> None:
    """Replace the schedule for a set. One row: there is only ever one truth about where the holes are.

    Confirming is an act with a name on it and it is not sticky — a re-read lands unconfirmed again,
    because the thing somebody checked is no longer the thing on the screen.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_station_schedules
            (set_id, schedule_json, source_sheet, confirmed_by, confirmed_at, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id) DO UPDATE SET
            schedule_json = excluded.schedule_json, source_sheet = excluded.source_sheet,
            confirmed_by = excluded.confirmed_by, confirmed_at = excluded.confirmed_at,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (set_id, schedule.model_dump_json(), source_sheet or schedule.source_sheet,
         actor if confirmed else "", now if confirmed else None, actor, now),
    )
    conn.commit()


def load_site_criteria(conn: sqlite3.Connection, set_id: str) -> tuple["SiteCriteria", dict[str, str]]:
    """The general-notes drawing's rules, and which bill items carry the Class A / B rig moves.

    Both default rather than returning None: the criteria's own defaults are the reference
    contract's, and a set nobody has configured is more usefully shown with those than with a blank
    screen — every one of them is an input the estimator can correct.
    """
    from client_boq.boq.criteria import SiteCriteria
    row = conn.execute(
        "SELECT criteria_json, source_sheet, class_refs FROM client_boq_site_criteria WHERE set_id = ?",
        (set_id,),
    ).fetchone()
    if row is None or not row["criteria_json"] or row["criteria_json"] == "{}":
        return SiteCriteria(), {"A": "2.2a", "B": "2.2b"}
    criteria = SiteCriteria.model_validate_json(row["criteria_json"])
    refs = json.loads(row["class_refs"] or "{}") or {"A": "2.2a", "B": "2.2b"}
    return criteria, {str(k): str(v) for k, v in refs.items()}


def save_site_criteria(conn: sqlite3.Connection, set_id: str, criteria: "SiteCriteria", *,
                       class_refs: Optional[dict[str, str]] = None, actor: str = "") -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_site_criteria
            (set_id, criteria_json, source_sheet, class_refs, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id) DO UPDATE SET
            criteria_json = excluded.criteria_json, source_sheet = excluded.source_sheet,
            class_refs = excluded.class_refs, updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (set_id, criteria.model_dump_json(), criteria.source_sheet,
         json.dumps(class_refs or {"A": "2.2a", "B": "2.2b"}), actor, now),
    )
    conn.commit()


def load_station_classes(conn: sqlite3.Connection, set_id: str) -> dict[str, dict]:
    """station → {access_class, group_id, decided_by, decided_at}. Absent means undecided."""
    rows = conn.execute(
        """
        SELECT station, access_class, group_id, decided_by, decided_at
        FROM client_boq_station_classes WHERE set_id = ?
        """,
        (set_id,),
    ).fetchall()
    return {row["station"]: dict(row) for row in rows}


def save_station_class(conn: sqlite3.Connection, set_id: str, station: str, *,
                       access_class: str = "", group_id: Optional[str] = None,
                       actor: str = "") -> None:
    """Record one hole's access class, with a name against it.

    The name is the point. The bill prices 80 Class A moves and no drawing says which holes those
    are, so when a count disagrees with the bill the only way to settle it is to ask the person who
    made the call — which requires knowing who that was.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = conn.execute(
        "SELECT group_id FROM client_boq_station_classes WHERE set_id = ? AND station = ?",
        (set_id, station),
    ).fetchone()
    resolved_group = existing["group_id"] if group_id is None and existing else (group_id or "")
    conn.execute(
        """
        INSERT INTO client_boq_station_classes
            (set_id, station, access_class, group_id, decided_by, decided_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, station) DO UPDATE SET
            access_class = excluded.access_class, group_id = excluded.group_id,
            decided_by = excluded.decided_by, decided_at = excluded.decided_at
        """,
        (set_id, station, access_class, resolved_group, actor, now),
    )
    conn.commit()


def load_hole_groups(conn: sqlite3.Connection, set_id: str, rev: int) -> list["HoleGroup"]:
    """The groups for one revision, in a stable order so the screen does not reshuffle on save."""
    from client_boq.boq.groups import HoleGroup
    rows = conn.execute(
        """
        SELECT group_id, group_json FROM client_boq_hole_groups
        WHERE set_id = ? AND rev = ? ORDER BY group_id
        """,
        (set_id, int(rev)),
    ).fetchall()
    return [HoleGroup.model_validate_json(row["group_json"])
            for row in rows if row["group_json"] and row["group_json"] != "{}"]


def save_hole_group(conn: sqlite3.Connection, set_id: str, rev: int, group_id: str,
                    group: "HoleGroup", actor: str = "") -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_hole_groups
            (set_id, rev, group_id, group_json, badge, basis, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, rev, group_id) DO UPDATE SET
            group_json = excluded.group_json, badge = excluded.badge, basis = excluded.basis,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (set_id, int(rev), group_id, group.model_dump_json(), group.badge, group.basis, actor, now),
    )
    conn.commit()


def delete_hole_group(conn: sqlite3.Connection, set_id: str, rev: int, group_id: str) -> None:
    """Remove a group. Its stations keep their access classes — classifying a hole and deciding
    which spread works it are two different acts, and undoing one must not undo the other."""
    conn.execute(
        "DELETE FROM client_boq_hole_groups WHERE set_id = ? AND rev = ? AND group_id = ?",
        (set_id, int(rev), group_id),
    )
    conn.execute(
        "UPDATE client_boq_station_classes SET group_id = '' WHERE set_id = ? AND group_id = ?",
        (set_id, group_id),
    )
    conn.commit()


def load_sheet_registrations(conn: sqlite3.Connection, set_id: str) -> list["SheetRegistration"]:
    """Every registered sheet for a set, in a stable order. A stored-but-broken registration is
    returned too — georef refuses to crop from it and names why, and hiding it here would turn
    that refusal into a silent absence."""
    from client_boq.boq.georef import SheetRegistration
    rows = conn.execute(
        """
        SELECT registration_json, confirmed_by FROM client_boq_sheet_registrations
        WHERE set_id = ? ORDER BY sheet
        """,
        (set_id,),
    ).fetchall()
    out = []
    for row in rows:
        if not row["registration_json"] or row["registration_json"] == "{}":
            continue
        registration = SheetRegistration.model_validate_json(row["registration_json"])
        # The column is authoritative, the same way the station schedule's is: the JSON blob may
        # carry whatever confirmed_by it was saved with, but confirm-not-sticky lives in the row.
        registration.confirmed_by = row["confirmed_by"]
        out.append(registration)
    return out


def save_sheet_registration(conn: sqlite3.Connection, set_id: str,
                            registration: "SheetRegistration", *,
                            confirmed: bool = False, actor: str = "") -> None:
    """Upsert one sheet's registration. Confirm is not sticky — editing a mark re-saves with
    confirmed=False, because the thing somebody checked is no longer the thing on the screen."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_sheet_registrations
            (set_id, sheet, registration_json, confirmed_by, confirmed_at, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, sheet) DO UPDATE SET
            registration_json = excluded.registration_json,
            confirmed_by = excluded.confirmed_by, confirmed_at = excluded.confirmed_at,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (set_id, registration.sheet, registration.model_dump_json(),
         actor if confirmed else "", now if confirmed else None, actor, now),
    )
    conn.commit()


def delete_sheet_registration(conn: sqlite3.Connection, set_id: str, sheet: str) -> None:
    conn.execute(
        "DELETE FROM client_boq_sheet_registrations WHERE set_id = ? AND sheet = ?",
        (set_id, sheet),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# The costing model — the library's, and a tender's own copy of it
# ---------------------------------------------------------------------------
LIBRARY_MODEL_ID = "default"


def load_library_model(conn: sqlite3.Connection) -> "CostingModel":
    """The company's costing model. Seeded from the reference template on first read.

    Seeded rather than required: a company that has never opened the model screen should still be
    able to price something, and the defaults are a working model rather than an empty one.
    """
    from client_boq.boq.model import CostingModel, default_model
    row = conn.execute(
        "SELECT model_json FROM client_boq_costing_models WHERE model_id = ?",
        (LIBRARY_MODEL_ID,),
    ).fetchone()
    if row is None or not row["model_json"] or row["model_json"] == "{}":
        return default_model()
    return CostingModel.model_validate_json(row["model_json"])


def save_library_model(conn: sqlite3.Connection, model: "CostingModel", actor: str = "") -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_costing_models (model_id, name, model_json, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(model_id) DO UPDATE SET
            name = excluded.name, model_json = excluded.model_json,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (LIBRARY_MODEL_ID, model.name, model.model_dump_json(), actor, now),
    )
    conn.commit()


def load_set_model(conn: sqlite3.Connection, set_id: str) -> Optional["CostingModel"]:
    """This tender's own model, or ``None`` meaning it is still using the library's."""
    from client_boq.boq.model import CostingModel
    row = conn.execute(
        "SELECT model_json FROM client_boq_set_costing_model WHERE set_id = ?", (set_id,)
    ).fetchone()
    if row is None or not row["model_json"] or row["model_json"] == "{}":
        return None
    return CostingModel.model_validate_json(row["model_json"])


def save_set_model(conn: sqlite3.Connection, set_id: str, model: "CostingModel",
                   based_on: str = LIBRARY_MODEL_ID, actor: str = "") -> None:
    """Copy-on-write. Writing here is what makes this tender's model its own from now on."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_set_costing_model
            (set_id, model_json, based_on, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(set_id) DO UPDATE SET
            model_json = excluded.model_json, based_on = excluded.based_on,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        (set_id, model.model_dump_json(), based_on, actor, now),
    )
    conn.commit()


def clear_set_model(conn: sqlite3.Connection, set_id: str) -> None:
    """Put this tender back on the library's model. The only way back once it has diverged."""
    conn.execute("DELETE FROM client_boq_set_costing_model WHERE set_id = ?", (set_id,))
    conn.commit()


def load_costing_state(conn: sqlite3.Connection, set_id: str, rev: int) -> dict:
    """What a person has decided about this tender's costing: mappings, rates, verdicts."""
    row = conn.execute(
        """
        SELECT mapping_json, submitted_json, verdicts_json, updated_by, updated_at
        FROM client_boq_costing_state WHERE set_id = ? AND rev = ?
        """,
        (set_id, int(rev)),
    ).fetchone()
    if row is None:
        return {"mapping": {}, "submitted": {}, "verdicts": {},
                "updated_by": "", "updated_at": None}
    return {
        "mapping": json.loads(row["mapping_json"] or "{}"),
        "submitted": {k: float(v) for k, v in json.loads(row["submitted_json"] or "{}").items()},
        "verdicts": json.loads(row["verdicts_json"] or "{}"),
        "updated_by": row["updated_by"], "updated_at": row["updated_at"],
    }


def save_costing_state(conn: sqlite3.Connection, set_id: str, rev: int, *,
                       mapping: Optional[dict] = None, submitted: Optional[dict] = None,
                       verdicts: Optional[dict] = None, actor: str = "") -> dict:
    """Merge into what is already recorded. Returns the state as it now stands.

    A merge rather than a replace because these three arrive from three different screens, and a
    caller that only knows about rates must not wipe somebody's register verdicts.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current = load_costing_state(conn, set_id, rev)
    merged = {
        "mapping": {**current["mapping"], **(mapping or {})},
        "submitted": {**current["submitted"], **(submitted or {})},
        "verdicts": {**current["verdicts"], **(verdicts or {})},
    }
    conn.execute(
        """
        INSERT INTO client_boq_costing_state
            (set_id, rev, mapping_json, submitted_json, verdicts_json, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, rev) DO UPDATE SET
            mapping_json = excluded.mapping_json, submitted_json = excluded.submitted_json,
            verdicts_json = excluded.verdicts_json, updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (set_id, int(rev), json.dumps(merged["mapping"]), json.dumps(merged["submitted"]),
         json.dumps(merged["verdicts"]), actor, now),
    )
    conn.commit()
    return {**merged, "updated_by": actor, "updated_at": now}


def clear_submitted_rate(conn: sqlite3.Connection, set_id: str, rev: int, full_ref: str) -> None:
    """Forget a typed rate and go back to the rounded proposal. The only undo that means anything —
    a proposal cannot be deleted, it is recomputed every time."""
    state = load_costing_state(conn, set_id, rev)
    state["submitted"].pop(full_ref, None)
    conn.execute(
        """
        INSERT INTO client_boq_costing_state (set_id, rev, submitted_json)
        VALUES (?, ?, ?)
        ON CONFLICT(set_id, rev) DO UPDATE SET submitted_json = excluded.submitted_json
        """,
        (set_id, int(rev), json.dumps(state["submitted"])),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# The sweep, and what a rate is ticked as covering
# ---------------------------------------------------------------------------
def load_sweep(conn: sqlite3.Connection, set_id: str, rev: int) -> "UnbilledSweep":
    """The costs the contract makes yours that no bill item asks for, and how each is routed."""
    from client_boq.boq.unbilled import UnbilledCost, UnbilledSweep
    rows = conn.execute(
        """
        SELECT key, label, source, amount, route, target_ref, reason, decided_by
        FROM client_boq_sweep_costs WHERE set_id = ? AND rev = ? ORDER BY key
        """,
        (set_id, int(rev)),
    ).fetchall()
    return UnbilledSweep(set_id=set_id, rev=int(rev), costs=[
        UnbilledCost(key=r["key"], label=r["label"], source=r["source"], amount=r["amount"],
                     route=r["route"], target_ref=r["target_ref"], reason=r["reason"],
                     decided_by=r["decided_by"])
        for r in rows
    ])


def save_sweep_cost(conn: sqlite3.Connection, set_id: str, rev: int, cost: "UnbilledCost",
                    actor: str = "") -> None:
    """Add a cost to the sweep, or route one already there.

    ``decided_by`` is only stamped once a route is chosen. An unrouted cost has nobody's name on it
    because nobody has decided anything about it yet — which is exactly the state the gate refuses.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_sweep_costs
            (set_id, rev, key, label, source, amount, route, target_ref, reason, decided_by,
             decided_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, rev, key) DO UPDATE SET
            label = excluded.label, source = excluded.source, amount = excluded.amount,
            route = excluded.route, target_ref = excluded.target_ref, reason = excluded.reason,
            decided_by = excluded.decided_by, decided_at = excluded.decided_at
        """,
        (set_id, int(rev), cost.key, cost.label, cost.source, cost.amount, cost.route,
         cost.target_ref, cost.reason, actor if cost.route else "", now if cost.route else None),
    )
    conn.commit()


def load_coverage_ticks(conn: sqlite3.Connection, set_id: str, rev: int) -> dict[str, dict[str, dict]]:
    """full_ref → head key → the tick. Only ticks are stored.

    The list of heads is re-derived from the measurement rules on every request, so an addendum that
    rewrites a clause changes the list without this table knowing — and a tick against a head that no
    longer exists simply stops being read rather than propping up a rate nobody checked.
    """
    rows = conn.execute(
        """
        SELECT full_ref, head_key, basis_key, ticked, ticked_by, ticked_at
        FROM client_boq_coverage_ticks WHERE set_id = ? AND rev = ?
        """,
        (set_id, int(rev)),
    ).fetchall()
    out: dict[str, dict[str, dict]] = {}
    for row in rows:
        out.setdefault(row["full_ref"], {})[row["head_key"]] = {
            "ticked": bool(row["ticked"]), "ticked_by": row["ticked_by"],
            "ticked_at": row["ticked_at"],
            # The cost basis the person named as discharging this head, or "" for a tick given
            # before the column existed — which reads as "asserted, no cost named", exactly what a
            # tick meant then.
            "basis_key": row["basis_key"] if "basis_key" in row.keys() else "",
        }
    return out


def save_coverage_tick(conn: sqlite3.Connection, set_id: str, rev: int, full_ref: str,
                       head_key: str, ticked: bool, actor: str = "",
                       basis_key: str = "") -> None:
    """Record that a person says their build-up does (or no longer does) carry this head.

    A machine cannot know what somebody put in their number, so there is no badge column here and no
    way for a model to write this row — the same structural refusal ``/review/approve`` makes for a
    clause verdict.

    ``basis_key`` names the build-up basis that carries it, and is what turns the tick from a belief
    into a link. Optional: a tick with no cost named is still a tick, and is exactly what every tick
    was before the column existed. What it buys is that the claim becomes CHECKABLE — a head named
    against a basis this item's rate does not draw on is an obligation claimed against money that is
    not in the rate, and that is arithmetic rather than memory.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_coverage_ticks
            (set_id, rev, full_ref, head_key, basis_key, ticked, ticked_by, ticked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, rev, full_ref, head_key) DO UPDATE SET
            basis_key = excluded.basis_key,
            ticked = excluded.ticked, ticked_by = excluded.ticked_by,
            ticked_at = excluded.ticked_at
        """,
        # Unticking clears the basis with the name and the date: the link was part of the claim,
        # and a withdrawn claim must not leave its evidence behind looking live.
        (set_id, int(rev), full_ref, head_key, basis_key if ticked else "", 1 if ticked else 0,
         actor if ticked else "", now if ticked else None),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Register + the review→estimate gate
# ---------------------------------------------------------------------------
def save_register(conn: sqlite3.Connection, register: DepartureRegister) -> None:
    """Persist the register to the tables (source of truth). Preserves the existing ``approved`` flag
    — assembling/re-running the review never silently re-opens or closes the gate; only the approve
    endpoint moves it."""
    conn.execute(
        """
        INSERT INTO client_boq_review_registers (set_id, register_json)
        VALUES (:set_id, :json)
        ON CONFLICT(set_id) DO UPDATE SET register_json = excluded.register_json
        """,
        {"set_id": register.set_id, "json": register.model_dump_json()},
    )
    conn.commit()


def load_register(conn: sqlite3.Connection, set_id: str) -> Optional[DepartureRegister]:
    """The persisted register for ``set_id`` (tables — the source of truth), or None. The stored
    ``approved`` column wins over whatever the JSON blob happens to carry, so the gate is always read
    from the authoritative flag."""
    row = conn.execute(
        "SELECT register_json, approved FROM client_boq_review_registers WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["register_json"] or row["register_json"] == "{}":
        return None
    reg = DepartureRegister.model_validate_json(row["register_json"])
    reg.approved = bool(row["approved"])
    return reg


def review_is_approved(conn: sqlite3.Connection, set_id: str) -> bool:
    """True when the review register for ``set_id`` is human-approved — the estimate gate."""
    row = conn.execute(
        "SELECT approved FROM client_boq_review_registers WHERE set_id = ?", (set_id,)
    ).fetchone()
    return bool(row and row["approved"])


def set_review_approved(conn: sqlite3.Connection, set_id: str, approved: bool) -> None:
    """Record the human approval decision on the register (the gate action). Upserts the row so it is
    safe even if called before a register was assembled (approved with no register is still a no-op
    for the estimate, which also requires a register)."""
    conn.execute(
        """
        INSERT INTO client_boq_review_registers (set_id, approved, approved_at)
        VALUES (?, ?, CASE WHEN ? THEN datetime('now') ELSE NULL END)
        ON CONFLICT(set_id) DO UPDATE SET
            approved = excluded.approved,
            approved_at = excluded.approved_at
        """,
        (set_id, 1 if approved else 0, 1 if approved else 0),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# INGEST — the split manifest and its gate (the FIRST gate of the workflow)
# ---------------------------------------------------------------------------
def save_manifest(conn: sqlite3.Connection, manifest: SplitManifest) -> None:
    """Persist a split manifest, preserving its approval flag. Re-inspecting or re-planning a
    document never silently re-opens or closes the gate — only ``approve_manifest`` moves it,
    exactly as ``save_register`` treats the review gate."""
    conn.execute(
        """
        INSERT INTO client_boq_manifests (set_id, manifest_json, tier)
        VALUES (:set_id, :json, :tier)
        ON CONFLICT(set_id) DO UPDATE SET
            manifest_json = excluded.manifest_json,
            tier = excluded.tier
        """,
        {"set_id": manifest.set_id, "json": manifest.model_dump_json(), "tier": manifest.tier},
    )
    conn.commit()


def load_manifest(conn: sqlite3.Connection, set_id: str) -> Optional[SplitManifest]:
    """The persisted manifest for ``set_id``, or None. The stored ``approved`` column wins over
    the JSON blob, so the gate is always read from the authoritative flag."""
    row = conn.execute(
        "SELECT manifest_json, approved FROM client_boq_manifests WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["manifest_json"] or row["manifest_json"] == "{}":
        return None
    manifest = SplitManifest.model_validate_json(row["manifest_json"])
    manifest.approved = bool(row["approved"])
    return manifest


def manifest_is_approved(conn: sqlite3.Connection, set_id: str) -> bool:
    """True when the split manifest for ``set_id`` is human-approved — the ingest gate."""
    row = conn.execute(
        "SELECT approved FROM client_boq_manifests WHERE set_id = ?", (set_id,)
    ).fetchone()
    return bool(row and row["approved"])


def approve_manifest(conn: sqlite3.Connection, set_id: str, approved: bool) -> None:
    """Record the decision on the manifest — the ONLY writer of the ingest gate flag.

    Usually a person's, via ``/ingest/manifest/approve``. A folder ingest sets it automatically
    because there are no page ranges to confirm, and says so in the manifest's ``tier_reason``
    rather than leaving a green tick that implies somebody looked.
    """
    conn.execute(
        """
        INSERT INTO client_boq_manifests (set_id, approved, approved_at)
        VALUES (?, ?, CASE WHEN ? THEN datetime('now') ELSE NULL END)
        ON CONFLICT(set_id) DO UPDATE SET
            approved = excluded.approved,
            approved_at = excluded.approved_at
        """,
        (set_id, 1 if approved else 0, 1 if approved else 0),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# INGEST — the split parts and their interpreted context
# ---------------------------------------------------------------------------
def upsert_document(conn: sqlite3.Connection, set_id: str, *, doc_id: str, filename: str,
                    kind: str = models.DOC_BASE, ref: str = "", note: str = "") -> int:
    """Record a file entering the set and return its arrival sequence.

    ``seq`` orders the history and is what "the tender as at Addendum 1" is replayed against.
    Re-recording the same ``doc_id`` keeps its original position, so re-splitting a document
    never reshuffles the timeline.
    """
    # One statement, not a SELECT followed by an INSERT. Ingests run on a thread pool, so two jobs
    # touching the same set — a double-clicked upload, the same folder sent twice — could both see
    # "no row yet" and both insert, and the loser died on a raw UNIQUE-constraint error with no
    # indication of what a person had actually done wrong.
    #
    # The seq sub-select keeps the promise in the docstring: an existing document holds its original
    # position, and only a genuinely new one takes the next number.
    conn.execute(
        """
        INSERT INTO client_boq_documents (set_id, doc_id, filename, kind, ref, seq, note)
        VALUES (?, ?, ?, ?, ?,
                COALESCE(
                    (SELECT seq FROM client_boq_documents WHERE set_id = ? AND doc_id = ?),
                    (SELECT COALESCE(MAX(seq), -1) + 1 FROM client_boq_documents WHERE set_id = ?)
                ), ?)
        ON CONFLICT(set_id, doc_id) DO UPDATE SET
            filename = excluded.filename, kind = excluded.kind,
            ref = excluded.ref, note = excluded.note
        """,
        (set_id, doc_id, filename, kind, ref, set_id, doc_id, set_id, note),
    )
    conn.commit()
    row = conn.execute(
        "SELECT seq FROM client_boq_documents WHERE set_id = ? AND doc_id = ?", (set_id, doc_id)
    ).fetchone()
    return int(row["seq"]) if row else 0


def list_documents(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    """Every document that entered the set, in arrival order. These are the history's tabs.

    Each row carries a derived ``applied``: whether this document has actually produced a part
    revision yet. ``/ingest/document`` deliberately commits nothing — it proposes a mapping and
    stops at the gate — so a received addendum and an applied one are different states, and only
    the applied one has changed what is being priced. Derived from the revision rows rather than
    stored as a flag, for the same reason the operative revision is (``load_parts``): a flag can
    drift, a join cannot.
    """
    rows = conn.execute(
        "SELECT doc_id, filename, kind, ref, seq, received_at, note "
        "FROM client_boq_documents WHERE set_id = ? ORDER BY seq",
        (set_id,),
    ).fetchall()
    applied = {
        row["doc_id"] for row in conn.execute(
            "SELECT DISTINCT doc_id FROM client_boq_part_revisions WHERE set_id = ?", (set_id,)
        )
    }
    return [{**dict(row), "applied": row["doc_id"] in applied} for row in rows]


def save_parts(conn: sqlite3.Connection, set_id: str, parts: list[PartSpec],
               pdf_paths: Optional[dict[str, str]] = None, *,
               doc_id: str = "doc-0", rev: int = 0) -> None:
    """Write a revision of every part in ``parts``.

    Two different operations share this, and the difference matters:

    * **Re-splitting the same document** (the manifest was edited) writes over the SAME ``rev``.
      A manifest edit is a better reading of one document, not a new document, and re-split churn
      would fill the history with noise. Parts that no longer exist in the manifest are dropped,
      or the review would read a page range that was cut away.
    * **A new document** (a correction or an addendum) is written at a HIGHER ``rev``, leaving
      every earlier revision untouched. Nothing is ever destroyed — Rev 0 survives Rev 1.
    """
    paths = pdf_paths or {}
    keep = {part.part_id for part in parts}

    if rev == 0:
        # Re-cut of the original document: parts dropped from the manifest go, with their history.
        placeholders = ",".join("?" for _ in keep) or "''"
        conn.execute(
            f"DELETE FROM client_boq_parts WHERE set_id = ? AND part_id NOT IN ({placeholders})",
            (set_id, *keep),
        )
        conn.execute(
            f"DELETE FROM client_boq_part_revisions WHERE set_id = ? AND part_id NOT IN ({placeholders})",
            (set_id, *keep),
        )

    for part in parts:
        conn.execute(
            """
            INSERT INTO client_boq_parts (set_id, part_id, n, abbr, slug, title, category)
            VALUES (:set_id, :part_id, :n, :abbr, :slug, :title, :category)
            ON CONFLICT(set_id, part_id) DO UPDATE SET
                n = excluded.n, abbr = excluded.abbr, slug = excluded.slug,
                title = excluded.title, category = excluded.category
            """,
            {"set_id": set_id, "part_id": part.part_id, "n": part.n, "abbr": part.abbr,
             "slug": part.slug, "title": part.title, "category": part.category},
        )
        conn.execute(
            """
            INSERT INTO client_boq_part_revisions
                (set_id, part_id, rev, doc_id, start_page, end_page, scanned, source_doc, pdf_path)
            VALUES (:set_id, :part_id, :rev, :doc_id, :start, :end, :scanned, :source_doc, :pdf_path)
            ON CONFLICT(set_id, part_id, rev) DO UPDATE SET
                doc_id = excluded.doc_id, start_page = excluded.start_page,
                end_page = excluded.end_page, scanned = excluded.scanned,
                source_doc = excluded.source_doc, pdf_path = excluded.pdf_path
            """,
            {"set_id": set_id, "part_id": part.part_id, "rev": rev, "doc_id": doc_id,
             "start": part.start, "end": part.end, "scanned": 1 if part.scanned else 0,
             "source_doc": part.source_doc, "pdf_path": paths.get(part.part_id, "")},
        )
    conn.commit()


def save_part_context(conn: sqlite3.Connection, set_id: str, part_id: str,
                      context: PartContext, *, rev: Optional[int] = None) -> None:
    """Attach one part revision's interpreted context. Per-part so a failure to interpret ONE
    part is a flagged card, never a failed job (the module's no-silent-drops invariant).

    Defaults to the operative revision, since that is the one just cut.
    """
    if rev is None:
        row = conn.execute(
            "SELECT MAX(rev) AS r FROM client_boq_part_revisions WHERE set_id = ? AND part_id = ?",
            (set_id, part_id),
        ).fetchone()
        rev = int(row["r"]) if row and row["r"] is not None else 0
    conn.execute(
        "UPDATE client_boq_part_revisions SET context_json = ? "
        "WHERE set_id = ? AND part_id = ? AND rev = ?",
        (context.model_dump_json(), set_id, part_id, rev),
    )
    conn.commit()


def _rows_to_parts(rows) -> list[tuple[PartSpec, str, PartContext]]:
    out: list[tuple[PartSpec, str, PartContext]] = []
    for row in rows:
        spec = PartSpec(
            n=row["n"], abbr=row["abbr"], slug=row["slug"], title=row["title"],
            start=row["start_page"], end=row["end_page"], category=row["category"],
            scanned=bool(row["scanned"]), source_doc=row["source_doc"], rev=row["rev"],
        )
        blob = row["context_json"]
        context = (
            PartContext.model_validate_json(blob) if blob and blob != "{}"
            else PartContext(part_id=row["part_id"], title=row["title"], category=row["category"])
        )
        out.append((spec, row["pdf_path"] or "", context))
    return out


def load_parts(conn: sqlite3.Connection, set_id: str) -> list[tuple[PartSpec, str, PartContext]]:
    """The OPERATIVE view: every part in document order, at its latest revision.

    This is the only thing the review and the estimate ever read. A superseded revision is kept
    for history and comparison but never priced — you bid the current documents, not an
    amended-away one. The operative revision is derived as the highest ``rev`` rather than stored
    as a flag, so it cannot drift out of step with the rows.
    """
    rows = conn.execute(
        """
        SELECT p.part_id, p.n, p.abbr, p.slug, p.title, p.category,
               r.rev, r.start_page, r.end_page, r.scanned, r.source_doc, r.pdf_path, r.context_json
        FROM client_boq_parts p
        JOIN client_boq_part_revisions r
          ON r.set_id = p.set_id AND r.part_id = p.part_id
         AND r.rev = (SELECT MAX(r2.rev) FROM client_boq_part_revisions r2
                      WHERE r2.set_id = p.set_id AND r2.part_id = p.part_id)
        WHERE p.set_id = ?
        ORDER BY p.n
        """,
        (set_id,),
    ).fetchall()
    return _rows_to_parts(rows)


def load_parts_as_at(conn: sqlite3.Connection, set_id: str, seq: int
                     ) -> list[tuple[PartSpec, str, PartContext]]:
    """The set as it stood after the document at arrival position ``seq`` — a history tab.

    Reconstructed rather than stored: each part's latest revision introduced at or before that
    point. Representing this by duplicating every part per event would mean storing the 154
    unchanged documents of a real tender once per addendum.
    """
    rows = conn.execute(
        """
        SELECT p.part_id, p.n, p.abbr, p.slug, p.title, p.category,
               r.rev, r.start_page, r.end_page, r.scanned, r.source_doc, r.pdf_path, r.context_json
        FROM client_boq_parts p
        JOIN client_boq_part_revisions r
          ON r.set_id = p.set_id AND r.part_id = p.part_id
         AND r.rev = (
             SELECT MAX(r2.rev) FROM client_boq_part_revisions r2
             JOIN client_boq_documents d2 ON d2.set_id = r2.set_id AND d2.doc_id = r2.doc_id
             WHERE r2.set_id = p.set_id AND r2.part_id = p.part_id AND d2.seq <= :seq
         )
        WHERE p.set_id = :set_id
        ORDER BY p.n
        """,
        {"set_id": set_id, "seq": seq},
    ).fetchall()
    return _rows_to_parts(rows)


# ---------------------------------------------------------------------------
# RFIs — the conversation with the client
# ---------------------------------------------------------------------------
def _rfi_from_row(row) -> RFIItem:
    return RFIItem(
        rfi_id=row["rfi_id"], number=row["number"], origin=row["origin"],
        register_item=row["register_item"], part_id=row["part_id"], clause=row["clause"],
        page=row["page"], question=row["question"], context=row["context"],
        status=row["status"], batch_id=row["batch_id"], answer=row["answer"],
        answered_by=row["answered_by"], raised_at=row["raised_at"],
        answered_at=row["answered_at"],
    )


def open_register_rfi_id(conn: sqlite3.Connection, set_id: str, register_item: int) -> str:
    """The id of the OPEN question already raised from register line ``register_item``, or ``""``.

    One register line asks the client one question. Re-recording a `query` verdict on the same
    line — pressing Query twice, or query → dismissed → query, and `Register.tsx` posts one
    decision per click with no clear-verdict path — used to raise `rfi-002`, `rfi-003`, … each
    identical. `open_rfi_count` then over-reported, which drives the routing proposal's
    open-queries note, the desk card's blocking sentence and the freeze gate, and the batch letter
    carried the same question to the client N times.

    Only an OPEN one is reused. A question already ANSWERED, WITHDRAWN or OVERTAKEN is a closed
    piece of history: asking again after an answer is a new question and must get a new id.
    """
    marks = ",".join("?" for _ in models.RFI_OPEN)
    row = conn.execute(
        f"SELECT rfi_id FROM client_boq_rfi_items WHERE set_id = ? AND origin = ? "
        f"AND register_item = ? AND status IN ({marks}) ORDER BY rfi_id LIMIT 1",
        (set_id, models.RFI_FROM_REGISTER, register_item, *sorted(models.RFI_OPEN)),
    ).fetchone()
    return row["rfi_id"] if row else ""


def save_rfi(conn: sqlite3.Connection, set_id: str, item: RFIItem) -> RFIItem:
    """Raise or update one question. Returns it with its id assigned.

    An id-less question from a register line REUSES the open question that line already raised —
    see :func:`open_register_rfi_id`. Every other id-less question is genuinely new.
    """
    if not item.rfi_id and item.origin == models.RFI_FROM_REGISTER and item.register_item:
        existing = open_register_rfi_id(conn, set_id, item.register_item)
        if existing:
            # Reuse the id AND the lifecycle. The upsert writes every column, so taking only the id
            # would reset a question already in a sent batch back to `draft` with no `batch_id` —
            # trading a duplicate for a lost one. A question the client has already been asked also
            # keeps its wording: what went out in the letter is a fact, not a draft.
            was = conn.execute(
                "SELECT number, status, batch_id, question FROM client_boq_rfi_items "
                "WHERE set_id = ? AND rfi_id = ?", (set_id, existing)).fetchone()
            keep = {"rfi_id": existing, "number": was["number"], "status": was["status"],
                    "batch_id": was["batch_id"]}
            if was["status"] != models.RFI_DRAFT:
                keep["question"] = was["question"]
            item = item.model_copy(update=keep)
    if not item.rfi_id:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM client_boq_rfi_items WHERE set_id = ?", (set_id,)
        ).fetchone()["n"]
        item = item.model_copy(update={"rfi_id": f"rfi-{count + 1:03d}"})
    conn.execute(
        """
        INSERT INTO client_boq_rfi_items
            (set_id, rfi_id, number, origin, register_item, part_id, clause, page, question,
             context, status, batch_id, answer, answered_by, answered_at)
        VALUES (:set_id, :rfi_id, :number, :origin, :register_item, :part_id, :clause, :page,
                :question, :context, :status, :batch_id, :answer, :answered_by, :answered_at)
        ON CONFLICT(set_id, rfi_id) DO UPDATE SET
            number = excluded.number, origin = excluded.origin,
            register_item = excluded.register_item, part_id = excluded.part_id,
            clause = excluded.clause, page = excluded.page, question = excluded.question,
            context = excluded.context, status = excluded.status, batch_id = excluded.batch_id,
            answer = excluded.answer, answered_by = excluded.answered_by,
            answered_at = excluded.answered_at
        """,
        {"set_id": set_id, **item.model_dump(exclude={"raised_at"})},
    )
    conn.commit()
    return item


def load_rfis(conn: sqlite3.Connection, set_id: str) -> list[RFIItem]:
    """Every question raised on this set, oldest first."""
    rows = conn.execute(
        "SELECT * FROM client_boq_rfi_items WHERE set_id = ? ORDER BY raised_at, rfi_id",
        (set_id,),
    ).fetchall()
    return [_rfi_from_row(row) for row in rows]


def open_rfi_count(conn: sqlite3.Connection, set_id: str) -> int:
    """How many questions are still waiting on the client.

    This is the number the freeze gate has to see reach zero — by an answer or by a stated
    assumption — and the number a UI must keep visible, since queries deliberately do not block
    review approval.
    """
    marks = ",".join("?" for _ in models.RFI_OPEN)
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM client_boq_rfi_items WHERE set_id = ? AND status IN ({marks})",
        (set_id, *sorted(models.RFI_OPEN)),
    ).fetchone()
    return int(row["n"])


def withdraw_rfi(conn: sqlite3.Connection, set_id: str, rfi_id: str) -> Optional[RFIItem]:
    """Take a question out of the build it is queued in. Returns the withdrawn item, or None.

    A status change, not a delete — nothing in this module is ever destroyed, and "we asked and
    then thought better of it" is part of the record. The question also stops counting as open,
    which is right: we are no longer waiting on the client for it.

    Refuses once the question has been sent. At that point the client has it, and pretending
    otherwise on our side would put the register out of step with what actually went out; the
    honest route for a sent question is an answer or an overtaking amendment.
    """
    row = conn.execute(
        "SELECT * FROM client_boq_rfi_items WHERE set_id = ? AND rfi_id = ?", (set_id, rfi_id)
    ).fetchone()
    if row is None:
        return None
    item = _rfi_from_row(row)
    if item.status != models.RFI_DRAFT:
        raise ValueError(
            f"Question {rfi_id} is {item.status}, not a draft — it cannot be withdrawn from a "
            f"build it has already left."
        )
    conn.execute(
        "UPDATE client_boq_rfi_items SET status = ?, batch_id = '' WHERE set_id = ? AND rfi_id = ?",
        (models.RFI_WITHDRAWN, set_id, rfi_id),
    )
    conn.commit()
    return item.model_copy(update={"status": models.RFI_WITHDRAWN, "batch_id": ""})


def save_rfi_batch(conn: sqlite3.Connection, set_id: str, batch: RFIBatch) -> None:
    conn.execute(
        """
        INSERT INTO client_boq_rfi_batches (set_id, batch_id, ref, sent_at, letter_md)
        VALUES (:set_id, :batch_id, :ref, :sent_at, :letter_md)
        ON CONFLICT(set_id, batch_id) DO UPDATE SET
            ref = excluded.ref, sent_at = excluded.sent_at, letter_md = excluded.letter_md
        """,
        {"set_id": set_id, "batch_id": batch.batch_id, "ref": batch.ref,
         "sent_at": batch.sent_at, "letter_md": batch.letter_md},
    )
    conn.commit()


def load_rfi_batches(conn: sqlite3.Connection, set_id: str) -> list[RFIBatch]:
    rows = conn.execute(
        "SELECT batch_id, ref, sent_at, letter_md FROM client_boq_rfi_batches "
        "WHERE set_id = ? ORDER BY batch_id",
        (set_id,),
    ).fetchall()
    items = load_rfis(conn, set_id)
    out = []
    for row in rows:
        out.append(RFIBatch(
            batch_id=row["batch_id"], ref=row["ref"], sent_at=row["sent_at"],
            letter_md=row["letter_md"],
            items=[i for i in items if i.batch_id == row["batch_id"]],
        ))
    return out


def overtake_rfis_for_parts(conn: sqlite3.Connection, set_id: str,
                            part_ids: list[str], doc_ref: str) -> list[str]:
    """Close open questions whose part has just been amended.

    An addendum that rewrites the clause you asked about has answered you, whether or not anyone
    wrote back. Leaving the question open would have you chasing a reply that is never coming, and
    would keep a stale item in the count the freeze gate reads.
    """
    if not part_ids:
        return []
    marks = ",".join("?" for _ in models.RFI_OPEN)
    parts = ",".join("?" for _ in part_ids)
    rows = conn.execute(
        f"SELECT rfi_id FROM client_boq_rfi_items WHERE set_id = ? AND status IN ({marks}) "
        f"AND part_id IN ({parts})",
        (set_id, *sorted(models.RFI_OPEN), *part_ids),
    ).fetchall()
    ids = [row["rfi_id"] for row in rows]
    for rfi_id in ids:
        conn.execute(
            "UPDATE client_boq_rfi_items SET status = ?, answered_by = ?, "
            "answered_at = datetime('now'), answer = ? WHERE set_id = ? AND rfi_id = ?",
            (models.RFI_OVERTAKEN, doc_ref,
             f"Overtaken by {doc_ref}, which amended the document this question was about.",
             set_id, rfi_id),
        )
    conn.commit()
    return ids


# The columns a HUMAN owns on a register line. Everything else on the line is the stages' to
# rewrite on a re-run; these five are not, because nothing but a person can produce them.
_HUMAN_COLUMNS = ("status", "decided_by", "register_status", "client_response", "contractor_response")


def _line_identity(item: models.DepartureItem) -> tuple:
    """What a register line is ABOUT — never where it sits.

    ``item.item`` is a position assigned by s07 at assembly time, so it moves the moment a clause
    is added or dropped. The stable identity is the departure itself: which check produced it,
    which criterion it is against, which clause it cites, and (for the s04–s06 findings, which
    carry neither) the finding's own wording.
    """
    anchored = bool(item.criterion_id) or bool(item.clause)
    tail = "" if anchored else " ".join((item.rationale or "").lower().split())
    return (item.source, item.criterion_id, item.clause, item.kind, tail)


def carry_human_decisions(
    previous: Optional[models.DepartureRegister], fresh: models.DepartureRegister,
) -> list[str]:
    """Move the human's columns from ``previous`` onto the matching lines of ``fresh``, in place.

    **A RE-RUN OF THE REVIEW DESTROYED EVERY VERDICT AND LEFT THE GATE SAYING APPROVED.** The
    register is one JSON blob and the re-run replaced it wholesale, so every ``confirmed`` went
    back to ``candidate``, every ``decided_by`` emptied, and every line of negotiation text the
    operator had typed was gone — while ``client_boq_review_registers.approved`` still read 1,
    because ``save_register`` correctly never touches it. The result is the worst state the gate
    can be in: APPROVED over a register nobody has read.

    Probed before the fix::

        after approve   : {'12.3': ('confirmed', 'R. Lam', 'we press this'), '14.1': ('dismissed', ...)}
        after RE-review : {'12.3': ('candidate', '', ''),                    '14.1': ('candidate', ...)}

    Only a HUMAN verdict is carried. A machine status (candidate, rule_flagged, uncovered,
    unresolved, citation_failed) is the stages' answer and the fresh run's is the current one —
    re-reading the document is the entire point of re-running.

    Returns the verdicts that could NOT be carried, one readable sentence each, because that is
    the number the operator has to act on. Three causes, none of them silent:

    * the line is gone — the re-read no longer produces that departure at all;
    * its identity is ambiguous — two lines share one identity on either side, and a verdict
      attached to the wrong line is far worse than a verdict asked for again;
    * (implicitly) the wording of an unanchored s04–s06 finding changed, which makes it a
      different finding.

    Pure: no DB, no gate. The caller decides what an uncarried verdict means for the gate flag —
    see :func:`client_boq.review.run.run_review`.
    """
    if previous is None:
        return []

    decided = [it for it in previous.items if it.status in models.HUMAN_VERDICTS
               or it.client_response or it.contractor_response]
    if not decided:
        return []

    def _index(items) -> tuple[dict, set]:
        seen: dict = {}
        dupes: set = set()
        for it in items:
            key = _line_identity(it)
            if key in seen:
                dupes.add(key)
            seen[key] = it
        return seen, dupes

    old_by_key, old_dupes = _index(previous.items)
    new_by_key, new_dupes = _index(fresh.items)
    ambiguous = old_dupes | new_dupes

    lost: list[str] = []
    for was in decided:
        key = _line_identity(was)
        target = new_by_key.get(key)
        label = f"item {was.item}" + (f" ({was.clause})" if was.clause else "")
        if key in ambiguous:
            lost.append(f"{label} marked {was.status!r} — two lines share its identity, so the "
                        f"verdict cannot be attached to one of them with confidence")
            continue
        if target is None:
            lost.append(f"{label} marked {was.status!r} — the re-read no longer produces this line")
            continue
        if (was.status in models.HUMAN_VERDICTS
                and target.status == models.STATUS_CITATION_FAILED):
            # The fresh run could not find the quote this line rests on. `/review/approve` refuses
            # to confirm such a line at all, so carrying a verdict onto it would smuggle in the
            # exact state that gate exists to refuse. The negotiation text still travels — it is
            # what someone typed, and it is not a verdict.
            lost.append(f"{label} marked {was.status!r} — its citation no longer verifies, so the "
                        f"verdict cannot stand until the line is re-reviewed")
            for column in ("client_response", "contractor_response"):
                if getattr(was, column):
                    setattr(target, column, getattr(was, column))
            continue
        for column in _HUMAN_COLUMNS:
            value = getattr(was, column)
            # A machine status is the fresh run's to state; only a human verdict travels.
            if column == "status" and value not in models.HUMAN_VERDICTS:
                continue
            if value:
                setattr(target, column, value)
    return lost


def reopen_verdicts_for_parts(set_id: str, part_ids: list[str]) -> list[int]:
    """Clear human verdicts on register lines whose underlying part was just revised.

    A verdict is an approval of specific wording. When an addendum rewrites that wording the
    approval no longer means anything, and letting it stand is how a departure schedule built on
    superseded text reaches a client. So the line goes back to ``candidate``, keeps its citation
    note explaining why, and must be decided again.

    Nothing is lost: the previous verdict is recorded in the note, and the old revision remains
    readable. The review gate flag is deliberately NOT cleared — reopening lines is a prompt to
    re-review, not a silent rollback of the whole sign-off, and the reopened lines are visible.
    """
    if not part_ids:
        return []
    conn = get_conn()
    try:
        register = load_register(conn, set_id)
        if register is None:
            return []
        affected = set(part_ids)
        reopened: list[int] = []
        for item in register.items:
            if item.status not in models.HUMAN_VERDICTS:
                continue
            clause = getattr(item, "part_id", "") or _part_for_clause(conn, set_id, item.clause)
            if clause not in affected:
                continue
            was = item.status
            item.status = models.STATUS_CANDIDATE
            item.register_status = "open"
            item.citation_note = (
                f"Reopened: the clause this line cites was amended after it was marked {was!r}. "
                f"Re-review against the current revision."
            )
            reopened.append(item.item)
        if reopened:
            save_register(conn, register)
        return reopened
    finally:
        conn.close()


def _part_for_clause(conn: sqlite3.Connection, set_id: str, clause_id: str) -> str:
    """Which part a cited clause came from, via the persisted parse."""
    if not clause_id:
        return ""
    parsed = load_parsed(conn, set_id)
    if parsed is None:
        return ""
    clause = parsed.clause_index().get(clause_id)
    return getattr(clause, "part_id", "") if clause is not None else ""


def load_part_revisions(conn: sqlite3.Connection, set_id: str, part_id: str) -> list[dict]:
    """Every revision of one part, oldest first, with the document and cause that introduced it.

    The cause is the introducing document's kind, never stored twice: an acknowledgement letter
    must list the client's addenda and not our own corrections, and one source of truth for that
    distinction is safer than two.
    """
    rows = conn.execute(
        """
        SELECT r.rev, r.doc_id, r.start_page, r.end_page, r.scanned, r.source_doc, r.pdf_path,
               r.context_json, r.created_at,
               COALESCE(d.kind, 'base') AS cause, COALESCE(d.ref, '') AS doc_ref,
               COALESCE(d.filename, '') AS doc_filename, COALESCE(d.seq, 0) AS seq
        FROM client_boq_part_revisions r
        LEFT JOIN client_boq_documents d ON d.set_id = r.set_id AND d.doc_id = r.doc_id
        WHERE r.set_id = ? AND r.part_id = ?
        ORDER BY r.rev
        """,
        (set_id, part_id),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["scanned"] = bool(item["scanned"])
        blob = item.pop("context_json", "") or ""
        item["readable"] = True
        if blob and blob != "{}":
            try:
                item["readable"] = bool(json.loads(blob).get("readable", True))
            except ValueError:
                pass
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Workspace artifacts (the readable file copies)
# ---------------------------------------------------------------------------
def _client_boq_dir(ws: Workspace, tender_id: str):
    path = ws.artifacts_dir(tender_id, create=True) / "client_boq"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parts_dir(ws: Workspace, tender_id: str):
    """Where the cut part PDFs and their context cards are materialised."""
    path = _client_boq_dir(ws, tender_id) / "parts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bill_dir(ws: Workspace, tender_id: str):
    """Where the client's bill-of-quantities workbooks are kept, one per revision.

    The file itself is kept, not merely what was read out of it: GCT Appendix A 10 requires the bill
    to be priced in the client's own workbook, so writing rates back means having their file — and
    every superseded revision stays beside it, because a diff needs both.
    """
    path = _client_boq_dir(ws, tender_id) / "bill"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_manifest_artifact(ws: Workspace, tender_id: str, manifest: SplitManifest) -> None:
    (_client_boq_dir(ws, tender_id) / "split-manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )


def save_parsed_artifact(ws: Workspace, tender_id: str, parsed: ParsedDocumentSet) -> None:
    (_client_boq_dir(ws, tender_id) / "parsed.json").write_text(
        parsed.model_dump_json(indent=2), encoding="utf-8"
    )


def save_register_artifact(ws: Workspace, tender_id: str, register: DepartureRegister) -> None:
    (_client_boq_dir(ws, tender_id) / "register.json").write_text(
        register.model_dump_json(indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Estimate persistence (client_boq_estimates table + artifact)
# ---------------------------------------------------------------------------
def save_estimate(conn: sqlite3.Connection, estimate: Estimate) -> None:
    """Persist the priced estimate to the tables (upsert per document set)."""
    conn.execute(
        """
        INSERT INTO client_boq_estimates (set_id, estimate_json)
        VALUES (:set_id, :json)
        ON CONFLICT(set_id) DO UPDATE SET estimate_json = excluded.estimate_json
        """,
        {"set_id": estimate.set_id, "json": estimate.model_dump_json()},
    )
    conn.commit()


def load_estimate(conn: sqlite3.Connection, set_id: str) -> Optional[Estimate]:
    """The persisted estimate for ``set_id``, or None."""
    row = conn.execute(
        "SELECT estimate_json FROM client_boq_estimates WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["estimate_json"] or row["estimate_json"] == "{}":
        return None
    return Estimate.model_validate_json(row["estimate_json"])


def save_estimate_artifact(ws: Workspace, tender_id: str, estimate: Estimate) -> None:
    (_client_boq_dir(ws, tender_id) / "estimate.json").write_text(
        estimate.model_dump_json(indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Estimate scope (the s01 draft + the scope gate — the second estimate gate)
# ---------------------------------------------------------------------------
def save_scope_draft(conn: sqlite3.Connection, set_id: str, draft: ScopeReviewResult) -> None:
    """Persist the s01 scope draft, preserving any existing approval/amendment (re-drafting never
    silently re-opens the gate)."""
    conn.execute(
        """
        INSERT INTO client_boq_estimate_scope (set_id, scope_json)
        VALUES (:set_id, :json)
        ON CONFLICT(set_id) DO UPDATE SET scope_json = excluded.scope_json
        """,
        {"set_id": set_id, "json": draft.model_dump_json()},
    )
    conn.commit()


def load_scope(conn: sqlite3.Connection, set_id: str) -> Optional[EstimateScope]:
    """The scope record (draft + amended summary + approved flag), or None. The stored ``approved``
    column is authoritative (mirrors the review gate)."""
    row = conn.execute(
        "SELECT scope_json, amended_summary, approved FROM client_boq_estimate_scope WHERE set_id = ?",
        (set_id,),
    ).fetchone()
    if not row or not row["scope_json"] or row["scope_json"] == "{}":
        return None
    return EstimateScope(
        set_id=set_id, draft=ScopeReviewResult.model_validate_json(row["scope_json"]),
        amended_summary=row["amended_summary"] or "", approved=bool(row["approved"]),
    )


def scope_is_approved(conn: sqlite3.Connection, set_id: str) -> bool:
    """True when the estimate scope for ``set_id`` is human-approved — the estimate's second gate."""
    row = conn.execute(
        "SELECT approved FROM client_boq_estimate_scope WHERE set_id = ?", (set_id,)
    ).fetchone()
    return bool(row and row["approved"])


def approve_scope(conn: sqlite3.Connection, set_id: str, approved: bool, amended_summary: str = "") -> None:
    """The scope gate writer (the ONLY place scope-approved state is set). An ``amended_summary`` (when
    non-empty) becomes the approved scope of record; the original draft is retained in ``scope_json``."""
    conn.execute(
        """
        INSERT INTO client_boq_estimate_scope (set_id, amended_summary, approved, approved_at)
        VALUES (:set_id, :amended, :approved, CASE WHEN :approved THEN datetime('now') ELSE NULL END)
        ON CONFLICT(set_id) DO UPDATE SET
            amended_summary = excluded.amended_summary,
            approved = excluded.approved,
            approved_at = excluded.approved_at
        """,
        {"set_id": set_id, "amended": amended_summary.strip(), "approved": 1 if approved else 0},
    )
    conn.commit()


# --- the scope of record, item by item (the freeze gate) --------------------
def _scope_item_from_row(row) -> models.ScopeItem:
    return models.ScopeItem(
        item_id=row["item_id"], section=row["section"], title=row["title"], badge=row["badge"],
        is_fallback=bool(row["is_fallback"]), accepted=bool(row["accepted"]),
        text=row["text"], source_ref=row["source_ref"], updated_at=row["updated_at"] or "",
    )


def load_scope_items(conn: sqlite3.Connection, set_id: str) -> list[models.ScopeItem]:
    """Every line of the scope of record, in section order then insertion order."""
    # CASE branches are space-separated, not comma-separated. The section names are module
    # constants, never user input, so interpolating them is safe.
    order = " ".join(f"WHEN '{s}' THEN {i}" for i, s in enumerate(models.SCOPE_SECTIONS))
    rows = conn.execute(
        f"SELECT * FROM client_boq_scope_items WHERE set_id = ? "
        f"ORDER BY CASE section {order} ELSE 99 END, item_id",
        (set_id,),
    ).fetchall()
    return [_scope_item_from_row(r) for r in rows]


def save_scope_item(conn: sqlite3.Connection, set_id: str, item: models.ScopeItem,
                    *, now: str = "") -> models.ScopeItem:
    """Insert or update one scope line. Assigns an id on first save."""
    if not item.item_id:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM client_boq_scope_items WHERE set_id = ?", (set_id,)
        ).fetchone()["n"]
        item = item.model_copy(update={"item_id": f"scope-{count + 1:03d}"})
    item = item.model_copy(update={"updated_at": now or item.updated_at})
    conn.execute(
        """
        INSERT INTO client_boq_scope_items
            (set_id, item_id, section, title, badge, is_fallback, accepted, text, source_ref,
             updated_at)
        VALUES (:set_id, :item_id, :section, :title, :badge, :is_fallback, :accepted, :text,
                :source_ref, :updated_at)
        ON CONFLICT(set_id, item_id) DO UPDATE SET
            section = excluded.section, title = excluded.title, badge = excluded.badge,
            is_fallback = excluded.is_fallback, accepted = excluded.accepted,
            text = excluded.text, source_ref = excluded.source_ref,
            updated_at = excluded.updated_at
        """,
        {"set_id": set_id, **item.model_dump()},
    )
    conn.commit()
    return item


def delete_scope_item(conn: sqlite3.Connection, set_id: str, item_id: str) -> bool:
    """Unmap a line. The only true delete in this module, and it is safe for one reason: the
    source it came from is derived, so removing the line simply returns the source to the rail
    with nothing lost. A line written by hand is genuinely discarded, which is what unmapping a
    thing you typed means."""
    cur = conn.execute(
        "DELETE FROM client_boq_scope_items WHERE set_id = ? AND item_id = ?", (set_id, item_id)
    )
    conn.commit()
    return cur.rowcount > 0


def unaccepted_fallbacks(conn: sqlite3.Connection, set_id: str) -> list[models.ScopeItem]:
    """Fallbacks nobody has accepted — the freeze gate's blocking set.

    These are the lines where a machine's guess is standing in for an answer the client never
    gave. Approving over one would put that guess behind a price with nothing recording that a
    person ever agreed to it, which is the single thing the authorship rule exists to prevent.
    """
    return [i for i in load_scope_items(conn, set_id) if i.is_fallback and not i.accepted]


def save_scope_artifact(ws: Workspace, tender_id: str, scope: EstimateScope) -> None:
    (_client_boq_dir(ws, tender_id) / "estimate_scope.json").write_text(
        scope.model_dump_json(indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Offer letter (draft) persistence
# ---------------------------------------------------------------------------
def save_letter(conn: sqlite3.Connection, letter: LetterOfOffer) -> None:
    conn.execute(
        """
        INSERT INTO client_boq_letters (set_id, letter_json)
        VALUES (:set_id, :json)
        ON CONFLICT(set_id) DO UPDATE SET letter_json = excluded.letter_json
        """,
        {"set_id": letter.set_id, "json": letter.model_dump_json()},
    )
    conn.commit()


def load_letter(conn: sqlite3.Connection, set_id: str) -> Optional[LetterOfOffer]:
    row = conn.execute(
        "SELECT letter_json FROM client_boq_letters WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["letter_json"] or row["letter_json"] == "{}":
        return None
    return LetterOfOffer.model_validate_json(row["letter_json"])


def save_letter_artifact(ws: Workspace, tender_id: str, letter: LetterOfOffer) -> None:
    (_client_boq_dir(ws, tender_id) / "letter_of_offer.md").write_text(letter.markdown, encoding="utf-8")


# ---------------------------------------------------------------------------
# Conditions — a sentence somebody wrote down, and the knob it was mapped onto
# ---------------------------------------------------------------------------
# The row is the record; the mapping is a PROPOSAL. `status` is a person's and nothing else sets
# it, and only a confirmation writes the model. See the table comment in `models.py`.
_CONDITION_COLUMNS = (
    "set_id, condition_id, text, note, created_by, created_at, proposed_path, proposed_value, "
    "proposal_basis, proposal_source, status, decided_by, decided_at, applied_value, born_of_seq"
)


def save_condition(conn: sqlite3.Connection, set_id: str, condition_id: str, *, text: str,
                   note: str = "", actor: str = "", born_of_seq: int = 0) -> dict:
    """Record a condition. Idempotent on ``(set_id, condition_id)``; never touches the verdict.

    ``born_of_seq`` names the site-log discussion that concluded this condition — the provenance
    that lets a confirmed condition answer "why do we believe this?" with the conversation. 0
    means it was typed straight onto the register, which most are.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_conditions
            (set_id, condition_id, text, note, created_by, created_at, born_of_seq)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, condition_id) DO UPDATE SET
            text = excluded.text, note = excluded.note,
            born_of_seq = CASE WHEN excluded.born_of_seq > 0
                               THEN excluded.born_of_seq ELSE born_of_seq END
        """,
        (set_id, condition_id, text, note, actor, now, born_of_seq),
    )
    conn.commit()
    return load_condition(conn, set_id, condition_id) or {}


def save_condition_proposal(conn: sqlite3.Connection, set_id: str, condition_id: str, *,
                            path: str, value: Optional[float], basis: str,
                            source: str = "") -> None:
    """Attach the machine's proposed mapping. Writes NO verdict and NO model value."""
    conn.execute(
        """
        UPDATE client_boq_conditions
           SET proposed_path = ?, proposed_value = ?, proposal_basis = ?, proposal_source = ?
         WHERE set_id = ? AND condition_id = ?
        """,
        (path, value, basis, source, set_id, condition_id),
    )
    conn.commit()


def decide_condition(conn: sqlite3.Connection, set_id: str, condition_id: str, *, status: str,
                     actor: str = "", applied_value: Optional[float] = None) -> None:
    """The human's verdict. The SOLE writer of `status` — no stage and no model call reaches it."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        UPDATE client_boq_conditions
           SET status = ?, decided_by = ?, decided_at = ?, applied_value = ?
         WHERE set_id = ? AND condition_id = ?
        """,
        (status, actor, now, applied_value, set_id, condition_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# The site log — grounded discussions, persisted. Memory, not authority.
# ---------------------------------------------------------------------------
def save_ask_exchange(conn: sqlite3.Connection, set_id: str, *, question: str,
                      payload: dict, actor: str = "") -> int:
    """Persist one grounded exchange and return its per-set ``seq``.

    ``payload`` is the validated answer's dict — the type with no field for a rate or a verdict —
    so the log can never hold more authority than the response did. Everything is kept, including
    ``stripped`` (what validation removed): a discussion that lost a citation on the way through
    must read that way six months later too.
    """
    import json as _json
    from datetime import datetime, timezone

    seq = (conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM client_boq_site_log WHERE set_id = ?",
        (set_id,)).fetchone()[0])
    conn.execute(
        """
        INSERT INTO client_boq_site_log
            (set_id, seq, question, answer, cannot_answer, citations_json, figures_json,
             proposes, stripped_json, asked_by, asked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (set_id, seq, question, payload.get("answer", ""), payload.get("cannot_answer", ""),
         _json.dumps(payload.get("citations", []), ensure_ascii=False),
         _json.dumps(payload.get("figures", {}), ensure_ascii=False),
         payload.get("proposes", ""),
         _json.dumps(payload.get("stripped", []), ensure_ascii=False),
         actor, datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()
    return int(seq)


def load_site_log(conn: sqlite3.Connection, set_id: str,
                  limit: Optional[int] = None) -> list[dict]:
    """The discussions, oldest first — the order a reader replays them in."""
    import json as _json

    rows = conn.execute(
        "SELECT seq, question, answer, cannot_answer, citations_json, figures_json, proposes, "
        "stripped_json, asked_by, asked_at FROM client_boq_site_log WHERE set_id = ? "
        "ORDER BY seq", (set_id,)).fetchall()
    out = []
    for row in rows:
        entry = dict(row)
        for key in ("citations_json", "figures_json", "stripped_json"):
            try:
                entry[key.removesuffix("_json")] = _json.loads(entry.pop(key))
            except (ValueError, TypeError):
                entry[key.removesuffix("_json")] = None   # a corrupt blob is a gap, not a crash
        out.append(entry)
    return out[-limit:] if limit else out


def load_condition(conn: sqlite3.Connection, set_id: str, condition_id: str) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_CONDITION_COLUMNS} FROM client_boq_conditions "
        f"WHERE set_id = ? AND condition_id = ?",
        (set_id, condition_id),
    ).fetchone()
    return dict(row) if row else None


def load_conditions(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    """Every condition on this tender, oldest first. Nothing is filtered out — an unmapped or
    unconfirmed condition is exactly the thing that has to stay visible."""
    rows = conn.execute(
        f"SELECT {_CONDITION_COLUMNS} FROM client_boq_conditions "
        # ORDER BY rowid, not by timestamp: two rows written in the same SECOND tie, and the
        # tiebreak was a hashed id — so arrival order was stable only by luck. rowid IS insertion
        # order in SQLite, which is the order these were actually written down in.
        f"WHERE set_id = ? ORDER BY rowid",
        (set_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_condition(conn: sqlite3.Connection, set_id: str, condition_id: str) -> None:
    conn.execute(
        "DELETE FROM client_boq_conditions WHERE set_id = ? AND condition_id = ?",
        (set_id, condition_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Site photographs — the index and the provenance; the bytes are in the workspace
# ---------------------------------------------------------------------------
_PHOTO_COLUMNS = ("set_id, photo_id, filename, rel_path, content_type, caption, station, "
                  "uploaded_by, uploaded_at")


def save_site_photo(conn: sqlite3.Connection, set_id: str, photo_id: str, *, filename: str,
                    rel_path: str, content_type: str = "", caption: str = "", station: str = "",
                    actor: str = "") -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO client_boq_site_photos
            (set_id, photo_id, filename, rel_path, content_type, caption, station,
             uploaded_by, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(set_id, photo_id) DO UPDATE SET
            caption = excluded.caption, station = excluded.station
        """,
        (set_id, photo_id, filename, rel_path, content_type, caption, station, actor, now),
    )
    conn.commit()
    return load_site_photo(conn, set_id, photo_id) or {}


def load_site_photo(conn: sqlite3.Connection, set_id: str, photo_id: str) -> Optional[dict]:
    row = conn.execute(
        f"SELECT {_PHOTO_COLUMNS} FROM client_boq_site_photos WHERE set_id = ? AND photo_id = ?",
        (set_id, photo_id),
    ).fetchone()
    return dict(row) if row else None


def load_site_photos(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    rows = conn.execute(
        # ORDER BY rowid — see the note on `load_conditions`. Two photographs uploaded in the same
        # second tied and fell back to a hashed id, so "the order they were taken in" was arbitrary.
        f"SELECT {_PHOTO_COLUMNS} FROM client_boq_site_photos WHERE set_id = ? ORDER BY rowid",
        (set_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def delete_site_photo(conn: sqlite3.Connection, set_id: str, photo_id: str) -> None:
    conn.execute(
        "DELETE FROM client_boq_site_photos WHERE set_id = ? AND photo_id = ?",
        (set_id, photo_id),
    )
    conn.commit()
