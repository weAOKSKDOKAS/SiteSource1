"""client_boq's LLM client construction — where the app-wide model setting is applied.

Every client_boq stage constructs its client here instead of calling ``LLMClient()`` bare. The
settings read is fresh per construction, and stages construct per run, so a changed setting takes
effect on the next run with no restart and no cache to invalidate.

Why not mutate ``os.environ``: the job pool (``jobs.py``) runs stages on threads, and a
process-global mutable env is a race nobody can see in a test. Passing ``provider=``/``model=``
explicitly is thread-safe and visible in a signature.

THE INGEST STAGE CHOOSES SEPARATELY
-----------------------------------
Reading the tender is not the same job as the eight stages that reason about what was read, and it
is the one that decides what every later stage is looking at. So it has its own provider setting:
``make_client(stage=STAGE_INGEST)`` resolves the stored ingest setting, then ``EXTRACTION_PROVIDER``,
then the app-wide setting — which is what makes that env var mean what its name has always implied.

The one thing no setting can change: a call carrying page images goes to a provider that can
actually read one. ``LLMClient._route`` enforces that from :data:`VISION_CAPABLE`, so choosing a
text-only provider for ingest does not silently produce a confident summary of a blank page.

Procurement is untouched by all of this: its call sites construct bare ``LLMClient()`` and route
from env exactly as before. That boundary (CLAUDE.md §4) is why this helper lives in client_boq
rather than in the shared chassis.
"""

from __future__ import annotations

from typing import Optional

from client_boq import store
from pipeline.llm_client import LLMClient, configured_extraction_provider

# The provider values a setting may hold. "" = auto (env-driven routing, the historical default).
SETTING_PROVIDER = "llm.provider"
SETTING_PROVIDER_INGEST = "llm.provider.ingest"
SETTING_MODEL_ANTHROPIC = "llm.model.anthropic"
SETTING_MODEL_DEEPSEEK = "llm.model.deepseek"
SETTING_MODEL_OPENAI = "llm.model.openai"
PROVIDERS = ("", "anthropic", "deepseek", "openai")

# Which stage is asking. Only ingest differs today; the constant exists so a call site says what it
# is rather than passing a bare string nobody can grep for.
STAGE_DEFAULT = ""
STAGE_INGEST = "ingest"

# provider name -> the key `current_settings()` returns that model under.
#
# Deliberately the dict key rather than the storage key (`llm.model.anthropic`): those are two
# different namespaces, and mapping to the wrong one fails silently — the lookup just returns None
# and the provider quietly uses its env default instead of the model somebody chose.
MODEL_KEY = {
    "anthropic": "model_anthropic",
    "deepseek": "model_deepseek",
    "openai": "model_openai",
}


def current_settings() -> dict:
    """The stored LLM settings, with '' meaning 'auto / env default'."""
    conn = store.get_conn()
    try:
        return {
            "provider": store.get_setting(conn, SETTING_PROVIDER, ""),
            "provider_ingest": store.get_setting(conn, SETTING_PROVIDER_INGEST, ""),
            "model_anthropic": store.get_setting(conn, SETTING_MODEL_ANTHROPIC, ""),
            "model_deepseek": store.get_setting(conn, SETTING_MODEL_DEEPSEEK, ""),
            "model_openai": store.get_setting(conn, SETTING_MODEL_OPENAI, ""),
        }
    finally:
        conn.close()


def resolve_provider(cfg: dict, stage: str = STAGE_DEFAULT) -> Optional[str]:
    """Which provider a stage should use, or ``None`` for env-driven routing.

    Ingest resolves in its own order — stored ingest setting, then ``EXTRACTION_PROVIDER``, then the
    app-wide setting — so that naming a provider for document reading does not require also changing
    what the reasoning stages use.
    """
    if stage == STAGE_INGEST:
        stored = (cfg.get("provider_ingest") or "").strip()
        if stored:
            return stored
        # Only when it is actually set — see configured_extraction_provider. An unset var must not
        # become an explicit choice, or ingest silently stops using the cheap text provider.
        from_env = configured_extraction_provider()
        if from_env:
            return from_env
    return (cfg.get("provider") or "").strip() or None


def make_client(*, stage: str = STAGE_DEFAULT) -> LLMClient:
    """The client every client_boq stage uses.

    Reads the app-wide setting and passes it explicitly; with nothing stored and no
    ``EXTRACTION_PROVIDER`` this is exactly ``LLMClient()``.
    """
    cfg = current_settings()
    provider = resolve_provider(cfg, stage)
    model = None
    if provider:
        key = MODEL_KEY.get(provider)
        model = (cfg.get(key) or None) if key else None
    return LLMClient(provider=provider, model=model)
