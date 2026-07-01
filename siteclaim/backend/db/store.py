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
import sqlite3
from pathlib import Path
from typing import Optional

from schemas.models import Evidence, FirmProfile, RiskFlag, Severity, SignalType
from db.embeddings import deterministic_embedding

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "sitesource.db"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Open the SiteSource DB read-only-ish (a plain connection with Row access)."""
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
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


def _json_obj(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


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


def _row_keys(row: sqlite3.Row) -> set[str]:
    return set(row.keys())


def _firm_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> FirmProfile:
    firm_id = row["firm_id"]
    keys = _row_keys(row)
    return FirmProfile(
        firm_id=firm_id,
        name=row["name_en"],
        registered_grade=row["registered_grade"] or "",
        value_band=row["value_band"] or "",
        trades=_json_list(row["trades"]),
        public_flags=_public_flag_rows(conn, firm_id) + _closeout_flag_rows(conn, firm_id),
        closeout_summary=row["closeout_summary"] or "",
        award_history=_award_strings(conn, firm_id),
        enquiry_email=(row["enquiry_email"] or "") if "enquiry_email" in keys else "",
        description=(row["description"] or "") if "description" in keys else "",
        registered_trades=_json_list(row["registered_trades"]) if "registered_trades" in keys else [],
        reg_date=(row["reg_date"] or "") if "reg_date" in keys else "",
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


def eos_firm_ids(conn: sqlite3.Connection) -> set[str]:
    """Firm ids that carry an **assessable EOS closeout record** (baked closeout
    chunks). The per-tender shortlist is drawn only from these; the wider
    public-record pool is screened and counted but not auto-shortlisted."""
    rows = conn.execute("SELECT DISTINCT firm_id FROM closeout_embeddings").fetchall()
    return {row["firm_id"] for row in rows}


def register_firm_ids(conn: sqlite3.Connection) -> set[str]:
    """Firm ids drawn from the real CIC register (provenance ``public_register``) —
    the genuine subcontractor pool, as opposed to the illustrative/benchmark rows."""
    rows = conn.execute("SELECT firm_id FROM firms WHERE provenance = ?", (_REAL,)).fetchall()
    return {row["firm_id"] for row in rows}


def shortlistable_firms_for_trade(conn: sqlite3.Connection, trade: str) -> list[FirmProfile]:
    """Firms in ``trade`` the platform surfaces for a per-tender shortlist. Three
    kinds qualify, so the genuine register pool is not hidden behind the private
    closeout archive:

    * firms with an **assessable EOS closeout** report we hold,
    * firms with a **public award** record, and
    * any **trade-matched firm on the real CIC register**.

    Only the illustrative/benchmark rows that are neither assessed nor on the register
    are withheld. The match scoring and the per-section cap that keep this readable are
    applied downstream in :func:`db.cross_reference.cross_reference`."""
    assessable = eos_firm_ids(conn)
    register = register_firm_ids(conn)
    return [
        firm
        for firm in firms_for_trade(conn, trade)
        if firm.firm_id in assessable or firm.award_history or firm.firm_id in register
    ]


_REAL = "public_register"


def coverage(conn: sqlite3.Connection) -> dict:
    """Live database-coverage figures for the UI's screening line — counting **only
    real-provenance firms** (the actual Hong Kong registry scrape). The illustrative
    demo firms (fabricated, placeholder references) are deliberately excluded, so the
    'sourced from official registers … linked to its government source' claim holds."""
    total = conn.execute("SELECT COUNT(*) AS n FROM firms WHERE provenance = ?", (_REAL,)).fetchone()["n"]
    # The CIC-register firms carry a Business Registration No.; the overlay rows
    # (enforcement/offer records not on the register) do not — so the headline can
    # state its composition rather than read as a bare total.
    register_count = conn.execute(
        "SELECT COUNT(*) AS n FROM firms WHERE provenance = ? AND br_no IS NOT NULL AND br_no != ''",
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
    trades: set[str] = set()
    for row in conn.execute("SELECT trades FROM firms WHERE provenance = ?", (_REAL,)):
        trades |= set(_json_list(row["trades"]))
    flag_sources = [
        row["source"]
        for row in conn.execute(
            "SELECT DISTINCT pf.source AS source FROM public_flags pf "
            "JOIN firms f ON f.firm_id = pf.firm_id WHERE f.provenance = ? AND pf.source IS NOT NULL "
            "AND pf.source != '' ORDER BY pf.source",
            (_REAL,),
        )
    ]
    return {
        "total_firms": int(total),
        "flagged_firms": int(flagged),
        "register_count": int(register_count),
        "overlay_count": int(total) - int(register_count),
        "flagged_count": int(flagged),
        "flags_by_type": flags_by_type,
        "trades": sorted(trades),
        "flag_sources": flag_sources,
        "registers": len(flag_sources),
        "provenance": _REAL,
    }


def _firm_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    flags = conn.execute(
        "SELECT signal_type, label, date, source, reference FROM public_flags "
        "WHERE firm_id = ? ORDER BY signal_type",
        (row["firm_id"],),
    ).fetchall()
    return {
        "firm_id": row["firm_id"],
        "name_en": row["name_en"],
        "name_zh": row["name_zh"],
        "registered_grade": row["registered_grade"] or "",
        "value_band": row["value_band"] or "",
        "trades": _json_list(row["trades"]),
        "registered_trades": _json_list(row["registered_trades"]),
        "description": row["description"] or "",
        "enquiry_email": row["enquiry_email"] or "",
        "br_no": row["br_no"] or "",
        "reg_date": row["reg_date"] or "",
        "expiry_date": row["expiry_date"] or "",
        "public_flags": [dict(flag) for flag in flags],
    }


_FIRM_SORTS = {
    "name": "name_en COLLATE NOCASE ASC",
    "name_desc": "name_en COLLATE NOCASE DESC",
}


def paged_firms(
    conn: sqlite3.Connection, *, limit: int = 25, offset: int = 0, q: str = "", sort: str = "name"
) -> dict:
    """A page of real-provenance registry firms, alphabetical by default. Server-side
    only — never load the whole register into the client. ``q`` is a case-insensitive
    name search. Returns ``{items, total, limit, offset}``; each item carries its
    description, enquiry_email and registration dates."""
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    order = _FIRM_SORTS.get(sort, _FIRM_SORTS["name"])
    where = "provenance = ?"
    params: list[object] = [_REAL]
    needle = (q or "").strip()
    if needle:
        where += " AND name_en LIKE ? COLLATE NOCASE"
        params.append(f"%{needle}%")
    total = conn.execute(f"SELECT COUNT(*) AS n FROM firms WHERE {where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM firms WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return {
        "items": [_firm_dict(conn, row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


def firm_full_by_id(conn: sqlite3.Connection, firm_id: str) -> dict | None:
    """Full firm profile for the detail modal — all columns plus award history with
    source URLs and public flags with citation references."""
    row = conn.execute("SELECT * FROM firms WHERE firm_id = ?", (firm_id,)).fetchone()
    if row is None:
        return None
    keys = _row_keys(row)
    flags = conn.execute(
        "SELECT signal_type, label, date, source, reference FROM public_flags "
        "WHERE firm_id = ? ORDER BY signal_type",
        (firm_id,),
    ).fetchall()
    awards = conn.execute(
        "SELECT project, client, year, source FROM award_history "
        "WHERE firm_id = ? ORDER BY year DESC",
        (firm_id,),
    ).fetchall()
    return {
        "firm_id": row["firm_id"],
        "name_en": row["name_en"],
        "name_zh": row["name_zh"],
        "registered_grade": row["registered_grade"] or "",
        "value_band": row["value_band"] or "",
        "registers": _json_list(row["registers"]),
        "trades": _json_list(row["trades"]),
        "registered_trades": _json_list(row["registered_trades"]),
        "description": row["description"] or "",
        "enquiry_email": row["enquiry_email"] or "",
        "br_no": row["br_no"] or "",
        "reg_date": row["reg_date"] or "",
        "expiry_date": row["expiry_date"] or "",
        "public_flags": [
            {"signal_type": fl["signal_type"], "label": fl["label"],
             "date": fl["date"], "source": fl["source"], "reference": fl["reference"]}
            for fl in flags
        ],
        "award_history": [
            {"project": aw["project"] or "", "client": aw["client"],
             "year": aw["year"], "source": aw["source"]}
            for aw in awards
        ],
        "provenance": row["provenance"],
        # The curated, verifiable profile (overview, services, notable projects, ...)
        # for the firms that genuinely do these trades; empty for register-only firms.
        "profile": _json_obj(row["profile"]) if "profile" in keys else {},
    }


def real_firms(conn: sqlite3.Connection) -> list[dict]:
    """All real-provenance registry firms (used by tests / internal callers). The API
    serves :func:`paged_firms` instead — never load the full register in the client."""
    rows = conn.execute(
        "SELECT * FROM firms WHERE provenance = ? ORDER BY name_en COLLATE NOCASE",
        (_REAL,),
    ).fetchall()
    return [_firm_dict(conn, row) for row in rows]


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
