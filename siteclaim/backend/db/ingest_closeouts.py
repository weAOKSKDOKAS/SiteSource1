"""Phase D — partner-archive closeout ingestion (build plan section 7).

Phase D (making the EOS/closeout layer real) is business development, not a coding
sprint. The code deliverable is this: an ingestion script so that *the day a partner
says yes, ingestion is a script rather than a project*. It maps a partner's closeout
export (the section-7 fields) into the existing database and the same
``cross_reference(..., include_public=True)`` then uses the closeout match as
enrichment automatically — no new pipeline stage.

For each record it:

1. **Resolves the firm** — by Business Registration number, else by exact normalized
   name, else it mints a new firm with ``provenance='partner_archive'`` (never
   ``public_register`` — the coverage 134/46 honesty figures stay exact, and an
   existing real firm's provenance is never downgraded on a match).
2. **Writes a ``project_closeouts`` row** — always, even with no narrative. A slipped
   closeout (actual completion past planned, or a live LD/claims history) sets
   ``delayed=1``; the rules engine then adjudicates that raw signal to a WARNING. The
   script writes facts, never severities.
3. **Bakes one closeout embedding** from the narrative — using the target DB's OWN
   recorded ``embed_method`` / ``embed_dim`` (read from ``meta``), exactly as the store
   embeds a query at runtime. Baking into the wrong space silently breaks cosine, so
   this parity is the load-bearing invariant. No narrative → no embedding (the
   project_closeouts row still lands; the firm's match_score stays 0 but it is screened).

Additive only: it imports the same helpers seed uses and touches no stage/API code.
Offline for a deterministic DB; the MiniLM path is used only if the target DB was
baked with MiniLM (opt-in), never in a deterministic DEMO_MODE DB.
"""

from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from db import seed, store
from db.embeddings import DETERMINISTIC_DIM, deterministic_embedding
from rules_engine.taxonomy import normalize as _normalize_trade

_PARTNER = "partner_archive"
_SUFFIX_TOKENS = {"ltd", "limited", "company", "co", "holdings", "hk", "hongkong", "the"}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Input record
# ---------------------------------------------------------------------------
@dataclass
class PartnerCloseoutRecord:
    """One past subcontract from a partner archive (build plan section 7 fields)."""

    firm_name: str
    trade: str
    br_number: Optional[str] = None
    project_name: Optional[str] = None
    client: Optional[str] = None
    year: Optional[int] = None
    contract_value: Optional[float] = None
    final_account_value: Optional[float] = None
    planned_completion: Optional[str] = None
    actual_completion: Optional[str] = None
    rework_defect_notes: Optional[str] = None
    ld_claims_history: Optional[str] = None
    closeout_narrative: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: dict) -> "PartnerCloseoutRecord":
        def norm_key(k: str) -> str:
            return re.sub(r"[^a-z0-9]+", "_", k.strip().lower()).strip("_")

        data = {norm_key(k): v for k, v in raw.items()}
        aliases = {"firm": "firm_name", "name": "firm_name", "br": "br_number", "project": "project_name",
                   "narrative": "closeout_narrative", "final_account": "final_account_value"}
        for a, real in aliases.items():
            if a in data and real not in data:
                data[real] = data[a]
        return cls(
            firm_name=str(data.get("firm_name") or "").strip(),
            trade=str(data.get("trade") or "").strip(),
            br_number=_clean_str(data.get("br_number")),
            project_name=_clean_str(data.get("project_name")),
            client=_clean_str(data.get("client")),
            year=_to_int(data.get("year")),
            contract_value=_to_float(data.get("contract_value")),
            final_account_value=_to_float(data.get("final_account_value")),
            planned_completion=_clean_str(data.get("planned_completion")),
            actual_completion=_clean_str(data.get("actual_completion")),
            rework_defect_notes=_clean_str(data.get("rework_defect_notes")),
            ld_claims_history=_clean_str(data.get("ld_claims_history")),
            closeout_narrative=_clean_str(data.get("closeout_narrative")),
        )


@dataclass
class IngestSummary:
    firms_created: int = 0
    firms_matched: int = 0
    closeouts_written: int = 0
    awards_written: int = 0
    embeddings_baked: int = 0
    skipped_no_narrative: int = 0
    skipped_invalid: int = 0
    skipped_ambiguous: int = 0
    skipped_duplicate: int = 0
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# Small parsers (tolerant — one bad row never aborts the batch)
# ---------------------------------------------------------------------------
def _clean_str(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip()[:4]) if re.search(r"\d", str(value)) else None
    except (ValueError, TypeError):
        return None


