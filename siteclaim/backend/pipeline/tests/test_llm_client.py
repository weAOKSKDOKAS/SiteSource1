"""Spec for the LLM client wrapper — DEMO_MODE is offline, fences are stripped."""

import pytest

from pydantic import BaseModel

from pipeline import llm_client
from pipeline.llm_client import LLMClient, demo_mode, strip_code_fences
from schemas.models import ScopePackages


class _Ok(BaseModel):
    ok: bool


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
    # If DEMO_MODE leaks to the network/SDK path, this blows up:
    monkeypatch.setattr(client, "_complete_text", _boom)
    scope = client.complete_json(
        system="ignored",
        user="ignored",
        target_model=ScopePackages,
        demo_fixture="_llm_probe.json",
    )
    assert scope.project_name == "Probe"


def test_demo_mode_requires_a_fixture(monkeypatch):
    client = LLMClient()
    with pytest.raises(RuntimeError):
        client.complete_json(
            system="s", user="u", target_model=ScopePackages, demo_fixture=None
        )


# -- per-call logging (P3-H): one line per LIVE call; DEMO logs nothing ----------------
import json  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402


def _fake_anthropic(text: str, *, input_tokens=1234, output_tokens=56):
    """A stand-in anthropic SDK module: a client that returns text + usage, no socket."""
    module = types.SimpleNamespace()

    class _Err(Exception):
        pass

    module.RateLimitError = module.APIConnectionError = _Err
    module.APITimeoutError = module.InternalServerError = _Err
    resp = types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text=text)],
        usage=types.SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = types.SimpleNamespace(create=lambda **kw: resp)

    module.Anthropic = _Anthropic
    return module


def test_a_live_call_logs_one_line_with_purpose_and_tokens(monkeypatch, capsys, tmp_path):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic('{"ok": true}'))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SITESOURCE_LLM_LOG", str(tmp_path / "llm.jsonl"))

    client = LLMClient(provider="anthropic")
    out = client._complete_text(system="s", user="u", images=["x"], max_tokens=100, purpose="ingest-chunk")

    assert out == '{"ok": true}'
    line = capsys.readouterr().out
    assert "[llm]" in line and "provider=anthropic" in line
    assert "purpose=ingest-chunk" in line and "in=1234 out=56" in line
    # JSONL sidecar written when SITESOURCE_LLM_LOG names a file
    rec = json.loads((tmp_path / "llm.jsonl").read_text(encoding="utf-8").strip())
    assert rec["purpose"] == "ingest-chunk" and rec["in"] == 1234 and rec["out"] == 56 and rec["ms"] >= 0


def test_demo_mode_makes_no_llm_log(monkeypatch, capsys):
    monkeypatch.setenv("DEMO_MODE", "true")
    LLMClient().complete_json(
        system="s", user="u", target_model=ScopePackages,
        demo_fixture="_llm_probe.json", purpose="ingest-chunk",
    )
    assert "[llm]" not in capsys.readouterr().out  # a fixture read never logs a call


def test_log_call_omits_tokens_when_unavailable(capsys):
    LLMClient()._log_call("deepseek", "deepseek-v4-pro", "classify", 12.0, {})
    line = capsys.readouterr().out
    assert "provider=deepseek" in line and "purpose=classify" in line
    assert "in=" not in line  # no token usage reported -> the fields are simply absent


# ---------------------------------------------------------------------------
# Reasoning models — a completion budget must still leave room for an ANSWER
# ---------------------------------------------------------------------------
def _fake_openai(content: str, *, finish_reason="stop", reasoning="", completion_tokens=100,
                 seen: dict | None = None):
    """A stand-in openai SDK module. Records the max_tokens it was called with, so a test can
    assert the reasoning headroom is actually applied."""
    module = types.SimpleNamespace()

    class _Err(Exception):
        pass

    module.RateLimitError = module.APIConnectionError = _Err
    module.APITimeoutError = module.InternalServerError = _Err

    message = types.SimpleNamespace(content=content, reasoning_content=reasoning)
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    resp = types.SimpleNamespace(
        choices=[choice],
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=completion_tokens),
    )

    def create(**kw):
        if seen is not None:
            seen.update(kw)
        return resp

    class _OpenAI:
        def __init__(self, *a, **k):
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))

    module.OpenAI = _OpenAI
    return module


def test_a_reasoning_model_that_never_answers_is_a_loud_config_error(monkeypatch):
    """MEASURED 2026-08-01: deepseek-v4-flash spends completion tokens on `reasoning_content`, so a
    hard prompt at max_tokens=8000 returned finish_reason='length' with content=''. That empty
    string reached the caller as 'Invalid JSON: EOF while parsing' — a true statement about a
    string that was never the problem, and `complete_json`'s corrective retry then re-sent the same
    budget and failed identically.

    It must name its own cause instead."""
    monkeypatch.setitem(sys.modules, "openai",
                        _fake_openai("", finish_reason="length", reasoning="x" * 2175))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    client = llm_client.LLMClient(provider="deepseek")
    with pytest.raises(llm_client.CompletionTruncated) as exc:
        client.complete_json(system="s", user="u", target_model=_Ok)
    message = str(exc.value)
    assert "reasoning" in message.lower()
    assert "DEEPSEEK_MIN_MAX_TOKENS" in message  # tells the operator how to fix it


def test_the_deepseek_path_raises_the_completion_budget_for_reasoning(monkeypatch):
    """The floor is what makes `max_tokens` mean the same thing on both providers — on a reasoning
    model the budget must cover the thinking AND the answer."""
    seen: dict = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai('{"ok": true}', seen=seen))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    client = llm_client.LLMClient(provider="deepseek")
    client.complete_json(system="s", user="u", target_model=_Ok,
                         max_tokens=llm_client.DEFAULT_MAX_TOKENS)
    assert seen["max_tokens"] == llm_client.DEEPSEEK_MIN_MAX_TOKENS


def test_an_explicit_larger_budget_is_never_lowered(monkeypatch):
    seen: dict = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai('{"ok": true}', seen=seen))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    client = llm_client.LLMClient(provider="deepseek")
    client.complete_json(system="s", user="u", target_model=_Ok, max_tokens=99_000)
    assert seen["max_tokens"] == 99_000


def test_a_truncated_answer_that_DID_produce_content_is_left_alone(monkeypatch):
    """Only the empty case is a config fault. Partial content is a parsing problem, and the
    existing corrective retry is the right handler for it — don't widen the new error."""
    monkeypatch.setitem(sys.modules, "openai",
                        _fake_openai('{"ok": true}', finish_reason="length"))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    client = llm_client.LLMClient(provider="deepseek")
    assert client.complete_json(system="s", user="u", target_model=_Ok).ok is True
