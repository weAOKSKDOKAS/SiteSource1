"""client_boq's LLM client construction — where the app-wide model setting is applied.

Every client_boq stage constructs its client here instead of calling ``LLMClient()`` bare. The
settings read is fresh per construction, and stages construct per run, so a changed setting takes
effect on the next run with no restart and no cache to invalidate.

Why not mutate ``os.environ``: the job pool (``jobs.py``) runs stages on threads, and a
process-global mutable env is a race nobody can see in a test. Passing ``provider=``/``model=``
explicitly is thread-safe and visible in a signature.

The one thing the setting cannot change: a call carrying page images always goes to Anthropic
vision, because DeepSeek's chat API rejects image input. That is a physical constraint, enforced
in ``LLMClient._route`` regardless of what is passed here — and the settings screen says so.

Procurement is untouched by all of this: its call sites construct bare ``LLMClient()`` and route
from env exactly as before. That boundary (CLAUDE.md §4) is why this helper lives in client_boq
rather than in the shared chassis.
"""

from __future__ import annotations

from client_boq import store
from pipeline.llm_client import LLMClient

# The provider values a setting may hold. "" = auto (env-driven routing, the historical default).
SETTING_PROVIDER = "llm.provider"
SETTING_MODEL_ANTHROPIC = "llm.model.anthropic"
SETTING_MODEL_DEEPSEEK = "llm.model.deepseek"
PROVIDERS = ("", "anthropic", "deepseek")


def current_settings() -> dict:
    """The stored LLM settings, with '' meaning 'auto / env default'."""
    conn = store.get_conn()
    try:
        return {
            "provider": store.get_setting(conn, SETTING_PROVIDER, ""),
            "model_anthropic": store.get_setting(conn, SETTING_MODEL_ANTHROPIC, ""),
            "model_deepseek": store.get_setting(conn, SETTING_MODEL_DEEPSEEK, ""),
        }
    finally:
        conn.close()


def make_client() -> LLMClient:
    """The client every client_boq stage uses. Reads the app-wide setting and passes it
    explicitly; with nothing stored this is exactly ``LLMClient()``."""
    cfg = current_settings()
    provider = cfg["provider"] or None
    model = None
    if provider == "anthropic":
        model = cfg["model_anthropic"] or None
    elif provider == "deepseek":
        model = cfg["model_deepseek"] or None
    return LLMClient(provider=provider, model=model)
