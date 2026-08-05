"""OpenAI as a third provider — and the two footguns that came with adding one.

The rule these defend: **an unrecognised provider must fail loudly, and a borrowed code path must not
bring its lender's assumptions with it.**

Before this, `_default_model` and `_model_for` were `if anthropic … else deepseek` with no `elif`, so
any third provider name silently priced with the DeepSeek model. And `_deepseek_complete` applies a
32,000-token floor that exists for DeepSeek's reasoning budget — reusing it for OpenAI by swapping a
`base_url`, which is the obvious shortcut, would have sent that floor on every call for a reason that
has nothing to do with OpenAI.

The third thing here is defensive rather than corrective: some OpenAI models reject `max_tokens` and
require `max_completion_tokens`. Which one a given model wants is discovered on the first call, so a
wrong guess costs one retry instead of failing every ingest on a parameter name.

Everything is offline — the SDK is a stand-in module, no socket is opened, no key is read.
"""

from __future__ import annotations

import sys
import types

import pytest
from pydantic import BaseModel

from pipeline import llm_client
from pipeline.llm_client import LLMClient

_B64 = "aGVsbG8="


class _Ok(BaseModel):
    ok: bool


def _fake_openai(content: str = '{"ok": true}', *, rejects: str = "", finish_reason="stop",
                 seen: list | None = None):
    """A stand-in openai SDK module.

    ``rejects`` names a token parameter the fake model refuses, so the discovery path can be
    exercised: a call carrying it raises ``BadRequestError`` naming the other one, exactly as the
    real API does.
    """
    module = types.SimpleNamespace()

    class _Err(Exception):
        pass

    class _BadRequest(Exception):
        pass

    module.RateLimitError = module.APIConnectionError = _Err
    module.APITimeoutError = module.InternalServerError = _Err
    module.BadRequestError = _BadRequest

    message = types.SimpleNamespace(content=content, reasoning_content="")
    choice = types.SimpleNamespace(message=message, finish_reason=finish_reason)
    resp = types.SimpleNamespace(
        choices=[choice],
        usage=types.SimpleNamespace(prompt_tokens=11, completion_tokens=22),
    )

    def create(**kw):
        if seen is not None:
            seen.append(kw)
        if rejects and rejects in kw:
            other = "max_completion_tokens" if rejects == "max_tokens" else "max_tokens"
            raise _BadRequest(
                f"Unsupported parameter: '{rejects}' is not supported with this model. "
                f"Use '{other}' instead.")
        return resp

    class _OpenAI:
        def __init__(self, *a, **k):
            self.kwargs = k
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=create))

    module.OpenAI = _OpenAI
    return module


@pytest.fixture(autouse=True)
def _reset_token_param(monkeypatch):
    # The discovered parameter is process-global on purpose; a test must not inherit another's.
    monkeypatch.setattr(llm_client, "_OPENAI_TOKEN_PARAM", "max_tokens", raising=False)


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


