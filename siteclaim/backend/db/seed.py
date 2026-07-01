"""Build ``sitesource.db`` from the provenance-separated seed sources.

Two sources are fused, because they have different provenance:

* ``seed_data/eos/``   — our private End-of-Site closeout archive (the exclusive
  layer). In production this is ingested from a partner contractor's real closeout
  files. It supplies the closeout narrative (embedded) and the per-project records.
* ``seed_data/public/`` — public-signal records. Today a small mock stub covering
  the demo firms; later AI Research drops real scraped Hong Kong public records here
  in the **same record shape** and the loader picks them up with no code change.
  The public layer may be empty or partial — the loader tolerates that and builds
  from the EOS archive alone without error.

Embeddings over the closeout text are computed **once, here**, and baked into
``closeout_embeddings`` so the shipped DB needs no model and no network at runtime.
By default we bake the dependency-free deterministic embedding (fully offline and
reproducible); set ``SITESOURCE_USE_MINILM=1`` to bake MiniLM vectors instead.

Run it:  ``python -m backend.db.seed``  (or ``python -m db.seed`` from ``backend/``).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import sys
from pathlib import Path

from .embeddings import DETERMINISTIC_DIM, build_embeddings, deterministic_embedding

_HERE = Path(__file__).resolve().parent
SCHEMA_PATH = _HERE / "schema.sql"
SEED_DATA_DIR = _HERE / "seed_data"
CSV_REGISTER_PATH = SEED_DATA_DIR / "source" / "RSRC_01_combined.csv"
DEFAULT_DB_PATH = _HERE / "sitesource.db"
SEED_VERSION = "2"

# Reuse the Layer-1 taxonomy normaliser to screen real-scrape trade names (e.g.
# "fire services", "mechanical and plumbing") into canonical keys at build time.
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))
from rules_engine.taxonomy import normalize as _normalize_trade  # noqa: E402,F401
from db import register_loader  # noqa: E402


def _canonical_trades(raw_trades: list[str]) -> list[str]:
    """Screen raw trade names against the taxonomy; keep canonical keys and preserve
    an unmapped trade rather than drop it. De-duplicated, order-stable."""
    out: list[str] = []
    for trade in raw_trades or []:
        key = _normalize_trade(trade) or trade
        if key not in out:
            out.append(key)
    return out



# ---------------------------------------------------------------------------
# Source loading (tolerant: missing or empty directories are fine)
# ---------------------------------------------------------------------------
# The one illustrative demo stub under seed_data/public/. Every OTHER file there is
# a real registry scrape, so its firms carry 'public_register' provenance.
ILLUSTRATIVE_STUB = "seed_public_records.json"


def _load_records(subdir: str) -> list[dict]:
    """Read every ``*.json`` under ``seed_data/<subdir>`` and flatten to records.

    A future scrape file dropped alongside the stub is picked up automatically.
    Each file may be a JSON array or a single object.
    """
    folder = SEED_DATA_DIR / subdir
    if not folder.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            records.extend(data)
        elif isinstance(data, dict):
            records.append(data)
    return records


def _load_public_records() -> tuple[list[dict], dict[str, str]]:
    """Public records plus a provenance map per firm_id. The illustrative stub is
    'illustrative'; every other file (the real Hong Kong registry scrape) is
    'public_register'. Provenance lets the coverage claim count only real firms."""
    folder = SEED_DATA_DIR / "public"
    records: list[dict] = []
    provenance: dict[str, str] = {}
    if not folder.is_dir():
        return records, provenance
    for path in sorted(folder.glob("*.json")):
        prov = "illustrative" if path.name == ILLUSTRATIVE_STUB else "public_register"
        data = json.loads(path.read_text(encoding="utf-8"))
        for rec in data if isinstance(data, list) else [data]:
            records.append(rec)
            if rec.get("firm_id"):
                provenance[rec["firm_id"]] = prov
    return records, provenance


# ---------------------------------------------------------------------------
# Embedding (baked once at build time)
# ---------------------------------------------------------------------------
def _bake_vectors(texts: list[str]) -> tuple[list[list[float]], str, int]:
    """Return (vectors, method, dim). MiniLM is opt-in and falls back to
    deterministic if sentence-transformers is unavailable, so the build never
    fails offline."""
    want_minilm = os.getenv("SITESOURCE_USE_MINILM", "").strip().lower() in {"1", "true", "yes", "on"}
    if want_minilm and texts:
        try:
            vectors = build_embeddings(texts)
            return vectors, "minilm", len(vectors[0]) if vectors else DETERMINISTIC_DIM
        except Exception as exc:  # noqa: BLE001 — any ST/Torch failure -> deterministic
            print(f"  [seed] MiniLM unavailable ({exc!r}); baking deterministic vectors instead.")
    vectors = [deterministic_embedding(t) for t in texts]
    return vectors, "deterministic", DETERMINISTIC_DIM


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build_database(db_path: Path | str = DEFAULT_DB_PATH) -> dict:
    """(Re)build the SQLite database at ``db_path``. Returns a small summary."""
    db_path = Path(db_path)
    public, provenance_by_id = _load_public_records()
    eos = _load_records("eos")
    pricing = _load_records("pricing")
    eos_by_id = {r["firm_id"]: r for r in eos}

    # The real CIC register is the public_register base; curated records (offers,
    # awards, enforcement flags) are fused onto their matching register row, and the
    # illustrative/demo stub stays its own (excluded-from-coverage) layer.
    curated_real = [r for r in public if provenance_by_id.get(r["firm_id"]) == "public_register"]
    illustrative = [r for r in public if provenance_by_id.get(r["firm_id"]) != "public_register"]
    register = register_loader.load_csv_register(CSV_REGISTER_PATH)
    public_firms = register_loader.merge_register(register, curated_real, eos_by_id)
    illus_firms = [register_loader.illustrative_firm(r, eos_by_id.get(r["firm_id"], {})) for r in illustrative]
    all_firms = public_firms + illus_firms

    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        chunk_rows: list[tuple[str, int, str]] = []  # (firm_id, chunk_id, text)
        for firm in all_firms:
            fid = firm["firm_id"]
            profile = firm.get("profile")
            conn.execute(
                "INSERT INTO firms (firm_id, name_en, name_zh, registered_grade, value_band, registers, "
                "trades, registered_trades, closeout_summary, description, enquiry_email, br_no, address, "
                "phone, fax, reg_date, expiry_date, profile, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fid,
                    firm["name_en"],
                    firm.get("name_zh"),
                    firm.get("registered_grade"),
                    firm.get("value_band"),
                    json.dumps(firm.get("registers", [])),
                    json.dumps(firm.get("trades", [])),
                    json.dumps(firm.get("registered_trades", [])),
                    firm.get("closeout_summary", ""),
                    firm.get("description", ""),
                    firm.get("enquiry_email", ""),
                    firm.get("br_no", ""),
                    firm.get("address", ""),
                    firm.get("phone", ""),
                    firm.get("fax", ""),
                    firm.get("reg_date", ""),
                    firm.get("expiry_date", ""),
                    json.dumps(profile) if profile else None,
                    firm["provenance"],
                ),
            )
            for flag in firm.get("public_flags", []):
                conn.execute(
                    "INSERT INTO public_flags (firm_id, signal_type, label, date, source, reference) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fid, flag["signal_type"], flag["label"], flag.get("date"), flag.get("source"), flag.get("reference")),
                )
            for proj in firm.get("projects", []):
                conn.execute(
                    "INSERT INTO project_closeouts (firm_id, project, client, year, delayed, note, source, reference) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (fid, proj.get("project"), proj.get("client"), proj.get("year"),
                     int(proj.get("delayed", 0)), proj.get("note"), proj.get("source"), proj.get("reference")),
                )
            for award in firm.get("award_history", []):
                conn.execute(
                    "INSERT INTO award_history (firm_id, project, client, year, source) VALUES (?, ?, ?, ?, ?)",
                    (fid, award.get("project"), award.get("client"), award.get("year"), award.get("source")),
                )
            for idx, text in enumerate(firm.get("report_text", [])):
                if text and text.strip():
                    chunk_rows.append((fid, idx, text.strip()))

        for row in pricing:
            conn.execute(
                "INSERT INTO trade_pricing (trade, value, project, year, source, reference) VALUES (?, ?, ?, ?, ?, ?)",
                (row["trade"], float(row["value"]), row.get("project"), row.get("year"), row.get("source"), row.get("reference")),
            )

        # Bake embeddings once over whatever closeout text exists.
        texts = [text for (_fid, _cid, text) in chunk_rows]
        vectors, method, dim = _bake_vectors(texts)
        for (fid, cid, text), vec in zip(chunk_rows, vectors):
            conn.execute(
                "INSERT INTO closeout_embeddings (firm_id, chunk_id, text, vector) VALUES (?, ?, ?, ?)",
                (fid, cid, text, json.dumps(vec)),
            )

        for key, value in {
            "embed_method": method,
            "embed_dim": str(dim),
            "seed_version": SEED_VERSION,
            "built_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "firm_count": str(len(all_firms)),
        }.items():
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, value))

        conn.commit()
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "firms": len(all_firms),
        "register_rows": len(register),
        "public_register": len(public_firms),
        "eos_reports": len(eos),
        "pricing_samples": len(pricing),
        "closeout_chunks": len(chunk_rows),
        "embed_method": method,
        "embed_dim": dim,
    }


def main() -> None:
    summary = build_database()
    print("Built SiteSource DB:")
    for key, value in summary.items():
        print(f"  {key:>16}: {value}")
    if summary["register_rows"] == 0:
        print("  note: register CSV not found — built from the curated records alone.")


if __name__ == "__main__":
    main()