def _to_float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _parse_date(value: Optional[str]) -> Optional[_dt.date]:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%Y", "%Y/%m/%d", "%Y"):
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_name(name: str) -> str:
    tokens = _SLUG_RE.sub(" ", (name or "").lower()).split()
    kept = [t for t in tokens if t not in _SUFFIX_TOKENS]
    return " ".join(kept or tokens)


def _mint_firm_id(name: str, br_number: Optional[str]) -> str:
    slug = _SLUG_RE.sub("-", (name or "firm").lower()).strip("-") or "firm"
    digest = hashlib.blake2b(f"{name}|{br_number or ''}".encode("utf-8"), digest_size=2).hexdigest()
    return f"{slug}-{digest}"


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def load_records(raw_records: list[dict]) -> list[PartnerCloseoutRecord]:
    return [PartnerCloseoutRecord.from_dict(r) for r in raw_records]


def load_json(path: Path | str) -> list[PartnerCloseoutRecord]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return load_records(data if isinstance(data, list) else [data])


def load_csv(path: Path | str) -> list[PartnerCloseoutRecord]:
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        return load_records(list(csv.DictReader(fh)))


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------
def _has_br_column(conn: sqlite3.Connection) -> bool:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(firms)").fetchall()}
    return "br_number" in cols


def _ensure_br_column(conn: sqlite3.Connection) -> None:
    if not _has_br_column(conn):
        conn.execute("ALTER TABLE firms ADD COLUMN br_number TEXT")


def resolve_firm(conn: sqlite3.Connection, record: PartnerCloseoutRecord) -> tuple[Optional[str], bool]:
    """Return (firm_id, created). Match by BR, else exact normalized name, else mint new.

    Returns (None, False) when a name is ambiguous (matches more than one firm) — the
    caller skips it rather than attach a closeout to the wrong firm.
    """
    if record.br_number and _has_br_column(conn):
        row = conn.execute("SELECT firm_id FROM firms WHERE br_number = ?", (record.br_number,)).fetchone()
        if row is not None:
            return row["firm_id"], False

    target = _normalize_name(record.firm_name)
    matches = [
        row["firm_id"]
        for row in conn.execute("SELECT firm_id, name_en FROM firms").fetchall()
        if _normalize_name(row["name_en"]) == target
    ]
    if len(matches) == 1:
        return matches[0], False
    if len(matches) > 1:
        return None, False  # ambiguous — do not guess

    return _mint_firm_id(record.firm_name, record.br_number), True


def _create_firm(conn: sqlite3.Connection, firm_id: str, record: PartnerCloseoutRecord) -> None:
    trades = [_normalize_trade(record.trade) or record.trade] if record.trade else []
    conn.execute(
        "INSERT INTO firms (firm_id, name_en, br_number, trades, closeout_summary, provenance) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (firm_id, record.firm_name, record.br_number, json.dumps(trades),
         (record.closeout_narrative or "")[:400], _PARTNER),
    )


# ---------------------------------------------------------------------------
# Closeout / delay / embedding
# ---------------------------------------------------------------------------
def _is_delayed(record: PartnerCloseoutRecord) -> bool:
    if record.ld_claims_history:
        return True
    planned, actual = _parse_date(record.planned_completion), _parse_date(record.actual_completion)
    return planned is not None and actual is not None and actual > planned


def _compose_note(record: PartnerCloseoutRecord, delayed: bool) -> str:
    parts: list[str] = []
    if record.closeout_narrative:
        parts.append(record.closeout_narrative)
    if delayed:
        planned, actual = _parse_date(record.planned_completion), _parse_date(record.actual_completion)
        if planned and actual:
            weeks = max(0, round((actual - planned).days / 7))
            parts.append(f"Closeout slipped ~{weeks} week(s) past planned completion.")
    if record.rework_defect_notes:
        parts.append(f"Rework/defects: {record.rework_defect_notes}")
    if record.ld_claims_history:
        parts.append(f"LD/claims: {record.ld_claims_history}")
    if record.contract_value or record.final_account_value:
        c = f"HK${record.contract_value:,.0f}" if record.contract_value else "n/a"
        f = f"HK${record.final_account_value:,.0f}" if record.final_account_value else "n/a"
        parts.append(f"Final account {f} vs contract {c}.")
    return " ".join(parts)


