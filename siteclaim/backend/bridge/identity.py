"""One tender, one identifier.

``set_id`` (client_boq) and ``run_ref`` (procurement) are the SAME string: both sides derive it
from ``pipeline.workspace.tender_slug`` over the project name — ``client_boq/ingest/run.py:70``
(``set_id = tender_slug(name)``) and ``api.py:2092``
(``run_ref = req.run_ref.strip() or tender_slug(req.scope.project_name)``). So there is no
translation layer here, and there must never be one: a mapping table would be a second source of
truth for a thing that is already a pure function of the name.

``unified_projects`` (``db/project.py``) is the umbrella for both halves. It lives on THIS side —
nothing is added to any ``client_boq_*`` table.
"""

from __future__ import annotations


def run_ref_for(set_id: str) -> str:
    """The procurement ``run_ref`` for a client_boq ``set_id`` — the identity function, validated.

    Will normalise/verify the id and return it unchanged (they are the same string by
    construction), raising on an empty id rather than inventing one.
    """
    raise NotImplementedError(
        "run_ref_for: return the run_ref for a set_id (identical string), rejecting an empty id"
    )


def register_set(set_id: str, name: str = "") -> dict:
    """Register this tender's umbrella row in ``unified_projects`` and return it.

    Will call ``db.project.get_or_create(conn, run_ref=set_id, name=..., provenance=...)`` — the
    first time the bridge touches a set. Idempotent: registering twice yields one row.
    """
    raise NotImplementedError(
        "register_set: get_or_create the unified_projects umbrella row keyed by run_ref == set_id"
    )
