"""One tender, one identifier.

``set_id`` (client_boq) and ``run_ref`` (procurement) are the SAME string: both sides derive it
from ``pipeline.workspace.tender_slug`` over the project name — ``client_boq/ingest/run.py:70``
(``set_id = tender_slug(name)``) and ``api.py:2092``
(``run_ref = req.run_ref.strip() or tender_slug(req.scope.project_name)``). So there is no
translation layer here, and there must never be one: a mapping table would be a second source of
truth for a thing that is already a pure function of the name, and the two copies would drift the
first time a tender was renamed.

``unified_projects`` (``db/project.py``) is the umbrella for both halves. It lives on THIS side —
nothing is added to any ``client_boq_*`` table.
"""

from __future__ import annotations

import sqlite3

from pipeline.llm_client import demo_mode


def bridge_conn() -> sqlite3.Connection:
    """The connection every bridge module uses — deliberately ``client_boq.store.get_conn()``.

    The bridge joins against client_boq's data, so it must open the database that data is in. In
    DEMO with no ``SITESOURCE_DB`` set, ``get_conn`` opens a gitignored scratch DB (client_boq's
    decision 4A), which is also exactly what keeps the committed ``sitesource.db`` byte-identical
    when the bridge writes its own tables — the trap 3b failure mode. Live, and under a test's
    ``SITESOURCE_DB``, it is the same shared database procurement uses, so ``unified_projects``
    and ``package_routes`` are the rows procurement already knows about.

    A read-only import: this calls client_boq, it never modifies it.
    """
    from client_boq import store as cb_store

    return cb_store.get_conn()


def run_ref_for(set_id: str) -> str:
    """The procurement ``run_ref`` for a client_boq ``set_id`` — the identity function.

    They are the same string by construction (see the module docstring), so this returns it
    unchanged. It exists so that every call site states the equivalence explicitly rather than
    passing a ``set_id`` into a ``run_ref`` parameter and leaving a reader to wonder, and so the
    one place that would ever need to change is findable.
    """
    ref = (set_id or "").strip()
    if not ref:
        raise ValueError("A tender needs a set_id — it is the run_ref on the procurement side.")
    return ref


def tender_ref(name_or_id: str) -> str:
    """THE canonical id for a tender's artifacts, from whatever a caller happens to hold.

    ONE IDENTITY, RESOLVED THE SAME WAY BY EVERY CALLER. The bridge owns a tender and addresses it
    by ``set_id``; the procurement endpoints are handed a ``ScopePackages`` and address it by
    ``project_name``. Those are different strings, and ``tender_slug`` does not reconcile them —
    it maps ``nd-2025-04-san-tin-technopole`` to itself and ``Contract No. ND/2025/04`` to
    ``nd-2025-04``. So the bridge wrote a 168-document index into one workspace while dispatch read
    a stale 570-byte one out of another, and the gate reported "no Schedule of Rates PDF is indexed
    for this tender" — an honest sentence about the wrong directory.

    ``unified_projects`` already holds the mapping: the bridge registers ``(run_ref, name)`` the
    first time it touches a set (:func:`register_set`), and ``run_ref`` IS the ``set_id``. So this
    is an EXACT lookup, never a fuzzy match:

    * the string is already a ``run_ref``     -> itself, unchanged;
    * the string is a registered ``name``     -> that row's ``run_ref``;
    * neither (a pure procurement run, or a tender the bridge never registered) -> itself, which is
      exactly today's behaviour and keeps the non-bridge path byte-for-byte as it was.

    Never guesses, and never invents an id: an unregistered tender addresses its own workspace under
    its own name, as it always did.
    """
    ref = (name_or_id or "").strip()
    if not ref:
        return ref
    try:
        conn = bridge_conn()
    except Exception:  # noqa: BLE001 — no database is not a reason to fail a dispatch preview
        return ref
    try:
        from db import project as uproject

        if not uproject.has_unified_table(conn):
            return ref
        if uproject.get(conn, ref) is not None:
            return ref                       # already the canonical id
        row = conn.execute(
            "SELECT run_ref FROM unified_projects WHERE name = ? ORDER BY id LIMIT 1", (ref,)
        ).fetchone()
        return row["run_ref"] if row and row["run_ref"] else ref
    except Exception:  # noqa: BLE001 — a lookup failure degrades to the caller's own string
        return ref
    finally:
        conn.close()


def set_name(conn: sqlite3.Connection, set_id: str) -> str:
    """The tender's human name from its client_boq set row, or "" when the set is unknown."""
    from client_boq import store as cb_store

    row = cb_store.load_set(conn, run_ref_for(set_id))
    return (row or {}).get("name", "") or ""


def register_set(set_id: str, name: str = "") -> dict:
    """Register (or fetch) this tender's ``unified_projects`` umbrella row and return it.

    Called the first time the bridge touches a set. Idempotent by ``get_or_create``: the second
    call returns the same row rather than creating a second one, and backfills the name if the
    row was first created without one.
    """
    run_ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        return register_set_on(conn, run_ref, name=name)
    finally:
        conn.close()


def register_set_on(conn: sqlite3.Connection, set_id: str, name: str = "") -> dict:
    """``register_set`` against a caller-owned connection — so an endpoint that already has one
    open registers inside the same transaction scope instead of opening a second."""
    from db import project as uproject

    run_ref = run_ref_for(set_id)
    return uproject.get_or_create(
        conn, run_ref,
        name=(name or set_name(conn, run_ref)),
        provenance=("demo" if demo_mode() else "live"),
    )
