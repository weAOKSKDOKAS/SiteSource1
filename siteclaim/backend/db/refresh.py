"""Phase C — semi-automated public-data refresh with a human-confirm gate.

A refresh never mutates the curated database directly. New public records (the same
record shape as ``seed_data/public/*.json``, supplied by an operator or an n8n cron
POST — there is no live scraper by design) are **staged**: written to ``staged_firms``
/ ``staged_flags`` with status ``pending``. A human reviews what is waiting
(:func:`list_pending`) and only then **confirms** it (:func:`confirm_pending`), at
which point new firms and new flags are upserted into the live ``firms`` /
``public_flags`` tables. Rejected batches (:func:`reject_pending`) stay as an audit
trail and never land.

Design guarantees:

* **Idempotent.** A flag is deduped by a stable fingerprint against both the pending
  staging rows and the live ``public_flags`` (which carries no UNIQUE constraint), so
  re-staging or re-confirming the same n8n batch adds nothing.
* **Honest provenance.** A refresh represents real ingest, so a confirmed firm is
  always ``provenance='public_register'``; the payload cannot inject ``illustrative``.
  So the coverage honesty figures only ever move on confirmed real data.
* **No orphans, no clobber.** A confirm INSERTs new firms and new flags only; it never
  rewrites an existing firm's curated identity, and a flag whose firm does not exist
  (and is not being created in the same confirm) is left pending, never orphan-inserted
  — checked explicitly rather than relying on per-connection foreign keys.

Pure SQLite + JSON. No network, no ML — Layer 3 discipline. The write endpoints are
gated off in DEMO_MODE at the API layer, so the committed demo DB is never mutated.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
import uuid
from typing import Optional

from rules_engine.taxonomy import normalize as _normalize_trade

_REAL = "public_register"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _batch_id() -> str:
    return uuid.uuid4().hex[:12]


def _canonical_trades(raw_trades: list) -> list[str]:
    """Screen raw trade names against the taxonomy (mirrors seed._canonical_trades)."""
    out: list[str] = []
    for trade in raw_trades or []:
        key = _normalize_trade(trade) or trade
        if key and key not in out:
            out.append(key)
    return out


def _flag_fingerprint(firm_id: str, flag: dict) -> str:
    """A stable hash of a flag's identity, for logical dedupe across stage/confirm."""
    parts = [
        firm_id,
        str(flag.get("signal_type") or ""),
        str(flag.get("label") or ""),
        str(flag.get("date") or ""),
        str(flag.get("source") or ""),
        str(flag.get("reference") or ""),
    ]
    return hashlib.blake2b("\x1f".join(parts).encode("utf-8"), digest_size=16).hexdigest()


def _ensure_staging_tables(conn: sqlite3.Connection) -> None:
    """Create the staging tables if this DB predates them (older committed DBs)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS staged_firms (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, firm_id TEXT NOT NULL,
            payload TEXT NOT NULL, provenance TEXT NOT NULL DEFAULT 'public_register',
            is_new_firm INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
            staged_at TEXT NOT NULL, applied_at TEXT, rejected_at TEXT
        );
        CREATE TABLE IF NOT EXISTS staged_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, firm_id TEXT NOT NULL,
            signal_type TEXT NOT NULL, label TEXT NOT NULL, date TEXT, source TEXT, reference TEXT,
            fingerprint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            staged_at TEXT NOT NULL, applied_at TEXT, rejected_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_staged_firms_status ON staged_firms(status);
        CREATE INDEX IF NOT EXISTS idx_staged_flags_status ON staged_flags(status);
        CREATE INDEX IF NOT EXISTS idx_staged_flags_fp ON staged_flags(fingerprint);
        """
    )


def _staging_present(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='staged_firms'"
    ).fetchone()
    return row is not None


def _firm_exists(conn: sqlite3.Connection, firm_id: str) -> bool:
    return conn.execute("SELECT 1 FROM firms WHERE firm_id = ? LIMIT 1", (firm_id,)).fetchone() is not None


def _flag_live_exists(conn: sqlite3.Connection, firm_id: str, fingerprint: str) -> bool:
    rows = conn.execute(
        "SELECT signal_type, label, date, source, reference FROM public_flags WHERE firm_id = ?",
        (firm_id,),
    ).fetchall()
    for row in rows:
        existing = {
            "signal_type": row["signal_type"], "label": row["label"], "date": row["date"],
            "source": row["source"], "reference": row["reference"],
        }
        if _flag_fingerprint(firm_id, existing) == fingerprint:
            return True
    return False


