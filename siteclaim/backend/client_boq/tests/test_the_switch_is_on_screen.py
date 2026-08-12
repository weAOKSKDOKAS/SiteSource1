"""Demo or live, decided on screen — and demo stays offline.

WHY THE FLAG IS A PROCESS VARIABLE AND NOT A ROW. `client_boq/store.py:72` chooses WHICH DATABASE
to open by calling `demo_mode()`. A flag in `client_boq_settings` would therefore be circular: you
would have to know the mode to know which database to read the mode from, and the demo DB and the
live DB would each hold their own answer. So the override lives beside `demo_mode()` in the chassis,
seeded from `DEMO_MODE`, and every one of the 61 non-test call sites reads it from inside a function
— checked — so a change reaches the next call without a restart.

IT DOES NOT SURVIVE A RESTART, on purpose. The environment is the deployment's decision and the
override is the operator's; a process that comes back returns to what it was deployed as. That is
the safe direction, and the screen says so rather than implying otherwise.

THE TWO RULES THAT DO NOT BEND, both tested here:

* demo must never spend a token or send an email — `complete_json` returns a fixture before any SDK
  is imported, and the mailer refuses;
* demo and live data must not mix — they are in different FILES, and the tender list now says which
  one it is reading, because `set_id = tender_slug(name)` means a demo tender and a live tender
  sharing a name share an id.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pipeline import llm_client

BASE = "/client-boq"


@pytest.fixture(autouse=True)
def _no_leaked_override():
    """The override is process-wide, so a test that sets it and dies would poison the suite."""
    llm_client.set_demo_mode(None)
    yield
    llm_client.set_demo_mode(None)


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestTheOverrideItself:
    def test_unset_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        assert llm_client.demo_mode() is True
        assert llm_client.demo_mode_source() == "environment"
        monkeypatch.setenv("DEMO_MODE", "false")
        assert llm_client.demo_mode() is False

    def test_the_operator_beats_the_environment_both_ways(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "false")
        assert llm_client.set_demo_mode(True) is True
        assert llm_client.demo_mode_source() == "operator"
        monkeypatch.setenv("DEMO_MODE", "true")
        assert llm_client.set_demo_mode(False) is False
        assert llm_client.demo_mode() is False, "the env must not win back mid-session"

    def test_clearing_returns_to_the_environment(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        llm_client.set_demo_mode(False)
        assert llm_client.set_demo_mode(None) is True
        assert llm_client.demo_mode_source() == "environment"

    def test_the_tri_state_is_why_clearing_is_possible(self, monkeypatch):
        """A bool could not express "the operator has not chosen", so the override could never be
        given back to the deployment."""
        monkeypatch.setenv("DEMO_MODE", "false")
        llm_client.set_demo_mode(False)
        assert llm_client.demo_mode_source() == "operator"
        llm_client.set_demo_mode(None)
        assert llm_client.demo_mode_source() == "environment"

    def test_no_call_site_reads_it_at_import(self):
        """The override only means anything if nothing cached the answer. Swept over the tree.

        Over the AST, not the text. The first version of this was a regex and its only hit was a
        `#:` comment in `llm_client.py` that happens to contain the words — a sweep that matches
        prose is a sweep that will be silenced rather than fixed.
        """
        import ast
        import pathlib

        root = pathlib.Path(llm_client.__file__).parent.parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            # Walk only the module's own top level, and do not descend into a def or a class body:
            # a call inside one runs when it is called, which is the whole point.
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for inner in ast.walk(node):
                    func = getattr(inner, "func", None)
                    name = getattr(func, "attr", None) or getattr(func, "id", None)
                    if name == "demo_mode":
                        offenders.append(f"{path.name}:{inner.lineno}")
        assert not offenders, (
            "these read the mode at import, so an operator switch would never reach them: "
            + ", ".join(offenders))

    def test_the_sweep_would_notice_one(self):
        """A sweep that matches nothing passes for the wrong reason."""
        import ast

        tree = ast.parse("import os\nFLAG = demo_mode()\n")
        found = [n for node in tree.body for n in ast.walk(node)
                 if getattr(getattr(n, "func", None), "id", None) == "demo_mode"]
        assert found, "the AST walk does not see a module-level call it is meant to catch"


class TestDemoIsOffline:
    def test_a_model_call_in_demo_never_reaches_a_provider(self, monkeypatch):
        """The rule that must not bend. `complete_json` returns the fixture BEFORE any SDK import,
        so there is no path to the network — proved by breaking every provider method."""
        llm_client.set_demo_mode(True)
        client = llm_client.LLMClient()
        for name in ("_anthropic_complete", "_openai_complete", "_deepseek_complete",
                     "_complete_text"):
            monkeypatch.setattr(
                llm_client.LLMClient, name,
                lambda *a, **k: pytest.fail("demo mode reached a provider"))

        from client_boq.models import PlannedSplit

        out = client.complete_json(
            system="s", user="u", target_model=PlannedSplit,
            demo_fixture="cases/client_boq/ingest_plan_split.json")
        assert out.parts, "the fixture should still have loaded"

    def test_switching_to_demo_at_runtime_takes_the_offline_path(self, monkeypatch):
        """Not just the env — the override has to reach the same branch, or the switch is a lie."""
        monkeypatch.setenv("DEMO_MODE", "false")
        llm_client.set_demo_mode(True)
        monkeypatch.setattr(
            llm_client.LLMClient, "_complete_text",
            lambda *a, **k: pytest.fail("the override did not reach the demo branch"))

        from client_boq.models import PlannedSplit

        assert llm_client.LLMClient().complete_json(
            system="s", user="u", target_model=PlannedSplit,
            demo_fixture="cases/client_boq/ingest_plan_split.json") is not None

    def test_the_mailer_refuses_in_demo_however_it_is_configured(self, monkeypatch):
        """Demo must never send an email, and the ONE place that decides reads the same flag.

        `_live_enabled` is `not demo_mode() and not dry_run and config.configured`, so this passes
        it the two other conditions at their most permissive — not a dry run, fully configured —
        and the mode alone still has to stop it.
        """
        from pipeline.stage_03_dispatch import mailer

        class _Configured:
            configured = True

        llm_client.set_demo_mode(True)
        assert mailer._live_enabled(dry_run=False, config=_Configured()) is False
        llm_client.set_demo_mode(False)
        assert mailer._live_enabled(dry_run=False, config=_Configured()) is True, (
            "the test would pass for the wrong reason if live were blocked too")

    def test_the_test_recipient_valve_is_forced_off_in_demo(self, monkeypatch):
        """Demo sends nothing, so a redirect notice there would be a misleading claim on a screen."""
        from pipeline.stage_03_dispatch import mailer

        monkeypatch.setenv("GMAIL_TEST_RECIPIENT", "someone@example.com")
        llm_client.set_demo_mode(True)
        assert mailer.test_recipient() == ""
        llm_client.set_demo_mode(False)
        assert mailer.test_recipient() == "someone@example.com"


class TestTheSwitchOnScreen:
    def test_the_mode_reads_back_with_where_it_came_from(self, client, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        body = client.get(f"{BASE}/mode").json()
        assert body["demo"] is True and body["source"] == "environment"
        assert body["reverts_on_restart"] is True

    def test_going_live_without_a_key_is_refused_at_the_switch(self, client, monkeypatch):
        """Not at the first model call, which is minutes into a job and looks like the tender
        failing rather than the configuration."""
        for name in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                     "CHATGPT_API_KEY", "CLAUDE_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        response = client.post(f"{BASE}/mode", json={"demo": False, "confirm": "LIVE"})
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "no key is set" in detail
        assert "API_KEY" in detail, "it must name the variable to set"
        assert ".env" in detail
        assert llm_client.demo_mode_source() == "environment", "nothing was switched"

    def test_the_unconfigured_state_says_what_to_set_before_you_try(self, client, monkeypatch):
        for name in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                     "CHATGPT_API_KEY", "CLAUDE_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        body = client.get(f"{BASE}/mode").json()
        assert body["live_ready"] is False
        assert body["providers_missing"]
        assert body["set_to_go_live"], "the screen needs the variable names, not just a refusal"

    def test_going_live_needs_the_word_typed(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        response = client.post(f"{BASE}/mode", json={"demo": False})
        assert response.status_code == 409
        assert "Type LIVE" in response.json()["detail"]
        assert llm_client.demo_mode() is not False or llm_client.demo_mode_source() == "environment"

    def test_going_live_with_a_key_and_the_word_works(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        body = client.post(f"{BASE}/mode", json={"demo": False, "confirm": "LIVE"},
                           headers={"X-CBOQ-Actor": "SW"}).json()
        assert body["demo"] is False and body["source"] == "operator"
        assert body["changed_by"] == "SW", "a switch this consequential carries a name"

    def test_going_back_to_demo_is_never_refused(self, client, monkeypatch):
        """Offline is always safe, and a switch that is hard to reach in the safe direction is a
        switch people route around."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        client.post(f"{BASE}/mode", json={"demo": False, "confirm": "LIVE"})
        body = client.post(f"{BASE}/mode", json={"demo": True}).json()
        assert body["demo"] is True and body["source"] == "operator"

    def test_clearing_the_override_is_never_refused(self, client, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        assert client.post(f"{BASE}/mode", json={"demo": None}).json()["source"] == "environment"


class TestDemoAndLiveDoNotMix:
    def test_the_tender_list_says_which_one_it_is_reading(self, client, monkeypatch):
        """`set_id = tender_slug(name)`, so a demo tender and a live tender sharing a name share an
        id in two different files. Without this the switch silently swaps which one you see."""
        monkeypatch.setenv("DEMO_MODE", "true")
        llm_client.set_demo_mode(True)
        assert client.get(f"{BASE}/sets").json()["demo"] is True
        llm_client.set_demo_mode(False)
        assert client.get(f"{BASE}/sets").json()["demo"] is False

    def test_every_row_carries_it_too(self, client, monkeypatch):
        """The shelf renders rows, not the envelope, so the flag has to be on the row."""
        llm_client.set_demo_mode(True)
        body = client.get(f"{BASE}/sets").json()
        assert all(row["demo"] is True for row in body["sets"])

    def test_the_two_modes_open_different_database_files(self, tmp_path, monkeypatch):
        """The separation itself, stated as a test rather than left as a comment.

        This is what makes "demo and live must not mix" structural rather than a filter somebody
        has to remember to apply: there is no query that could return both, because they are not
        in the same file.
        """
        monkeypatch.delenv("SITESOURCE_DB", raising=False)
        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
        from db.store import DEFAULT_DB_PATH
        from client_boq import store

        demo_path = store._demo_db_path()
        assert demo_path.name == "client_boq_demo.db"
        assert demo_path.resolve() != DEFAULT_DB_PATH.resolve(), (
            "the demo database is the committed live one — a demo run would write real data")

    def test_an_explicit_db_still_wins_over_the_mode(self, tmp_path, monkeypatch):
        """`SITESOURCE_DB` is how the tests stay hermetic, and the switch must not take that away."""
        db = tmp_path / "explicit.db"
        import sqlite3

        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("SITESOURCE_DB", str(db))
        llm_client.set_demo_mode(True)
        from client_boq import store

        conn = store.get_conn()
        try:
            got = conn.execute("PRAGMA database_list").fetchall()[0][2]
        finally:
            conn.close()
        assert str(db) in got
