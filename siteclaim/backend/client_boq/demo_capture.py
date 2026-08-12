"""Capture one real tender as a committable demo, and replay it offline.

WHY THIS EXISTS. Every feature in this module was verified by driving a live tender and paying for
it — the bid gate, coverage, combine-pricing, conservation, the schedule reader, the absence sweep.
That is not repeatable for a demo, a new joiner, or a regression check. One captured tender turns
"spend twenty dollars and twenty minutes" into "open the app".

THE CAPTURE IS THE REAL RUN, NOT A TIDIED ONE. It carries the arithmetic mismatches, the unread
cells, the partial coverage, the combine gaps and the placeholder warnings, because a demo where
everything is clean teaches the wrong thing about the product and hides exactly the surfaces that
took longest to build. Nothing here repairs, completes or sorts anything: it copies rows.

WHAT IS DELIBERATELY LEFT BEHIND
--------------------------------
Three kinds of thing, and the reason differs for each:

* **Contact details and identity.** `db/sitesource.db` holds a real `enquiry_email` for 1,365 of
  its 1,423 firms, and `fixtures/out/outbox.json` carries composed enquiries addressed to them.
  A demo that shipped those would publish a subcontractor mailing list. Every `*_by` column —
  who approved, who ticked, who confirmed — is replaced with a placeholder for the same reason at
  a smaller scale: an operator's name is not part of the product.
* **Anything that could act.** No Gmail token, no API key. Neither is stored in the tables this
  walks, and the sweep below asserts that rather than trusting it.
* **The procurement database.** The firm corpus is not a client_boq artifact and is far too large
  to embed. A captured tender's Sourcing screen therefore shows the shortlist that was RECORDED,
  not one recomputed against 1,423 firms.

WHAT IS NOT CAPTURED BECAUSE IT IS DERIVED
------------------------------------------
Most of the app. The priced bill, the checks, the coverage classification, the conservation
verdict, the combine, every total and every gate sentence are computed at read time from the rows
below — so capturing them would create a second copy that could disagree with the engine. The rule
for deciding: if an endpoint computes it, do not capture it; if a person or a model wrote it,
capture it.

RUNNING IT
----------
On the machine that holds the run::

    DEMO_MODE=false python -m client_boq.demo_capture export --set-id nd-2025-04-... \\
        --out ../fixtures/cases/client_boq/demo_tender.json

then commit the JSON. To replay::

    DEMO_MODE=true python -m client_boq.demo_capture load

which writes into the demo database only — it refuses to run against a live one, because a demo
tender in the live shelf is exactly the mixing this whole design is against.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from pipeline.llm_client import demo_mode

from client_boq import models, store

#: Every table a tender's own state lives in, in an order safe to insert.
#:
#: NOT `client_boq_settings`, `client_boq_team_members`, `client_boq_rates`, `client_boq_criteria`,
#: `client_boq_threshold_rules` or `client_boq_costing_models` — those are app-wide libraries
#: rather than one tender's work. Shipping the criteria library inside a tender would make a demo
#: silently overwrite an installation's edited copy of it.
TENDER_TABLES = (
    "client_boq_document_sets",
    "client_boq_set_meta",
    "client_boq_manifests",
    "client_boq_documents",
    "client_boq_parts",
    "client_boq_part_revisions",
    "client_boq_changes",
    "client_boq_review_registers",
    "client_boq_docmaps",
    "client_boq_estimate_scope",
    "client_boq_scope_items",
    "client_boq_estimates",
    "client_boq_schedules",
    "client_boq_letters",
    "client_boq_outputs",
    "client_boq_bill_revisions",
    "client_boq_bill_rates",
    "client_boq_item_assumptions",
    "client_boq_costing_state",
    "client_boq_set_costing_model",
    "client_boq_coverage_ticks",
    "client_boq_sweep_costs",
    "client_boq_conditions",
    "client_boq_station_schedules",
    "client_boq_station_classes",
    "client_boq_hole_groups",
    "client_boq_site_criteria",
    "client_boq_site_photos",
    "client_boq_rfi_batches",
    "client_boq_rfi_items",
)

#: Column names holding a person. Replaced with :data:`PLACEHOLDER_ACTOR` — never blanked, because
#: "nobody approved this" and "somebody approved this and we removed their name" are different
#: facts, and the gates read the first as unapproved.
ACTOR_COLUMNS = re.compile(
    r"(_by|^actor|^owner_id|^approved_by|^updated_by|^confirmed_by|^ticked_by|^decided_by)$")
PLACEHOLDER_ACTOR = "demo"

#: What must never appear in a capture. Checked as a sweep over the serialised bundle rather than
#: per column, because the risk is a blob: a register, a letter or an outputs row is JSON text and
#: an address inside one would pass any column-name rule.
FORBIDDEN = (
    # An email address that is not obviously a placeholder.
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an email address"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"), "something shaped like an API key"),
    (re.compile(r"\bya29\.[A-Za-z0-9_-]{10,}"), "something shaped like a Google OAuth token"),
    (re.compile(r'"refresh_token"'), "a refresh token"),
)
#: Addresses that are obviously not a real person's. Kept so a letter template reading
#: "you@example.com" does not fail the sweep.
ALLOWED_EMAIL = re.compile(r"@(example\.(com|org|net)|localhost)$", re.I)

BUNDLE_VERSION = 1


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _redact_row(row: dict) -> dict:
    """One row with every person's name replaced. Pure."""
    return {k: (PLACEHOLDER_ACTOR if ACTOR_COLUMNS.search(k) and str(v or "").strip() else v)
            for k, v in row.items()}


