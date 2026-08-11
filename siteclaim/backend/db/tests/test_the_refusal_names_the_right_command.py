"""A refusal that tells you to run a command must tell you the command that works.

THE DEFECT. `get_connection` used to answer every missing database with the same sentence —
"Build it with `python -m db.seed`" — and that command is wrong in the case an operator most often
hits. `db.seed` defaults to `--profile demo` (`seed.py:316`), which writes `sitesource.db`, never
the `sitesource_live.db` the environment variable points at. And it UNLINKS the target first
(`seed.py:169-170`).

So an operator who set `SITESOURCE_DB=db/sitesource_live.db` on a fresh clone and followed the
app's own instruction got two things: the identical error on the next start, and a
deleted-and-rebuilt copy of a file that is COMMITTED to this repository. That is CLAUDE.md trap 2,
reached by doing exactly what the software said.

Every other place that documents the seed already says `--profile live` — `siteclaim/CLAUDE.md`,
`BUILD_PLAN.md`, `.env.example`. This was the single wrong copy, and the reason it stayed wrong is
that no test read the sentence.
"""

from __future__ import annotations

import pytest

from db import seed as db_seed
from db.store import _how_to_build, get_connection


def _message(path, monkeypatch, env: str = "") -> str:
    """The sentence for `path`.

    Written against the message builder rather than `get_connection`, because one of the three
    branches is the COMMITTED `sitesource.db` — which is present in every checkout, so the only
    way to reach its message through the connection would be to move the tracked file aside.
    `TestItStillDoesTheOrdinaryThing` covers the wiring.
    """
    if env:
        monkeypatch.setenv("SITESOURCE_DB", env)
    else:
        monkeypatch.delenv("SITESOURCE_DB", raising=False)
    return _how_to_build(path)


class TestItNamesTheCommandThatBuildsTheFileThatIsMissing:

    def test_the_live_database_asks_for_the_live_profile(self, monkeypatch):
        message = _message(db_seed.LIVE_DB_PATH, monkeypatch, env="db/sitesource_live.db")
        assert "--profile live" in message
        assert "--profile demo" not in message.split("Note:")[0], (
            "the demo profile must not be offered as the way to build the live database")

    def test_the_committed_demo_database_is_restored_rather_than_rebuilt(self, monkeypatch):
        """`sitesource.db` is tracked. Rebuilding it makes the working copy stop being the file
        that shipped even when the data comes back — so the checkout is named first."""
        message = _message(db_seed.DEFAULT_DB_PATH, monkeypatch)
        assert "git checkout --" in message
        assert "COMMITTED" in message

    def test_any_other_path_needs_out_because_no_profile_default_produces_it(self, tmp_path,
                                                                            monkeypatch):
        target = tmp_path / "somewhere" / "custom.db"
        message = _message(target, monkeypatch, env=str(target))
        assert "--out" in message and str(target) in message
        assert "parent directory must" in message, (
            "build_database connects directly and does not create parents")


class TestItSaysTheThingsThatCostARebuild:

    def test_it_warns_that_the_bare_command_deletes(self, monkeypatch):
        message = _message(db_seed.LIVE_DB_PATH, monkeypatch, env="db/sitesource_live.db")
        assert "DELETES" in message

    def test_it_says_the_bare_command_builds_the_demo_database(self, monkeypatch):
        message = _message(db_seed.LIVE_DB_PATH, monkeypatch, env="db/sitesource_live.db")
        assert "no --profile builds the DEMO database" in message
        assert str(db_seed.DEFAULT_DB_PATH) in message

    def test_it_names_the_working_directory_the_module_path_assumes(self, monkeypatch):
        """`python -m db.seed` resolves only from `siteclaim/backend/`; from `siteclaim/` the
        module path is `backend.db.seed`. The old message stated neither."""
        message = _message(db_seed.LIVE_DB_PATH, monkeypatch, env="db/sitesource_live.db")
        assert "from siteclaim/backend/" in message

    def test_it_reports_the_env_var_that_chose_the_path(self, monkeypatch):
        """The path in the message is often relative, and the reason it is relative is the env
        var. Printing one without the other leaves the operator guessing which is in force."""
        message = _message(db_seed.LIVE_DB_PATH, monkeypatch, env="db/sitesource_live.db")
        assert "SITESOURCE_DB=db/sitesource_live.db" in message

    def test_an_unset_env_var_says_so_rather_than_printing_nothing(self, monkeypatch):
        message = _message(db_seed.DEFAULT_DB_PATH, monkeypatch)
        assert "SITESOURCE_DB=<unset>" in message


class TestItStillDoesTheOrdinaryThing:

    def test_the_path_that_is_missing_is_still_the_first_thing_said(self, monkeypatch):
        message = _message(db_seed.LIVE_DB_PATH, monkeypatch, env="db/sitesource_live.db")
        assert message.startswith("SiteSource DB not found at ")
        assert str(db_seed.LIVE_DB_PATH) in message

    def test_get_connection_raises_with_exactly_this_message(self, tmp_path, monkeypatch):
        """The wiring, so the sentence cannot drift away from the refusal that prints it."""
        missing = tmp_path / "not-there.db"
        monkeypatch.setenv("SITESOURCE_DB", str(missing))
        with pytest.raises(FileNotFoundError) as caught:
            get_connection(missing)
        assert str(caught.value) == _how_to_build(missing)
        assert "--out" in str(caught.value)

    def test_a_database_that_exists_opens_normally(self, tmp_path, monkeypatch):
        import sqlite3

        db = tmp_path / "present.db"
        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("SITESOURCE_DB", str(db))
        conn = get_connection(db)
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()
