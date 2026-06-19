"""Spec for the LLM client wrapper — DEMO_MODE is offline, fences are stripped."""

import pytest

from pipeline.llm_client import LLMClient, demo_mode, strip_code_fences
from schemas.models import ExtractedFacts


def _boom(*args, **kwargs):
    raise AssertionError("the live/network path must not be reached in DEMO_MODE")


def test_strip_code_fences_passes_plain_json_through():
    assert strip_code_fences('{"x": 1}') == '{"x": 1}'


def test_strip_code_fences_removes_json_fence():
    assert strip_code_fences('```json\n{"x": 1}\n```') == '{"x": 1}'


def test_strip_code_fences_removes_bare_fence():
    assert strip_code_fences('```\n{"x": 1}\n```') == '{"x": 1}'


def test_demo_mode_reads_env_dynamically(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    assert demo_mode() is True
    monkeypatch.setenv("DEMO_MODE", "0")
    assert demo_mode() is False


def test_demo_mode_loads_fixture_without_any_live_call(monkeypatch):
    client = LLMClient()
    # If DEMO_MODE leaks to the network/SDK path, these blow up:
    monkeypatch.setattr(client, "_live_complete_json", _boom)
    monkeypatch.setattr(client, "_anthropic", _boom)
    facts = client.complete_json(
        system="ignored",
        user="ignored",
        target_model=ExtractedFacts,
        demo_fixture="cases/clean/extracted.json",
    )
    assert facts.claimed_amount.value is not None


def test_demo_mode_requires_a_fixture(monkeypatch):
    client = LLMClient()
    with pytest.raises(RuntimeError):
        client.complete_json(
            system="s", user="u", target_model=ExtractedFacts, demo_fixture=None
        )
