"""Which Particular Specification section governs which bill section — CONFIRMED BY A PERSON.

``spec_match`` proposes; this stores what a human decided. The split is the whole design. A title
match is good evidence and it is not a fact: on CEDD ND/2025/04 the bill headed "Ground
Investigation" is Bill **2** and the specification that governs it is PS **28**, so a machine that
confirms its own proposal is one bad match away from sending a firm the wrong specification with
nothing anywhere to say so. Confirming is cheap — once per tender, a handful of rows — and it is
the only thing standing between a plausible guess and a priced tender built on it.

**Nothing here proposes, and nothing here selects.** It records a decision and reads it back.
An UNCONFIRMED proposal has no row, and dispatch treats a missing row as "no mapping" — never as
the proposal (see ``relevant_docs.resolve_section_plan``).

Modelled on ``bridge/approvals.py`` rather than inventing a second pattern: the same lazy idempotent
DDL, the same ``UNIQUE`` from the first version so re-confirming updates in place instead of
accumulating rows read back in insertion order, and the same ``bridge_conn`` / ``run_ref_for``
identity handling with an ``*_on(conn, …)`` + connection-owning wrapper pair.

The row is ``(set_id, bill_section)``: one decision per bill section per tender. ``ps_section = ""``
is a real, storable decision — "I looked, and no specification section corresponds" — and it is
deliberately distinct from having no row at all, which means nobody has looked yet. Both fall to the
whole-specification path at dispatch; only one of them is a decision.

What the machine proposed is stored beside what the person chose (``proposed_ps_section``,
``proposed_confidence``). Two columns, and they are what later tells you whether the matcher is
worth trusting — whether operators agree with it or quietly correct it every time.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3

from pydantic import BaseModel


class ConfirmedSpec(BaseModel):
    """One confirmed bill-section -> PS-section decision, as stored."""

    bill_section: str
    ps_section: str = ""          # "" is a decision: no specification section corresponds
    bill_heading: str = ""
    ps_title: str = ""
    proposed_ps_section: str = ""  # what the matcher offered, for comparison against the choice
    proposed_confidence: str = ""  # exact | strong | weak | none
    confirmed_by: str = "operator"
    confirmed_at: str = ""

    @property
    def agreed_with_the_machine(self) -> bool:
        return self.ps_section == self.proposed_ps_section


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the bridge's specification-map table if absent (lazy DDL, idempotent).

    ``UNIQUE(set_id, bill_section)`` from the first version: a bill section has ONE governing
    decision, and correcting it must overwrite rather than leave the old answer behind for a reader
    ordering by ``id`` to find first. Adding the constraint later would cost a migration.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_spec_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id TEXT NOT NULL,
            bill_section TEXT NOT NULL,
            ps_section TEXT NOT NULL DEFAULT '',
            bill_heading TEXT NOT NULL DEFAULT '',
            ps_title TEXT NOT NULL DEFAULT '',
            proposed_ps_section TEXT NOT NULL DEFAULT '',
            proposed_confidence TEXT NOT NULL DEFAULT '',
            confirmed_by TEXT NOT NULL DEFAULT 'operator',
            confirmed_at TEXT NOT NULL,
            UNIQUE(set_id, bill_section)
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_spec_map_set ON bridge_spec_map(set_id);
        """
    )
    conn.commit()


def load_spec_map_on(conn: sqlite3.Connection, set_id: str) -> dict[str, ConfirmedSpec]:
    """``{bill_section: ConfirmedSpec}`` for one set, against a caller-owned connection.

    Confirmation order is preserved (``ORDER BY id``) so a mapping screen does not reshuffle under
    the operator between one visit and the next.
    """
    ensure_tables(conn)
    out: dict[str, ConfirmedSpec] = {}
    for row in conn.execute(
        "SELECT bill_section, ps_section, bill_heading, ps_title, proposed_ps_section, "
        "proposed_confidence, confirmed_by, confirmed_at FROM bridge_spec_map "
        "WHERE set_id = ? ORDER BY id",
        (set_id,),
    ).fetchall():
        out[row["bill_section"]] = ConfirmedSpec(**dict(row))
    return out


