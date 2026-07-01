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
DEFAULT_DB_PATH = _HERE / "sitesource.db"       # profile 'demo' (real + illustrative firms)
LIVE_DB_PATH = _HERE / "sitesource_live.db"     # profile 'live' (clean real firms only)
SEED_VERSION = "1"

# Profiles. 'demo' is the pitch database (real + the 16 illustrative firms + their
# fabricated EOS records, pricing, and contacts). 'live' is the clean engine database:
# only the real public-register firms, none of the fabricated layer. The mode flag on
# cross_reference (include_public) is what lets the live engine shortlist real firms
# against this clean database; see BUILD_PLAN.md sections 3 and 6.
PROFILES = ("demo", "live")
_REAL = "public_register"

# Reuse the Layer-1 taxonomy normaliser to screen real-scrape trade names (e.g.
# "fire services", "mechanical and plumbing") into canonical keys at build time.
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))
from rules_engine.taxonomy import normalize as _normalize_trade  # noqa: E402


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
def build_database(db_path: Path | str | None = None, *, profile: str = "demo") -> dict:
    """(Re)build the SQLite database at ``db_path``. Returns a small summary.

    ``profile='demo'`` (default) builds the full pitch database — real firms
    plus the 16 illustrative firms and their fabricated EOS records, pricing and
    contacts. ``profile='live'`` builds the clean engine database: only the real
    ``public_register`` firms, with none of the fabricated layer (no illustrative
    firms, no EOS closeouts/embeddings, no illustrative pricing, no illustrative
    contacts). The default is unchanged so the committed demo DB and every hermetic
    test stay untouched.

    When ``db_path`` is None the path is derived from the profile (demo →
    ``sitesource.db``, live → ``sitesource_live.db``); an explicit ``db_path`` always
    wins.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r} (use one of {PROFILES})")
    db_path = Path(db_path) if db_path is not None else (DEFAULT_DB_PATH if profile == "demo" else LIVE_DB_PATH)

    public, provenance_by_id = _load_public_records()
    # The live engine carries only real public data; the fabricated layer (illustrative
    # firms' EOS records, pricing, contacts) is demo-only and skipped entirely for live.
    eos = _load_records("eos") if profile == "demo" else []
    pricing = _load_records("pricing") if profile == "demo" else []
    contacts = _load_records("contacts") if profile == "demo" else []

    public_by_id = {r["firm_id"]: r for r in public}
    eos_by_id = {r["firm_id"]: r for r in eos}
    firm_ids = sorted(set(public_by_id) | set(eos_by_id))
    if profile == "live":
        # Keep only real-provenance firms — drop the 16 illustrative stubs. Provenance
        # (not an id-prefix guess) is the source-of-truth discriminator.
        firm_ids = [fid for fid in firm_ids if provenance_by_id.get(fid) == _REAL]

    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

        chunk_rows: list[tuple[str, int, str]] = []  # (firm_id, chunk_id, text)
        for fid in firm_ids:
            pub = public_by_id.get(fid, {})
            rep = eos_by_id.get(fid, {})

            conn.execute(
                "INSERT INTO firms (firm_id, name_en, name_zh, registered_grade, value_band, "
                "registers, trades, closeout_summary, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fid,
                    pub.get("name_en") or fid,
                    pub.get("name_zh"),
                    pub.get("registered_grade"),
                    pub.get("value_band"),
                    json.dumps(pub.get("registers", [])),
                    json.dumps(_canonical_trades(pub.get("trades", []))),
                    rep.get("closeout_summary", ""),
                    provenance_by_id.get(fid, "illustrative"),
                ),
            )
            for flag in pub.get("public_flags", []):
                conn.execute(
                    "INSERT INTO public_flags (firm_id, signal_type, label, date, source, reference) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fid, flag["signal_type"], flag["label"], flag.get("date"), flag.get("source"), flag.get("reference")),
                )
            for proj in rep.get("projects", []):
                conn.execute(
                    "INSERT INTO project_closeouts (firm_id, project, client, year, delayed, note, source, reference) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (fid, proj.get("project"), proj.get("client"), proj.get("year"),
                     int(proj.get("delayed", 0)), proj.get("note"), proj.get("source"), proj.get("reference")),
                )
            for award in pub.get("award_history", []):
                conn.execute(
                    "INSERT INTO award_history (firm_id, project, client, year, source) VALUES (?, ?, ?, ?, ?)",
                    (fid, award.get("project"), award.get("client"), award.get("year"), award.get("source")),
                )
            for idx, text in enumerate(rep.get("report_text", [])):
                if text and text.strip():
                    chunk_rows.append((fid, idx, text.strip()))

        for row in pricing:
            conn.execute(
                "INSERT INTO trade_pricing (trade, value, project, year, source, reference) VALUES (?, ?, ?, ?, ?, ?)",
                (row["trade"], float(row["value"]), row.get("project"), row.get("year"), row.get("source"), row.get("reference")),
            )

        # Address book — only for firms that exist (the foreign key holds); a contact
        # for an unknown firm_id is skipped rather than crashing the build.
        known_firms = set(firm_ids)
        contacts_written = 0
        for row in contacts:
            if row.get("firm_id") not in known_firms or not row.get("email") or not row.get("trade"):
                continue
            conn.execute(
                "INSERT OR REPLACE INTO contacts (firm_id, trade, contact_name, email, phone, note) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["firm_id"], row["trade"], row.get("contact_name"), row["email"], row.get("phone"), row.get("note")),
            )
            contacts_written += 1

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
            "profile": profile,
            "built_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "firm_count": str(len(firm_ids)),
        }.items():
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, value))

        conn.commit()
    finally:
        conn.close()

    return {
        "db_path": str(db_path),
        "profile": profile,
        "firms": len(firm_ids),
        "public_records": len(public),
        "eos_reports": len(eos),
        "pricing_samples": len(pricing),
        "contacts": contacts_written,
        "closeout_chunks": len(chunk_rows),
        "embed_method": method,
        "embed_dim": dim,
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m db.seed",
        description="Build the SiteSource database. 'demo' is the full pitch DB "
        "(real + illustrative); 'live' is the clean real-firm-only engine DB.",
    )
    parser.add_argument("--profile", choices=PROFILES, default="demo", help="which database to build (default: demo)")
    parser.add_argument("--out", default=None, help="output path (default: derived from the profile)")
    args = parser.parse_args(argv)

    summary = build_database(args.out, profile=args.profile)
    print("Built SiteSource DB:")
    for key, value in summary.items():
        print(f"  {key:>16}: {value}")
    if summary["public_records"] == 0:
        print("  note: no public records found — built from the EOS archive alone.")


if __name__ == "__main__":
    main()
