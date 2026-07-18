"""Decision 4A — a DEMO review must leave the committed sitesource.db byte-identical.

With no SITESOURCE_DB set, a DEMO run defaults the module's DB to a gitignored scratch file, so the
committed demo database is never written. This test removes the SITESOURCE_DB the conftest sets (to
exercise the real DEMO default) and asserts the committed DB is unchanged, and that the scratch DB
took the write instead.
"""

from __future__ import annotations

import hashlib

from client_boq.review import run as review_run
from client_boq.store import _demo_db_path
from db import store as db_store


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_demo_run_leaves_committed_db_byte_identical(monkeypatch) -> None:
    monkeypatch.delenv("SITESOURCE_DB", raising=False)  # exercise the DEMO scratch-DB default (DEMO_MODE stays on)

    committed = db_store.DEFAULT_DB_PATH
    before = _sha(committed)

    register = review_run.run_review([], "hygiene-demo")
    assert register.items  # the review really ran and produced a register

    assert _sha(committed) == before, "a DEMO run must not modify the committed sitesource.db"
    # The write landed in the gitignored scratch DB instead.
    assert _demo_db_path().is_file()