def export_set(conn: sqlite3.Connection, set_id: str) -> dict:
    """Every row of one tender, redacted, as a plain dict ready for `json.dump`.

    Reads; never writes. Safe to run against a live database, which is the only place the real run
    exists — so it must not be the kind of tool that needs a copy taken first.
    """
    bundle: dict = {"version": BUNDLE_VERSION, "set_id": set_id, "tables": {}}
    for table in TENDER_TABLES:
        try:
            cols = _columns(conn, table)
        except sqlite3.OperationalError:
            continue                      # a table this installation has not created yet
        if "set_id" not in cols:
            continue
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE set_id = ?", (set_id,))]
        if rows:
            bundle["tables"][table] = [_redact_row(r) for r in rows]
    return bundle


def offences(bundle: dict) -> list[str]:
    """Everything in this bundle that must not ship, named. Empty means it is safe to commit.

    Over the SERIALISED bundle, not per column: a register, a letter and an outputs row are all
    JSON text, and an address inside one of those blobs would pass any column-name rule. This is
    the check that decides whether a capture is publishable, so it looks where the risk is.
    """
    text = json.dumps(bundle, ensure_ascii=False)
    found: list[str] = []
    for pattern, what in FORBIDDEN:
        for hit in set(pattern.findall(text)):
            value = hit if isinstance(hit, str) else str(hit)
            if what == "an email address" and ALLOWED_EMAIL.search(value):
                continue
            found.append(f"{what}: {value[:60]}")
    return sorted(found)


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load_bundle(conn: sqlite3.Connection, bundle: dict, *, replace: bool = True) -> dict:
    """Write a captured tender into this database. Returns a per-table count.

    ``replace`` clears the set's existing rows first, so re-loading is idempotent rather than
    doubling every list. It only ever touches rows whose ``set_id`` is the bundle's own.
    """
    if bundle.get("version") != BUNDLE_VERSION:
        raise ValueError(f"this bundle is version {bundle.get('version')!r}, not {BUNDLE_VERSION}")
    set_id = bundle["set_id"]
    models.init_tables(conn)
    written: dict[str, int] = {}
    for table, rows in bundle.get("tables", {}).items():
        if table not in TENDER_TABLES:
            raise ValueError(f"{table!r} is not a tender table; refusing to write it")
        cols = _columns(conn, table)
        if replace:
            conn.execute(f"DELETE FROM {table} WHERE set_id = ?", (set_id,))
        for row in rows:
            # Only columns this installation actually has, so a bundle captured on a newer schema
            # loads on an older one with the extra fields dropped rather than failing outright.
            keep = {k: v for k, v in row.items() if k in cols}
            names = ", ".join(keep)
            marks = ", ".join("?" for _ in keep)
            conn.execute(f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({marks})",
                         tuple(keep.values()))
        written[table] = len(rows)
    conn.commit()
    return written


