"""Spec for the app-wide AI-model setting.

The chain: a setting row in the DB → ``client_boq/llm.py::make_client()`` reads it per
construction → the client carries it as an EXPLICIT constructor arg → ``LLMClient._route``
honours an explicit provider for text calls. Two truths the setting must never override:
images always route to Anthropic (DeepSeek rejects them), and procurement — which constructs
bare ``LLMClient()`` — routes from env exactly as it always has.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq import llm as llm_mod
from client_boq import store
from pipeline.llm_client import LLMClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestRouting:
    def test_an_explicit_provider_wins_for_text(self, monkeypatch):
        """The additive _route change: without it the setting would be a placebo whenever
        DEEPSEEK_API_KEY exists."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")
        assert LLMClient(provider="anthropic")._route(images=None) == "anthropic"

    def test_images_always_route_to_anthropic(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")
        assert LLMClient(provider="deepseek")._route(images=["b64"]) == "anthropic"

    def test_bare_construction_routes_from_env_as_always(self, monkeypatch):
        """Procurement's shape. The two historical behaviours, unchanged."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake")
        assert LLMClient()._route(images=None) == "deepseek"
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        assert LLMClient()._route(images=None) == "anthropic"

    def test_an_explicit_model_rides_with_its_provider(self):
        c = LLMClient(provider="anthropic", model="claude-opus-5")
        assert c._model_for("anthropic") == "claude-opus-5"


class TestMakeClient:
    def test_no_settings_means_a_bare_client(self):
        c = llm_mod.make_client()
        assert c._provider_arg is None and c._model_arg is None

    def test_a_stored_setting_reaches_the_client(self):
        conn = store.get_conn()
        try:
            store.set_setting(conn, llm_mod.SETTING_PROVIDER, "anthropic", "r-lam")
            store.set_setting(conn, llm_mod.SETTING_MODEL_ANTHROPIC, "claude-opus-5", "r-lam")
        finally:
            conn.close()
        c = llm_mod.make_client()
        assert c._provider_arg == "anthropic"
        assert c._model_arg == "claude-opus-5"

    def test_the_setting_applies_per_construction_not_per_process(self):
        """Stages construct per run, so a change takes effect on the next run — no restart."""
        before = llm_mod.make_client()
        conn = store.get_conn()
        try:
            store.set_setting(conn, llm_mod.SETTING_PROVIDER, "deepseek", "")
        finally:
            conn.close()
        after = llm_mod.make_client()
        assert before._provider_arg is None and after._provider_arg == "deepseek"


class TestRoutes:
    def test_settings_round_trip_with_authorship(self, client: TestClient):
        resp = client.post("/client-boq/settings",
                           json={"provider": "anthropic", "model_anthropic": "claude-opus-5"},
                           headers={"X-CBOQ-Actor": "r-lam"})
        assert resp.status_code == 200
        payload = client.get("/client-boq/settings").json()
        assert payload["provider"] == "anthropic"
        assert payload["effective"]["model_anthropic"] == "claude-opus-5"
        row = next(r for r in payload["rows"] if r["key"] == llm_mod.SETTING_PROVIDER)
        assert row["updated_by"] == "r-lam"

    def test_vision_is_always_anthropic_and_the_payload_says_so(self, client: TestClient):
        client.post("/client-boq/settings", json={"provider": "deepseek"})
        payload = client.get("/client-boq/settings").json()
        assert payload["effective"]["vision_provider"] == "anthropic"

    def test_a_nonsense_provider_is_refused(self, client: TestClient):
        assert client.post("/client-boq/settings",
                           json={"provider": "openai"}).status_code == 422

    def test_empty_means_auto_not_off(self, client: TestClient):
        client.post("/client-boq/settings", json={"provider": ""})
        payload = client.get("/client-boq/settings").json()
        assert payload["effective"]["text_provider"] in ("anthropic", "deepseek")