def save_spec_map_on(
    conn: sqlite3.Connection, set_id: str, confirmations: list[ConfirmedSpec] | list[dict],
    *, confirmed_by: str = "operator",
) -> dict[str, ConfirmedSpec]:
    """Replace the decision for EVERY bill section named. Returns the new state.

    Replace, not merge, and only for the sections named: the payload is the screen's current
    decisions for those sections, so a correction must overwrite. A bill section absent from the
    payload is left alone — that is a section this screen was not talking about, not one whose
    decision was withdrawn.

    A confirmation with a blank ``bill_section`` is refused: it would collide with every other blank
    under the UNIQUE constraint and there is no bill section it could mean.
    """
    ensure_tables(conn)
    stamp = _now()
    rows = [c if isinstance(c, ConfirmedSpec) else ConfirmedSpec(**c) for c in confirmations]
    for c in rows:
        section = (c.bill_section or "").strip()
        if not section:
            raise ValueError("a confirmation must name the bill section it decides")
        conn.execute(
            "INSERT INTO bridge_spec_map (set_id, bill_section, ps_section, bill_heading, ps_title,"
            " proposed_ps_section, proposed_confidence, confirmed_by, confirmed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(set_id, bill_section) DO UPDATE SET"
            "   ps_section = excluded.ps_section, bill_heading = excluded.bill_heading,"
            "   ps_title = excluded.ps_title, proposed_ps_section = excluded.proposed_ps_section,"
            "   proposed_confidence = excluded.proposed_confidence,"
            "   confirmed_by = excluded.confirmed_by, confirmed_at = excluded.confirmed_at",
            (set_id, section, (c.ps_section or "").strip(), c.bill_heading, c.ps_title,
             c.proposed_ps_section, c.proposed_confidence,
             (c.confirmed_by or "").strip() or confirmed_by, stamp),
        )
    conn.commit()
    return load_spec_map_on(conn, set_id)


def ps_specs_for_sections(spec_map: dict[str, ConfirmedSpec], sections: list[str]) -> set[str]:
    """The confirmed PS sections governing a dispatched unit's bill sections.

    A section with no row contributes nothing — an unconfirmed proposal must not select anything,
    which is the point of the whole module. A section confirmed as "no counterpart" contributes
    nothing either, and correctly: the answer was that no specification section governs it.
    """
    out: set[str] = set()
    for code in sections or []:
        row = spec_map.get((code or "").strip())
        if row and row.ps_section:
            out.add(row.ps_section)
    return out


# ---------------------------------------------------------------------------
# The connection-owning wrappers, exactly as approvals.py pairs them
# ---------------------------------------------------------------------------
def storage_key(set_id: str) -> str:
    """The key these rows are stored under: ``tender_slug(run_ref_for(set_id))``.

    THE ONE DELIBERATE DIVERGENCE FROM ``approvals.py``, and it is what made the confirmed map
    unreachable. Approvals are written and read from the bridge alone, so ``run_ref_for`` — the
    identity function — is enough. This map is written from the bridge under a ``set_id`` and read
    from the PROCUREMENT dispatch path, which is handed the tender's human ``project_name``. Six
    confirmations were stored under ``nd-2025-04`` and looked up under ``Contract No. ND/2025/04``,
    so the fallback fired and told the operator no mapping was confirmed while six sat in the table.

    ``tender_slug`` is the equivalence the rest of the system already runs on — ``Workspace``
    resolves a tender directory through it, which is why the doc index is reachable by either name —
    and it is idempotent on its own output, so a ``set_id`` that is already a slug is unchanged.
    """
    from bridge.identity import run_ref_for
    from pipeline.workspace import tender_slug

    return tender_slug(run_ref_for(set_id))


def load_spec_map(set_id: str) -> dict[str, ConfirmedSpec]:
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        rows = load_spec_map_on(conn, storage_key(set_id))
        if not rows:
            # Rows written before the key was canonicalised, under the raw ref. A read-side
            # fallback rather than a migration: confirming is a human act and losing one silently
            # is worse than one extra query on a table with a handful of rows per tender.
            rows = load_spec_map_on(conn, run_ref_for(set_id))
        return rows
    finally:
        conn.close()


def save_spec_map(set_id: str, confirmations: list[ConfirmedSpec] | list[dict],
                  *, confirmed_by: str = "operator") -> dict[str, ConfirmedSpec]:
    from bridge.identity import bridge_conn

    conn = bridge_conn()
    try:
        return save_spec_map_on(conn, storage_key(set_id), confirmations,
                                confirmed_by=confirmed_by)
    finally:
        conn.close()