def bundled_path() -> Path:
    """Where the committed capture lives, beside the per-call fixtures it complements."""
    return Path(__file__).resolve().parent.parent / "fixtures" / "cases" / "client_boq" / \
        "demo_tender.json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cmd_export(args) -> int:
    conn = store.get_conn()
    try:
        bundle = export_set(conn, args.set_id)
    finally:
        conn.close()
    if not bundle["tables"]:
        print(f"no rows for set {args.set_id!r} — is the set id right, and is SITESOURCE_DB "
              f"pointing at the database that holds the run?", file=sys.stderr)
        return 1
    bad = offences(bundle)
    if bad and not args.force:
        print("REFUSING TO WRITE — this capture contains things that must not ship:",
              file=sys.stderr)
        for note in bad:
            print(f"  {note}", file=sys.stderr)
        print("\nRemove them at source and re-export. --force writes anyway, and is only for "
              "checking what a capture would look like.", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else bundled_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(len(v) for v in bundle["tables"].values())
    print(f"wrote {out} — {total} row(s) across {len(bundle['tables'])} table(s)")
    for table, rows in sorted(bundle["tables"].items()):
        print(f"  {table}: {len(rows)}")
    if bad:
        print("\nWARNING: written with --force and it carries:", file=sys.stderr)
        for note in bad:
            print(f"  {note}", file=sys.stderr)
    return 0


def _cmd_load(args) -> int:
    # THE ONE REFUSAL IN THIS FILE. A captured tender in the live shelf is exactly the mixing the
    # whole demo/live design exists to prevent, and it would be silent: the rows are valid.
    if not demo_mode() and not args.i_know_this_is_live:
        print("refusing to load a demo tender outside DEMO mode — it would appear in the live "
              "shelf beside real tenders. Set DEMO_MODE=true (or pass --i-know-this-is-live).",
              file=sys.stderr)
        return 2
    path = Path(args.path) if args.path else bundled_path()
    if not path.is_file():
        print(f"no capture at {path}. Run `export` on the machine that holds the run first.",
              file=sys.stderr)
        return 1
    bundle = json.loads(path.read_text(encoding="utf-8"))
    conn = store.get_conn()
    try:
        written = load_bundle(conn, bundle)
    finally:
        conn.close()
    print(f"loaded {bundle['set_id']} from {path}")
    for table, n in sorted(written.items()):
        print(f"  {table}: {n}")
    return 0


def _cmd_check(args) -> int:
    path = Path(args.path) if args.path else bundled_path()
    if not path.is_file():
        print(f"no capture at {path}", file=sys.stderr)
        return 1
    bad = offences(json.loads(path.read_text(encoding="utf-8")))
    for note in bad:
        print(note)
    print("clean" if not bad else f"{len(bad)} thing(s) that must not ship")
    return 0 if not bad else 2


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m client_boq.demo_capture",
        description="Capture one real tender as a committable demo, and replay it offline.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="read one tender out of the current database")
    ex.add_argument("--set-id", required=True)
    ex.add_argument("--out", default="")
    ex.add_argument("--force", action="store_true",
                    help="write even if the capture carries something that must not ship")
    ex.set_defaults(func=_cmd_export)

    ld = sub.add_parser("load", help="write a captured tender into the demo database")
    ld.add_argument("--path", default="")
    ld.add_argument("--i-know-this-is-live", action="store_true")
    ld.set_defaults(func=_cmd_load)

    ck = sub.add_parser("check", help="say whether a capture is safe to commit")
    ck.add_argument("--path", default="")
    ck.set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover — the entry point itself
    raise SystemExit(main())