def _flag_pending_exists(conn: sqlite3.Connection, fingerprint: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM staged_flags WHERE fingerprint = ? AND status = 'pending' LIMIT 1",
        (fingerprint,),
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------
def stage_records(conn: sqlite3.Connection, records: list[dict]) -> dict:
    """Validate and stage ``records`` (never touches the live tables). Returns a summary.

    A record needs a ``firm_id`` and a list of ``public_flags`` (each needing a
    ``signal_type`` and ``label``). Trades are canonicalised. A flag already present
    (live) or already pending or repeated within this batch is skipped as a duplicate.
    """
    _ensure_staging_tables(conn)
    batch_id = _batch_id()
    now = _now_iso()
    summary = {
        "batch_id": batch_id, "staged_firms": 0, "staged_flags": 0,
        "skipped_duplicate_flags": 0, "skipped_invalid": 0, "new_firms": 0,
    }
    seen_this_batch: set[str] = set()

    for rec in records:
        firm_id = rec.get("firm_id")
        flags = rec.get("public_flags", [])
        if not firm_id or not isinstance(flags, list):
            summary["skipped_invalid"] += 1
            continue

        is_new = not _firm_exists(conn, firm_id)
        payload = {
            "firm_id": firm_id,
            "name_en": rec.get("name_en") or firm_id,
            "name_zh": rec.get("name_zh"),
            "registered_grade": rec.get("registered_grade"),
            "value_band": rec.get("value_band"),
            "registers": rec.get("registers", []),
            "trades": _canonical_trades(rec.get("trades", [])),
            "closeout_summary": rec.get("closeout_summary", ""),
            "award_history": rec.get("award_history", []),
        }
        conn.execute(
            "INSERT INTO staged_firms (batch_id, firm_id, payload, provenance, is_new_firm, status, staged_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (batch_id, firm_id, json.dumps(payload), _REAL, int(is_new), now),
        )
        summary["staged_firms"] += 1
        if is_new:
            summary["new_firms"] += 1

        for flag in flags:
            if not flag.get("signal_type") or not flag.get("label"):
                summary["skipped_invalid"] += 1
                continue
            fp = _flag_fingerprint(firm_id, flag)
            if fp in seen_this_batch or _flag_pending_exists(conn, fp) or _flag_live_exists(conn, firm_id, fp):
                summary["skipped_duplicate_flags"] += 1
                continue
            seen_this_batch.add(fp)
            conn.execute(
                "INSERT INTO staged_flags (batch_id, firm_id, signal_type, label, date, source, reference, "
                "fingerprint, status, staged_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (batch_id, firm_id, flag["signal_type"], flag["label"], flag.get("date"),
                 flag.get("source"), flag.get("reference"), fp, now),
            )
            summary["staged_flags"] += 1

    conn.commit()
    return summary


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
def list_pending(conn: sqlite3.Connection) -> list[dict]:
    """Pending firms with their pending flags nested — what a human is asked to confirm."""
    if not _staging_present(conn):
        return []
    firms = conn.execute(
        "SELECT batch_id, firm_id, is_new_firm, staged_at FROM staged_firms "
        "WHERE status = 'pending' ORDER BY staged_at, firm_id"
    ).fetchall()
    flag_rows = conn.execute(
        "SELECT batch_id, firm_id, signal_type, label, date, source, reference FROM staged_flags "
        "WHERE status = 'pending' ORDER BY staged_at, firm_id"
    ).fetchall()
    flags_by_firm: dict[tuple, list] = {}
    for r in flag_rows:
        flags_by_firm.setdefault((r["batch_id"], r["firm_id"]), []).append({
            "signal_type": r["signal_type"], "label": r["label"], "date": r["date"],
            "source": r["source"], "reference": r["reference"],
        })
    out = []
    for f in firms:
        out.append({
            "batch_id": f["batch_id"],
            "firm_id": f["firm_id"],
            "is_new_firm": bool(f["is_new_firm"]),
            "firm_exists": _firm_exists(conn, f["firm_id"]),
            "staged_at": f["staged_at"],
            "pending_flags": flags_by_firm.get((f["batch_id"], f["firm_id"]), []),
        })
    return out