def _closeout_exists(conn: sqlite3.Connection, firm_id: str, project: Optional[str], year: Optional[int]) -> bool:
    return conn.execute(
        "SELECT 1 FROM project_closeouts WHERE firm_id = ? AND IFNULL(project,'') = IFNULL(?,'') "
        "AND IFNULL(year,-1) = IFNULL(?,-1) LIMIT 1",
        (firm_id, project, year),
    ).fetchone() is not None


def _next_chunk_id(conn: sqlite3.Connection, firm_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(chunk_id) AS m FROM closeout_embeddings WHERE firm_id = ?", (firm_id,)
    ).fetchone()
    return (row["m"] + 1) if row and row["m"] is not None else 0


def _embed(conn: sqlite3.Connection, text: str) -> list[float]:
    """Bake ``text`` in the SAME space the DB was built with (meta embed_method/dim)."""
    method = store._meta(conn, "embed_method", "deterministic")
    dim = int(store._meta(conn, "embed_dim", str(DETERMINISTIC_DIM)))
    if method == "deterministic":
        return deterministic_embedding(text, dim=dim)
    from db.embeddings import build_embeddings  # lazy — MiniLM DB only, never DEMO_MODE

    vec = build_embeddings([text])[0]
    if len(vec) != dim:
        raise ValueError(f"embedded dim {len(vec)} != DB embed_dim {dim} (embed-space mismatch)")
    return vec


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
def ingest(conn_or_path, records: list[PartnerCloseoutRecord]) -> IngestSummary:
    """Ingest ``records`` into the target DB. Accepts a Connection or a DB path."""
    own_conn = not isinstance(conn_or_path, sqlite3.Connection)
    conn = store.get_connection(conn_or_path) if own_conn else conn_or_path
    summary = IngestSummary()
    try:
        _ensure_br_column(conn)
        for record in records:
            if not record.firm_name or not record.trade:
                summary.skipped_invalid += 1
                continue

            firm_id, created = resolve_firm(conn, record)
            if firm_id is None:
                summary.skipped_ambiguous += 1
                summary.warnings.append(f"ambiguous firm name, skipped: {record.firm_name!r}")
                continue
            if created:
                _create_firm(conn, firm_id, record)
                summary.firms_created += 1
            else:
                summary.firms_matched += 1

            delayed = _is_delayed(record)
            if _closeout_exists(conn, firm_id, record.project_name, record.year):
                summary.skipped_duplicate += 1
                conn.commit()
                continue

            conn.execute(
                "INSERT INTO project_closeouts (firm_id, project, client, year, delayed, note, source, reference) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (firm_id, record.project_name, record.client, record.year, int(delayed),
                 _compose_note(record, delayed), "Partner archive",
                 f"PARTNER:{firm_id}:{record.year or 'na'}"),
            )
            summary.closeouts_written += 1

            if record.project_name or record.client or record.year:
                conn.execute(
                    "INSERT INTO award_history (firm_id, project, client, year, source) VALUES (?, ?, ?, ?, ?)",
                    (firm_id, record.project_name, record.client, record.year, "Partner archive"),
                )
                summary.awards_written += 1

            narrative = record.closeout_narrative
            if narrative and narrative.strip():
                vec = _embed(conn, narrative)
                conn.execute(
                    "INSERT INTO closeout_embeddings (firm_id, chunk_id, text, vector) VALUES (?, ?, ?, ?)",
                    (firm_id, _next_chunk_id(conn, firm_id), narrative.strip(), json.dumps(vec)),
                )
                summary.embeddings_baked += 1
            else:
                summary.skipped_no_narrative += 1

            conn.commit()
    finally:
        if own_conn:
            conn.close()
    return summary


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m db.ingest_closeouts",
        description="Ingest a partner closeout archive (CSV or JSON) into a SiteSource DB.",
    )
    parser.add_argument("--input", required=True, help="path to the partner export (.csv or .json)")
    parser.add_argument("--db", default=str(seed.LIVE_DB_PATH), help="target DB (default: sitesource_live.db)")
    args = parser.parse_args(argv)

    path = Path(args.input)
    records = load_csv(path) if path.suffix.lower() == ".csv" else load_json(path)
    summary = ingest(args.db, records)
    print(f"Ingested partner closeouts into {args.db}:")
    for key, value in summary.as_dict().items():
        print(f"  {key:>20}: {value}")


if __name__ == "__main__":
    main()
