"""The name the DOCUMENTS give a tender must resolve to the tender.

THE DEFECT. `register_set_on` records the names known at the START of a split — the set_id and the
set row's display name, which on the archive path is the ZIP filename's stem. The tender's real
title arrives later: `ingest_tender` asks the model for a `project_name`, and `_merge_scopes`
prefers the model's answer over the registered one (`ingest.py:1203-1233`). So on any PDF-bill
tender the persisted split carries the title as printed in the documents — "Ground Investigation
Works for Development of…" — and that string is registered nowhere.

WHAT IT COSTS. The desk dispatches under exactly that string (`Sourcing.tsx:273`, `:300` — it is
the reference on the plan, the compose AND the send). `resolve_ref` misses on all three of its
exact-equality chances and `tender_ref` quietly falls back to the name itself
(`identity.py:78`). `Workspace.tender_dir` then mints a fresh directory from the unresolved
string, the document index there is empty, and `relevant_docs` substitutes a GENERATED pricing
sheet for the client's own sliced bill. The plan and the drafts flag the substitution; the
confirm-and-send path computes no plan at all and does not.

Registered as an alias at the one funnel every split is persisted through, the whole chain resolves
and the real bill is attached.
"""

from __future__ import annotations

import sqlite3

import pytest
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

# The two names a real tender has. The first is what the archive upload knew; the second is what
# the documents themselves say, and it is the one the frontend sends back.
ZIP_STEM = "OneDrive_2026-07-21"
SET_ID = "onedrive-2026-07-21"
TITLE_IN_THE_DOCUMENTS = (
    "Ground Investigation Works for Development of Columbarium and Related Facilities")


@pytest.fixture
def conn(tmp_path, monkeypatch) -> sqlite3.Connection:
    monkeypatch.setenv("DEMO_MODE", "true")
    db = tmp_path / "bridge.db"
    sqlite3.connect(str(db)).close()
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _scope(name: str) -> ScopePackages:
    return ScopePackages(project_name=name, packages=[
        TradeWorkPackage(trade="ground_investigation", scope_summary="GI", sor_items=[
            SorItem(item_ref="2.2", description="Rotary drilling in soil", unit="m", section="2"),
        ]),
    ])


class TestTheTitleTheDocumentsGaveIt:

    def test_it_resolves_to_the_tender_after_the_split_is_saved(self, conn):
        from bridge import scope as scope_mod
        from bridge.identity import register_set_on
        from db import project as uproject

        register_set_on(conn, SET_ID, name=ZIP_STEM)
        assert uproject.resolve_ref(conn, TITLE_IN_THE_DOCUMENTS) is None, (
            "the defect: the title the documents state is registered nowhere")

        scope_mod.save_scope_on(conn, SET_ID, _scope(TITLE_IN_THE_DOCUMENTS))
        assert uproject.resolve_ref(conn, TITLE_IN_THE_DOCUMENTS) == SET_ID

    def test_the_names_that_already_worked_still_do(self, conn):
        from bridge import scope as scope_mod
        from bridge.identity import register_set_on
        from db import project as uproject

        register_set_on(conn, SET_ID, name=ZIP_STEM)
        scope_mod.save_scope_on(conn, SET_ID, _scope(TITLE_IN_THE_DOCUMENTS))
        for name in (SET_ID, ZIP_STEM, TITLE_IN_THE_DOCUMENTS):
            assert uproject.resolve_ref(conn, name) == SET_ID

    def test_a_split_saved_twice_is_idempotent(self, conn):
        from bridge import scope as scope_mod
        from bridge.identity import register_set_on
        from db import project as uproject

        register_set_on(conn, SET_ID, name=ZIP_STEM)
        for _ in range(3):
            scope_mod.save_scope_on(conn, SET_ID, _scope(TITLE_IN_THE_DOCUMENTS))
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM unified_project_aliases WHERE alias = ?",
            (TITLE_IN_THE_DOCUMENTS,)).fetchone()
        assert rows["n"] == 1
        assert uproject.resolve_ref(conn, TITLE_IN_THE_DOCUMENTS) == SET_ID

    def test_a_re_split_under_a_better_title_registers_that_one_too(self, conn):
        """A second reading of the same binder may report the title differently. Both names must
        keep working — the first one is what an in-flight dispatch is already holding."""
        from bridge import scope as scope_mod
        from bridge.identity import register_set_on
        from db import project as uproject

        register_set_on(conn, SET_ID, name=ZIP_STEM)
        scope_mod.save_scope_on(conn, SET_ID, _scope(TITLE_IN_THE_DOCUMENTS))
        better = "Contract No. ND/2025/04 — Ground Investigation Works"
        scope_mod.save_scope_on(conn, SET_ID, _scope(better))
        assert uproject.resolve_ref(conn, TITLE_IN_THE_DOCUMENTS) == SET_ID
        assert uproject.resolve_ref(conn, better) == SET_ID


class TestItNeverCrossesTwoTenders:

    def test_a_title_already_owned_by_another_tender_is_left_alone(self, conn):
        """`register_aliases` reports by omission rather than re-pointing. Two tenders sharing a
        title is a fact for a person to resolve; moving one tender's artifacts under another is
        not a repair."""
        from bridge import scope as scope_mod
        from bridge.identity import register_set_on
        from db import project as uproject

        register_set_on(conn, "first-tender", name="First")
        uproject.register_aliases(conn, "first-tender", TITLE_IN_THE_DOCUMENTS)
        register_set_on(conn, SET_ID, name=ZIP_STEM)

        scope_mod.save_scope_on(conn, SET_ID, _scope(TITLE_IN_THE_DOCUMENTS))
        assert uproject.resolve_ref(conn, TITLE_IN_THE_DOCUMENTS) == "first-tender"
        assert uproject.resolve_ref(conn, SET_ID) == SET_ID

    def test_an_empty_project_name_registers_nothing(self, conn):
        from bridge import scope as scope_mod
        from bridge.identity import register_set_on

        register_set_on(conn, SET_ID, name=ZIP_STEM)
        before = conn.execute("SELECT COUNT(*) AS n FROM unified_project_aliases").fetchone()["n"]
        scope_mod.save_scope_on(conn, SET_ID, _scope("   "))
        after = conn.execute("SELECT COUNT(*) AS n FROM unified_project_aliases").fetchone()["n"]
        assert after == before

    def test_the_split_is_still_saved_and_readable(self, conn):
        """The registry is a side effect. If it ever fails, the split must not."""
        from bridge import scope as scope_mod

        scope_mod.save_scope_on(conn, SET_ID, _scope(TITLE_IN_THE_DOCUMENTS))
        back = scope_mod.load_scope_on(conn, SET_ID)
        assert back is not None and back.project_name == TITLE_IN_THE_DOCUMENTS
        assert back.packages[0].sor_items[0].item_ref == "2.2"


class TestTheWorkspaceFollows:
    """The consequence the alias exists for: the dispatch reads the directory the split wrote."""

    def test_the_title_addresses_the_same_workspace_directory_as_the_set_id(self, conn, tmp_path,
                                                                           monkeypatch):
        from bridge import scope as scope_mod
        from bridge.identity import register_set_on
        from pipeline.workspace import Workspace

        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
        register_set_on(conn, SET_ID, name=ZIP_STEM)
        scope_mod.save_scope_on(conn, SET_ID, _scope(TITLE_IN_THE_DOCUMENTS))

        ws = Workspace()
        assert ws.resolve_ref(TITLE_IN_THE_DOCUMENTS) == SET_ID
        assert ws.tender_dir(TITLE_IN_THE_DOCUMENTS) == ws.tender_dir(SET_ID)
