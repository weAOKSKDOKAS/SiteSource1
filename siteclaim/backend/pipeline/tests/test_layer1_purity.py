"""Guard: Layer 1 (rules_engine) stays pure — no LLM imports anywhere in it."""

import importlib
import inspect

_LAYER1_MODULES = (
    "engine",
    "deadlines",
    "eligibility",
    "mandatory_fields",
    "notice_validity",
    "set_off",
    "business_days",
    "sopo_config",
    "_common",
)


def test_rules_engine_imports_no_llm_sdk():
    for name in _LAYER1_MODULES:
        source = inspect.getsource(importlib.import_module(f"rules_engine.{name}")).lower()
        assert "anthropic" not in source, f"rules_engine.{name} must not import anthropic"
        assert "import openai" not in source, f"rules_engine.{name} must not import openai"


def test_importing_llm_client_does_not_import_anthropic_eagerly():
    import sys

    sys.modules.pop("anthropic", None)
    importlib.import_module("pipeline.llm_client")
    assert "anthropic" not in sys.modules, "anthropic must be imported lazily, not at module load"
