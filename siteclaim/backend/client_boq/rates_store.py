"""The rate library, DB-backed — the source ``rates.py`` declared itself the seam for.

``rates.py`` has said since v1: "``load_rates`` returns :class:`RateRow` objects, and a future
company-DB source only has to return the same list from a different reader. Nothing downstream
reads the CSV directly." This is that source. The CSV seeds the table once (first-wins on
duplicate ids, mirroring ``rate_index`` so the seeded book resolves identically to the file it
came from); thereafter the DB is the source of truth and the CSV remains as documentation of the
starting book.

Rates ARCHIVE rather than delete. An estimate that referenced a rate now archived resolves it as
``missing_rate`` on a re-run — honestly absent, priced at 0 with a flag — instead of silently
pricing at a number nobody stands behind any more.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from client_boq import rates as rates_csv
from client_boq.models import RateRow

_FIELDS = ("category", "code", "description", "unit", "rate", "currency", "source", "notes")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed_if_empty(conn: sqlite3.Connection) -> set[str]:
    """First access reads the CSV into the table; later accesses are no-ops. Returns the
    duplicate rate_ids found at seed time (first-wins applied), so the screen can say the
    source needed cleaning rather than hiding that it did."""
    row = conn.execute("SELECT COUNT(*) AS n FROM client_boq_rates").fetchone()
    if int(row["n"]) > 0:
        return set()
    rows = rates_csv.load_rates_csv()
    duplicates = rates_csv.duplicate_rate_ids(rows)
    for r in rates_csv.rate_index(rows).values():   # first-wins, same as the resolver
        conn.execute(
            """
            INSERT OR IGNORE INTO client_boq_rates
                (rate_id, category, code, description, unit, rate, currency, source, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (r.rate_id, r.category, r.code, r.description, r.unit, r.rate,
             r.currency, r.source, r.notes),
        )
    conn.commit()
    return duplicates


def load(conn: sqlite3.Connection, include_archived: bool = False) -> list[RateRow]:
    """The live rate book as :class:`RateRow` objects — the same list ``rates.load_rates``
    used to return from the CSV. Archived rows are absent by default, which is exactly how an
    archived rate becomes an honest ``missing_rate`` downstream."""
    seed_if_empty(conn)
    where = "" if include_archived else "WHERE archived = 0"
    rows = conn.execute(
        f"SELECT * FROM client_boq_rates {where} ORDER BY rowid"
    ).fetchall()
    return [RateRow(
        rate_id=r["rate_id"], category=r["category"], code=r["code"],
        description=r["description"], unit=r["unit"], rate=r["rate"],
        currency=r["currency"], source=r["source"], notes=r["notes"],
    ) for r in rows]


def load_rows(conn: sqlite3.Connection) -> list[dict]:
    """Every rate row with its editing metadata — what the Pricing & rates screen renders."""
    seed_if_empty(conn)
    rows = conn.execute("SELECT * FROM client_boq_rates ORDER BY rowid").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["archived"] = bool(d["archived"])
        out.append(d)
    return out


def get(conn: sqlite3.Connection, rate_id: str) -> Optional[dict]:
    seed_if_empty(conn)
    row = conn.execute("SELECT * FROM client_boq_rates WHERE rate_id = ?", (rate_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["archived"] = bool(d["archived"])
    return d


def upsert(conn: sqlite3.Connection, *, rate_id: str, actor: str = "", **fields) -> dict:
    """Create or update one rate, stamping who and when. A non-numeric rate raises — a bad rate
    must never silently become 0 (the same rule the CSV loader enforces)."""
    unknown = set(fields) - set(_FIELDS) - {"archived"}
    if unknown:
        raise ValueError(f"unknown rate fields: {sorted(unknown)}")
    if "rate" in fields:
        try:
            fields["rate"] = float(fields["rate"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-numeric rate for {rate_id!r}") from exc
    seed_if_empty(conn)
    existing = get(conn, rate_id)
    merged = existing or {f: ("" if f != "rate" else 0.0) for f in _FIELDS}
    merged = {**merged, **fields}
    merged["archived"] = int(bool(merged.get("archived", False)))
    conn.execute(
        """
        INSERT INTO client_boq_rates
            (rate_id, category, code, description, unit, rate, currency, source, notes,
             archived, updated_by, updated_at)
        VALUES (:rate_id, :category, :code, :description, :unit, :rate, :currency, :source,
                :notes, :archived, :updated_by, :updated_at)
        ON CONFLICT(rate_id) DO UPDATE SET
            category = excluded.category, code = excluded.code,
            description = excluded.description, unit = excluded.unit, rate = excluded.rate,
            currency = excluded.currency, source = excluded.source, notes = excluded.notes,
            archived = excluded.archived,
            updated_by = excluded.updated_by, updated_at = excluded.updated_at
        """,
        {"rate_id": rate_id, **{f: merged.get(f, "") for f in _FIELDS},
         "archived": merged["archived"], "updated_by": actor, "updated_at": _now()},
    )
    conn.commit()
    return get(conn, rate_id)  # type: ignore[return-value]
