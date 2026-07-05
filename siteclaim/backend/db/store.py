"""Read-only query API over the SiteSource SQLite file (Layer 3).

Pure data access: SQLite + JSON columns + cosine. **No ML import here** — the
runtime never loads an embedding model. ``semantic_closeout_matches`` embeds the
query with the dependency-free :func:`db.embeddings.deterministic_embedding` (the
method the demo seed is baked with) and scores it by cosine over the baked
vectors, so the whole path is offline and reproducible.

Severity is NOT decided here. ``firm_profile`` returns each public/closeout signal
as a *raw, unadjudicated* :class:`RiskFlag` (``severity=INFO``, ``rule_ref`` of the
form ``signal.<type>``) carrying its cited :class:`Evidence`; the deterministic
rules engine (:func:`rules_engine.risk_scoring.score_firm`) is the single place
that assigns the real fatal/warning severities. The DB reports facts; the engine
adjudicates them.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from schemas.models import Contact, Evidence, FirmProfile, RiskFlag, Severity, SignalType
from db.embeddings import deterministic_embedding

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "sitesource.db"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Open the SiteSource DB read-only-ish (a plain connection with Row access).

    Path precedence: an explicit ``db_path`` wins; otherwise the ``SITESOURCE_DB``
    environment variable (how the live engine points at the clean ``sitesource_live.db``);
    otherwise the packaged demo ``sitesource.db``. Tests always pass an explicit path,
    so they are immune to the env override.
    """
    if db_path is not None:
        path = Path(db_path)
    else:
        env_path = os.getenv("SITESOURCE_DB", "").strip()
        path = Path(env_path) if env_path else DEFAULT_DB_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"SiteSource DB not found at {path}. Build it with `python -m db.seed`."
        )
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Firm assembly
# ---------------------------------------------------------------------------
def _json_list(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _raw_flag(signal_type: SignalType, label: str, source: str, reference: str, snippet: str) -> RiskFlag:
    """A raw, unadjudicated signal. Severity INFO is a placeholder — the rules
    engine assigns the real severity from the rubric (see module docstring)."""
    return RiskFlag(
        severity=Severity.INFO,
        label=label,
        rule_ref=f"signal.{signal_type.value}",
        evidence=[Evidence(source=source, signal_type=signal_type, snippet=snippet, reference=reference)],
    )


def _public_flag_rows(conn: sqlite3.Connection, firm_id: str) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    rows = conn.execute(
        "SELECT signal_type, label, date, source, reference FROM public_flags WHERE firm_id = ?",
        (firm_id,),
    ).fetchall()
    for row in rows:
        try:
            signal = SignalType(row["signal_type"])
        except ValueError:
            # Unknown signal type from a future scrape — carry it as advisory, do not crash.
            signal = SignalType.AWARD_HISTORY
        date = f" ({row['date']})" if row["date"] else ""
        flags.append(
            _raw_flag(signal, row["label"], row["source"] or "", row["reference"] or "", row["label"] + date)
        )
    return flags


def _closeout_flag_rows(conn: sqlite3.Connection, firm_id: str) -> list[RiskFlag]:
    """A delayed closeout becomes a raw CLOSEOUT_PERFORMANCE signal (from the EOS)."""
    flags: list[RiskFlag] = []
    rows = conn.execute(
        "SELECT project, year, delayed, note, source, reference FROM project_closeouts "
        "WHERE firm_id = ? AND delayed = 1",
        (firm_id,),
    ).fetchall()
    for row in rows:
        snippet = row["note"] or f"Delayed closeout on {row['project']} ({row['year']})."
        flags.append(
            _raw_flag(
                SignalType.CLOSEOUT_PERFORMANCE,
                f"Delayed closeout: {row['project']}",
                row["source"] or "Project closeout (EOS)",
                row["reference"] or "",
                snippet,
            )
        )
    return flags


def _award_strings(conn: sqlite3.Connection, firm_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT project, client, year FROM award_history WHERE firm_id = ? ORDER BY year DESC",
        (firm_id,),
    ).fetchall()
    out = []
    for row in rows:
        client = f" — {row['client']}" if row["client"] else ""
        out.append(f"{row['year']}: {row['project']}{client}")
    return out


def _firm_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> FirmProfile:
    firm_id = row["firm_id"]
    return FirmProfile(
        firm_id=firm_id,
        name=row["name_en"],
        registered_grade=row["registered_grade"] or "",
        value_band=row["value_band"] or "",
        trades=_json_list(row["trades"]),
        public_flags=_public_flag_rows(conn, firm_id) + _closeout_flag_rows(conn, firm_id),
        closeout_summary=row["closeout_summary"] or "",
        award_history=_award_strings(conn, firm_id),
    )


def all_firms(conn: sqlite3.Connection) -> list[FirmProfile]:
    rows = conn.execute("SELECT * FROM firms ORDER BY firm_id").fetchall()
    return [_firm_from_row(conn, row) for row in rows]


def firm_profile(conn: sqlite3.Connection, firm_id: str) -> Optional[FirmProfile]:
    row = conn.execute("SELECT * FROM firms WHERE firm_id = ?", (firm_id,)).fetchone()
    return _firm_from_row(conn, row) if row is not None else None


def firms_for_trade(conn: sqlite3.Connection, trade: str) -> list[FirmProfile]:
    """Every firm whose canonical trades include ``trade`` (the discovery/coverage
    pool — includes public-record-only firms with no closeout history)."""
    return [firm for firm in all_firms(conn) if trade in firm.trades]


def firms_page(conn: sqlite3.Connection, *, q: str = "", trade: str = "",
               limit: int = 25, offset: int = 0) -> tuple[list[FirmProfile], int]:
    """The browseable firm database — **real-provenance register firms only** (never the
    illustrative demo stubs, never partner_archive), so it reproduces the ``coverage`` 140/46
    population exactly. Optional case-insensitive name substring ``q`` and canonical ``trade``
    membership; ordered by name. Returns ``(page, total)`` where total is the full filtered
    count. Reuses ``_firm_from_row`` for the record mapping (no duplication)."""
    rows = conn.execute(
        "SELECT * FROM firms WHERE provenance = ? ORDER BY name_en COLLATE NOCASE, firm_id",
        (_REAL,),
    ).fetchall()
    firms = [_firm_from_row(conn, row) for row in rows]

    needle = (q or "").strip().lower()
    trade_key = (trade or "").strip()
    filtered = [
        firm for firm in firms
        if (not needle or needle in firm.name.lower())
        and (not trade_key or trade_key in firm.trades)
    ]
    total = len(filtered)
    start = max(0, offset)
    page = filtered[start:start + limit] if limit > 0 else filtered[start:]
    return page, total


def eos_firm_ids(conn: sqlite3.Connection) -> set[str]:
    """Firm ids that carry an **assessable EOS closeout record** (baked closeout
    chunks). The per-tender shortlist is drawn only from these; the wider
    public-record pool is screened and counted but not auto-shortlisted."""
    rows = conn.execute("SELECT DISTINCT firm_id FROM closeout_embeddings").fetchall()
    return {row["firm_id"] for row in rows}


def shortlistable_firms_for_trade(conn: sqlite3.Connection, trade: str) -> list[FirmProfile]:
    """Firms in ``trade`` that have an assessable EOS closeout record — the only
    firms eligible for the per-tender shortlist."""
    assessable = eos_firm_ids(conn)
    return [firm for firm in firms_for_trade(conn, trade) if firm.firm_id in assessable]


# ---------------------------------------------------------------------------
# Address book (Phase A) — where a trade's RFQ email is sent
# ---------------------------------------------------------------------------
def _contact_from_row(row: sqlite3.Row) -> Contact:
    return Contact(
        firm_id=row["firm_id"],
        trade=row["trade"],
        email=row["email"],
        contact_name=row["contact_name"] or "",
        phone=row["phone"] or "",
        note=row["note"] or "",
    )


def _has_contacts_table(conn: sqlite3.Connection) -> bool:
    """True if the DB was seeded with the address-book table (older DBs may predate it)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='contacts'"
    ).fetchone()
    return row is not None


def contact_for(conn: sqlite3.Connection, firm_id: str, trade: str) -> Optional[Contact]:
    """The address-book entry for ``firm_id`` on ``trade``, or None if unknown."""
    if not _has_contacts_table(conn):
        return None
    row = conn.execute(
        "SELECT firm_id, trade, contact_name, email, phone, note FROM contacts "
        "WHERE firm_id = ? AND trade = ?",
        (firm_id, trade),
    ).fetchone()
    return _contact_from_row(row) if row is not None else None


def all_contacts(conn: sqlite3.Connection) -> list[Contact]:
    """Every address-book entry (empty list if the table predates Phase A)."""
    if not _has_contacts_table(conn):
        return []
    rows = conn.execute(
        "SELECT firm_id, trade, contact_name, email, phone, note FROM contacts "
        "ORDER BY firm_id, trade"
    ).fetchall()
    return [_contact_from_row(row) for row in rows]


_REAL = "public_register"


def coverage(conn: sqlite3.Connection) -> dict:
    """Live database-coverage figures for the UI's screening line, as an **honest
    composition** — counting **only real-provenance firms** (the CIC register + the
    enforcement overlay), never the illustrative demo firms. The figure is never a bare
    "1,407 firms" claim: it is stated as ``register_count`` on the CIC register (real firms
    that carry a Business Registration No. from the register), ``overlay_count`` from the
    enforcement/offer records (real firms not on the register), and ``flagged_count``
    flagged. ``flag_sources`` are the distinct issuing bodies on the stored flags and
    ``registers`` is how many there are — every flag keeps its issuing source and reference."""
    total = conn.execute("SELECT COUNT(*) AS n FROM firms WHERE provenance = ?", (_REAL,)).fetchone()["n"]
    register_count = conn.execute(
        "SELECT COUNT(*) AS n FROM firms WHERE provenance = ? "
        "AND br_number IS NOT NULL AND br_number != ''",
        (_REAL,),
    ).fetchone()["n"]
    flagged = conn.execute(
        "SELECT COUNT(DISTINCT pf.firm_id) AS n FROM public_flags pf "
        "JOIN firms f ON f.firm_id = pf.firm_id WHERE f.provenance = ?",
        (_REAL,),
    ).fetchone()["n"]
    flags_by_type = {
        row["signal_type"]: row["n"]
        for row in conn.execute(
            "SELECT pf.signal_type AS signal_type, COUNT(*) AS n FROM public_flags pf "
            "JOIN firms f ON f.firm_id = pf.firm_id WHERE f.provenance = ? "
            "GROUP BY pf.signal_type ORDER BY pf.signal_type",
            (_REAL,),
        )
    }
    flag_sources = [
        row["source"]
        for row in conn.execute(
            "SELECT DISTINCT pf.source AS source FROM public_flags pf "
            "JOIN firms f ON f.firm_id = pf.firm_id "
            "WHERE f.provenance = ? AND pf.source IS NOT NULL AND pf.source != '' "
            "ORDER BY pf.source",
            (_REAL,),
        )
    ]
    trades: set[str] = set()
    for row in conn.execute("SELECT trades FROM firms WHERE provenance = ?", (_REAL,)):
        trades |= set(_json_list(row["trades"]))
    return {
        "total_firms": int(total),
        "register_count": int(register_count),
        "overlay_count": int(total) - int(register_count),
        "flagged_count": int(flagged),
        "flagged_firms": int(flagged),  # back-compat alias for existing consumers
        "flags_by_type": flags_by_type,
        "trades": sorted(trades),
        "flag_sources": flag_sources,
        "registers": len(flag_sources),
        "provenance": _REAL,
    }


# ---------------------------------------------------------------------------
# Historical pricing
# ---------------------------------------------------------------------------
def historical_pricing(conn: sqlite3.Connection, trade: str) -> Optional[tuple[float, float, float]]:
    """Return (low, median, high) awarded-value band for ``trade``, or None if no samples."""
    rows = conn.execute(
        "SELECT value FROM trade_pricing WHERE trade = ? ORDER BY value", (trade,)
    ).fetchall()
    values = [float(r["value"]) for r in rows]
    if not values:
        return None
    return (
        _percentile(values, 10.0),
        _percentile(values, 50.0),
        _percentile(values, 90.0),
    )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolated percentile (values must be sorted ascending)."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low_idx = int(rank)
    high_idx = min(low_idx + 1, len(sorted_values) - 1)
    frac = rank - low_idx
    return sorted_values[low_idx] * (1 - frac) + sorted_values[high_idx] * frac


# ---------------------------------------------------------------------------
# Semantic closeout matching (cosine over baked vectors — no model load)
# ---------------------------------------------------------------------------
def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Uses numpy when available, else a pure-Python fallback."""
    try:
        import numpy as np  # optional acceleration; not required for correctness

        va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except ImportError:
        import math

        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return 0.0 if na == 0.0 or nb == 0.0 else dot / (na * nb)


def _embed_query(conn: sqlite3.Connection, query_text: str) -> list[float]:
    """Embed the query in the *same* space the DB was baked with — offline by default."""
    method = _meta(conn, "embed_method", "deterministic")
    dim = int(_meta(conn, "embed_dim", "256"))
    if method == "deterministic":
        return deterministic_embedding(query_text, dim=dim)
    # A MiniLM-baked DB (opt-in) needs the model to embed the query; lazily delegate.
    from db.embeddings import build_embeddings  # lazy — only on the non-demo path

    return build_embeddings([query_text])[0]


def _meta(conn: sqlite3.Connection, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def semantic_closeout_matches(
    conn: sqlite3.Connection, query_text: str, trade: str, k: int = 5
) -> list[tuple[str, float]]:
    """Top-``k`` (firm_id, score) by cosine of the query against baked closeout
    vectors, restricted to firms that do ``trade``. A firm's score is the best
    score over its chunks. Deterministic and offline."""
    trade_firm_ids = {firm.firm_id for firm in firms_for_trade(conn, trade)}
    if not trade_firm_ids:
        return []
    query_vec = _embed_query(conn, query_text)

    best: dict[str, float] = {}
    rows = conn.execute("SELECT firm_id, vector FROM closeout_embeddings").fetchall()
    for row in rows:
        firm_id = row["firm_id"]
        if firm_id not in trade_firm_ids:
            continue
        score = _cosine(query_vec, json.loads(row["vector"]))
        score = max(0.0, min(1.0, score))  # clamp into [0, 1] for the Candidate contract
        if score > best.get(firm_id, -1.0):
            best[firm_id] = score

    ranked = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:k]
