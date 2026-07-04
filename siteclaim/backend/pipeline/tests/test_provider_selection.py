"""Spec for the provider abstraction: selection, multimodal message shaping, and
the DEMO_MODE zero-dependency guarantee — all offline, no live call."""

import sys

from pipeline.llm_client import (
    LLMClient,
    build_anthropic_content,
    build_openai_messages,
    extraction_provider,
)
from schemas.models import ScopePackages

_B64 = "aGVsbG8="  # not a real PNG; we only check message shaping


def test_default_provider_is_anthropic(monkeypatch):
    # DeepSeek V4 rejects image input, so the default is Claude (native multimodal).
    monkeypatch.delenv("EXTRACTION_PROVIDER", raising=False)
    assert extraction_provider() == "anthropic"
    client = LLMClient()
    assert client.provider == "anthropic"
    assert client.model == "claude-sonnet-4-6"


def test_deepseek_is_selectable_as_non_default(monkeypatch):
    monkeypatch.setenv("EXTRACTION_PROVIDER", "deepseek")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    client = LLMClient()
    assert client.provider == "deepseek"
    assert client.model == "deepseek-v4-pro"


def test_deepseek_model_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    assert LLMClient(provider="deepseek").model == "deepseek-v4-flash"


def test_anthropic_model_reads_env(monkeypatch):
    # .env ANTHROPIC_MODEL=claude-sonnet-5 must be honoured (was a hardcoded constant).
    monkeypatch.delenv("EXTRACTION_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    assert LLMClient().model == "claude-sonnet-5"
    assert LLMClient()._model_for("anthropic") == "claude-sonnet-5"


def test_content_routing_sends_images_to_anthropic(monkeypatch):
    # Any image -> Anthropic vision, even when a DeepSeek key is configured (it rejects images).
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert LLMClient()._route([_B64]) == "anthropic"


def test_content_routing_text_prefers_deepseek_when_keyed(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert LLMClient()._route(None) == "deepseek"
    assert LLMClient()._route([]) == "deepseek"  # no images -> text path


def test_content_routing_text_falls_back_to_anthropic_without_a_key(monkeypatch):
    # No DeepSeek key yet: text runs on Anthropic text-mode (works today, cheaper than images).
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert LLMClient()._route(None) == "anthropic"


def test_openai_messages_text_only_uses_string_content():
    msgs = build_openai_messages("SYS", "USER", None)
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1] == {"role": "user", "content": "USER"}


def test_openai_messages_attach_image_url_blocks():
    msgs = build_openai_messages("SYS", "USER", [_B64])
    content = msgs[1]["content"]
    assert content[0] == {"type": "text", "text": "USER"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{_B64}"


def test_anthropic_content_text_only_is_a_string():
    assert build_anthropic_content("USER", None) == "USER"


def test_anthropic_content_attaches_image_blocks_text_last():
    content = build_anthropic_content("USER", [_B64])
    assert content[0]["type"] == "image"
    assert content[0]["source"] == {"type": "base64", "media_type": "image/png", "data": _B64}
    assert content[-1] == {"type": "text", "text": "USER"}


def test_demo_mode_needs_no_provider_sdk(monkeypatch):
    # Block every live dependency: a leak to the live path would ImportError.
    for mod in ("openai", "anthropic", "fitz", "pymupdf"):
        monkeypatch.setitem(sys.modules, mod, None)
    monkeypatch.setenv("DEMO_MODE", "true")
    scope = LLMClient().complete_json(
        system="x", user="y", target_model=ScopePackages, demo_fixture="_llm_probe.json"
    )
    assert scope.project_name == "Probe"
