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
from typing import Optional

from client_boq import models
from client_boq.models import (
    ContextSummary,
    DepartureRegister,
    Estimate,
    EstimateScope,
    LetterOfOffer,
    ParsedDocumentSet,
    PartContext,
    PartSpec,
    RFIBatch,
    RFIItem,
    ScopeReviewResult,
    SplitManifest,
)
from db import store as db_store
from pipeline.llm_client import demo_mode
from pipeline.workspace import Workspace


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
    """Record the human decision on the manifest — the ONLY writer of the ingest gate flag."""
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
    row = conn.execute(
        "SELECT seq FROM client_boq_documents WHERE set_id = ? AND doc_id = ?", (set_id, doc_id)
    ).fetchone()
    if row is not None:
        seq = int(row["seq"])
        conn.execute(
            "UPDATE client_boq_documents SET filename = ?, kind = ?, ref = ?, note = ? "
            "WHERE set_id = ? AND doc_id = ?",
            (filename, kind, ref, note, set_id, doc_id),
        )
    else:
        nxt = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 AS n FROM client_boq_documents WHERE set_id = ?",
            (set_id,),
        ).fetchone()
        seq = int(nxt["n"])
        conn.execute(
            "INSERT INTO client_boq_documents (set_id, doc_id, filename, kind, ref, seq, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (set_id, doc_id, filename, kind, ref, seq, note),
        )
    conn.commit()
    return seq


def list_documents(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    """Every document that entered the set, in arrival order. These are the history's tabs."""
    rows = conn.execute(
        "SELECT doc_id, filename, kind, ref, seq, received_at, note "
        "FROM client_boq_documents WHERE set_id = ? ORDER BY seq",
        (set_id,),
    ).fetchall()
    return [dict(row) for row in rows]


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


def save_rfi(conn: sqlite3.Connection, set_id: str, item: RFIItem) -> RFIItem:
    """Raise or update one question. Returns it with its id assigned."""
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