def _selector_sql(batch_id: Optional[str], firm_ids: Optional[list[str]]) -> tuple[str, list]:
    clauses = ["status = 'pending'"]
    params: list = []
    if batch_id:
        clauses.append("batch_id = ?")
        params.append(batch_id)
    if firm_ids:
        clauses.append(f"firm_id IN ({','.join('?' for _ in firm_ids)})")
        params.extend(firm_ids)
    return " AND ".join(clauses), params


# ---------------------------------------------------------------------------
# Confirm / reject
# ---------------------------------------------------------------------------
def confirm_pending(
    conn: sqlite3.Connection, *, batch_id: Optional[str] = None, firm_ids: Optional[list[str]] = None
) -> dict:
    """Apply pending staged rows (optionally filtered by ``batch_id`` / ``firm_ids``).

    New ``public_register`` firms are inserted (identity of an existing firm is never
    rewritten); new flags are inserted only if the same flag is not already live. A
    flag whose firm neither exists nor is created here is left pending and reported.
    Runs under a single writer transaction and is safe to call twice (already-applied
    rows are not re-selected).
    """
    _ensure_staging_tables(conn)
    now = _now_iso()
    where, params = _selector_sql(batch_id, firm_ids)
    summary = {"confirmed_firms": 0, "confirmed_flags": 0, "skipped_existing_flags": 0, "skipped_unknown_firm": 0}

    # sqlite3 (default isolation) auto-opens a transaction on the first write below and
    # holds it until commit() — so the firm/flag inserts apply atomically, rolled back
    # together on any error.
    try:
        firm_rows = conn.execute(
            f"SELECT id, firm_id, payload, is_new_firm FROM staged_firms WHERE {where}", params
        ).fetchall()
        for fr in firm_rows:
            if fr["is_new_firm"] and not _firm_exists(conn, fr["firm_id"]):
                _insert_firm(conn, json.loads(fr["payload"]))
                summary["confirmed_firms"] += 1
            conn.execute(
                "UPDATE staged_firms SET status = 'applied', applied_at = ? WHERE id = ?", (now, fr["id"])
            )

        flag_rows = conn.execute(
            f"SELECT id, firm_id, signal_type, label, date, source, reference, fingerprint "
            f"FROM staged_flags WHERE {where}", params
        ).fetchall()
        for fl in flag_rows:
            if not _firm_exists(conn, fl["firm_id"]):
                summary["skipped_unknown_firm"] += 1
                continue  # leave pending — never orphan-insert
            if _flag_live_exists(conn, fl["firm_id"], fl["fingerprint"]):
                summary["skipped_existing_flags"] += 1
            else:
                conn.execute(
                    "INSERT INTO public_flags (firm_id, signal_type, label, date, source, reference) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fl["firm_id"], fl["signal_type"], fl["label"], fl["date"], fl["source"], fl["reference"]),
                )
                summary["confirmed_flags"] += 1
            conn.execute(
                "UPDATE staged_flags SET status = 'applied', applied_at = ? WHERE id = ?", (now, fl["id"])
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return summary


def _insert_firm(conn: sqlite3.Connection, payload: dict) -> None:
    conn.execute(
        "INSERT INTO firms (firm_id, name_en, name_zh, registered_grade, value_band, registers, "
        "trades, closeout_summary, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            payload["firm_id"], payload.get("name_en") or payload["firm_id"], payload.get("name_zh"),
            payload.get("registered_grade"), payload.get("value_band"),
            json.dumps(payload.get("registers", [])), json.dumps(payload.get("trades", [])),
            payload.get("closeout_summary", ""), _REAL,
        ),
    )
    for award in payload.get("award_history", []):
        conn.execute(
            "INSERT INTO award_history (firm_id, project, client, year, source) VALUES (?, ?, ?, ?, ?)",
            (payload["firm_id"], award.get("project"), award.get("client"), award.get("year"), award.get("source")),
        )


def reject_pending(
    conn: sqlite3.Connection, *, batch_id: Optional[str] = None, firm_ids: Optional[list[str]] = None
) -> dict:
    """Mark matching pending staged rows ``rejected`` — they never land; kept for audit."""
    _ensure_staging_tables(conn)
    now = _now_iso()
    where, params = _selector_sql(batch_id, firm_ids)
    rejected = 0
    for table in ("staged_firms", "staged_flags"):
        cur = conn.execute(
            f"UPDATE {table} SET status = 'rejected', rejected_at = ? WHERE {where}", [now, *params]
        )
        rejected += cur.rowcount
    conn.commit()
    return {"rejected": rejected}