class TestOpenAIIsSelectable:
    def test_it_is_one_of_the_providers(self):
        assert "openai" in llm_client.PROVIDERS

    def test_it_gets_its_own_model_not_deepseeks(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        client = LLMClient(provider="openai")
        assert client.model == llm_client.DEFAULT_OPENAI_MODEL
        assert client.model != "deepseek-v4-flash"

    def test_the_model_reads_its_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
        assert LLMClient(provider="openai").model == "gpt-5.6-luna"

    def test_chatgpt_model_works_as_an_alias(self, monkeypatch):
        # People who think of it as "the ChatGPT key" write CHATGPT_* in their .env.
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.setenv("CHATGPT_MODEL", "gpt-5.6-luna")
        assert LLMClient(provider="openai").model == "gpt-5.6-luna"

    def test_the_canonical_name_wins_over_the_alias(self, monkeypatch):
        monkeypatch.setenv("OPENAI_MODEL", "canonical")
        monkeypatch.setenv("CHATGPT_MODEL", "alias")
        assert LLMClient(provider="openai").model == "canonical"

    def test_chatgpt_api_key_works_as_an_alias(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("CHATGPT_API_KEY", "sk-alias")
        assert llm_client.provider_key("openai") == "sk-alias"


class TestAnUnknownProviderFailsLoudly:
    """The footgun this replaced: `else: return deepseek` priced tenders with a model nobody chose."""

    def test_a_typo_raises_rather_than_becoming_deepseek(self):
        with pytest.raises(ValueError, match="not a provider this client knows"):
            LLMClient(provider="opneai")

    def test_the_error_names_the_providers_that_do_exist(self):
        with pytest.raises(ValueError) as raised:
            llm_client.model_for_provider("gpt")
        assert "anthropic" in str(raised.value) and "openai" in str(raised.value)


class TestImagesGoToWhoeverCanReadThem:
    def test_openai_keeps_its_pages(self):
        assert LLMClient(provider="openai")._route([_B64]) == "openai"

    def test_deepseek_still_cannot_have_them(self):
        # A fact about DeepSeek's API, not a rule about Anthropic. Unchanged.
        assert LLMClient(provider="deepseek")._route([_B64]) == "anthropic"

    def test_a_bare_client_is_untouched(self, monkeypatch):
        # Every procurement call site constructs bare. This must not move.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        assert LLMClient()._route([_B64]) == "anthropic"

    def test_vision_capability_is_data_not_a_branch(self):
        assert "deepseek" not in llm_client.VISION_CAPABLE
        assert {"anthropic", "openai"} <= llm_client.VISION_CAPABLE


class TestItDoesNotInheritDeepseeksAssumptions:
    def test_no_thirty_two_thousand_token_floor(self, live, monkeypatch):
        seen: list = []
        monkeypatch.setitem(sys.modules, "openai", _fake_openai(seen=seen))
        LLMClient(provider="openai").complete_json(
            system="s", user="u", target_model=_Ok, max_tokens=llm_client.DEFAULT_MAX_TOKENS)
        assert seen[0]["max_tokens"] == llm_client.DEFAULT_MAX_TOKENS
        assert seen[0]["max_tokens"] != llm_client.DEEPSEEK_MIN_MAX_TOKENS

    def test_it_talks_to_openai_and_not_to_deepseeks_base_url(self, live, monkeypatch):
        monkeypatch.setitem(sys.modules, "openai", _fake_openai())
        client = LLMClient(provider="openai")
        client.complete_json(system="s", user="u", target_model=_Ok)
        assert "base_url" not in client._clients["openai"].kwargs

    def test_the_call_is_logged_under_its_own_provider(self, live, monkeypatch, capsys):
        monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
        monkeypatch.setitem(sys.modules, "openai", _fake_openai())
        LLMClient(provider="openai").complete_json(
            system="s", user="u", target_model=_Ok, purpose="client_boq-ingest-interpret")
        line = capsys.readouterr().out
        assert "provider=openai" in line and "model=gpt-5.6-luna" in line
        assert "purpose=client_boq-ingest-interpret" in line

    def test_an_answerless_budget_is_still_a_loud_config_error(self, live, monkeypatch):
        monkeypatch.setitem(sys.modules, "openai", _fake_openai("", finish_reason="length"))
        with pytest.raises(llm_client.CompletionTruncated) as raised:
            LLMClient(provider="openai").complete_json(system="s", user="u", target_model=_Ok)
        # It must name OpenAI's own lever, not DeepSeek's.
        assert "OPENAI_MODEL" in str(raised.value)
        assert "DEEPSEEK_MIN_MAX_TOKENS" not in str(raised.value)


class TestTheTokenParameterIsDiscovered:
    """Some OpenAI models reject `max_tokens`. Guessing wrong must cost one retry, not every call."""

    def test_it_retries_with_max_completion_tokens_when_told_to(self, live, monkeypatch):
        seen: list = []
        monkeypatch.setitem(sys.modules, "openai",
                            _fake_openai(rejects="max_tokens", seen=seen))
        LLMClient(provider="openai").complete_json(system="s", user="u", target_model=_Ok)
        assert "max_tokens" in seen[0], "it tries the common spelling first"
        assert "max_completion_tokens" in seen[1], "and switches when the model says so"

    def test_it_remembers_so_the_next_call_costs_nothing(self, live, monkeypatch):
        seen: list = []
        monkeypatch.setitem(sys.modules, "openai",
                            _fake_openai(rejects="max_tokens", seen=seen))
        client = LLMClient(provider="openai")
        client.complete_json(system="s", user="u", target_model=_Ok)
        before = len(seen)
        client.complete_json(system="s", user="u", target_model=_Ok)
        assert len(seen) == before + 1, "the second call must not repeat the rejected attempt"
        assert "max_completion_tokens" in seen[-1]

    def test_any_other_bad_request_is_surfaced_rather_than_swallowed(self, live, monkeypatch):
        module = _fake_openai()

        def create(**kw):
            raise module.BadRequestError("model 'gpt-nope' does not exist")

        module.OpenAI = lambda *a, **k: types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        monkeypatch.setitem(sys.modules, "openai", module)
        with pytest.raises(module.BadRequestError, match="does not exist"):
            LLMClient(provider="openai").complete_json(system="s", user="u", target_model=_Ok)


class TestConfiguration:
    def test_a_missing_key_says_which_env_vars_to_set(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "false")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CHATGPT_API_KEY", raising=False)
        monkeypatch.setitem(sys.modules, "openai", _fake_openai())
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            LLMClient(provider="openai").complete_json(system="s", user="u", target_model=_Ok)

    def test_an_unset_extraction_provider_is_empty_not_a_default(self, monkeypatch):
        # The distinction that keeps ingest on the cheap text provider for anybody who never
        # expressed an opinion: "not configured" must not become an explicit choice.
        monkeypatch.delenv("EXTRACTION_PROVIDER", raising=False)
        assert llm_client.configured_extraction_provider() == ""
        assert llm_client.extraction_provider() == "anthropic"

    def test_demo_mode_still_needs_no_sdk_at_all(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setenv("EXTRACTION_PROVIDER", "openai")
        for module in ("openai", "anthropic"):
            monkeypatch.setitem(sys.modules, module, None)
        from schemas.models import ScopePackages

        scope = LLMClient(provider="openai").complete_json(
            system="s", user="u", target_model=ScopePackages, demo_fixture="_llm_probe.json")
        assert scope.project_name == "Probe"
