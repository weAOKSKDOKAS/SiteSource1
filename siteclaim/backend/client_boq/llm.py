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

# THE DRAWING READ IS ITS OWN QUESTION, and this is why it gets its own two settings rather than
# sharing ingest's.
#
# It runs once or twice per tender, it reads a legal-quality drawing, and everything downstream —
# the map, the access cards, the rig optimiser, the independent check on Bill No.2's quantities —
# rests on what it returns. A wrong number here reads as confident and prices work. So it is the
# one place where the strongest available model is worth its cost and its latency, and where that
# choice should not also change the model that classifies a document or drafts an enquiry.
#
# `SETTING_MODEL_DRAWING` is the per-QUESTION part, and the shape that did not exist before: every
# other model setting is per PROVIDER, so choosing a stronger model for the drawing meant choosing
# it for every call to that provider. This one overrides the model for whichever provider the
# drawing read resolves to, and nothing else.
SETTING_PROVIDER_DRAWING = "llm.provider.drawing"
SETTING_MODEL_DRAWING = "llm.model.drawing"

# THE BRAIN IS ITS OWN QUESTION, for the same reason the drawing read is: it runs rarely, it
# reads EVERYTHING the tender knows at once, and its output steers where a person looks next.
# "One strong model to understand it all" is the owner's stated design — and that choice must
# not also change the model that classifies a document. Same two-setting shape as the drawing:
# a provider, and a per-question model that overrides whichever provider resolves.
#
# It falls through to the APP-WIDE default, not to ingest: the brain reasons over what was
# already read — it reads no pages, so inheriting the document-reading provider would be a
# category error dressed as a default.
SETTING_PROVIDER_BRAIN = "llm.provider.brain"
SETTING_MODEL_BRAIN = "llm.model.brain"
PROVIDERS = ("", "anthropic", "deepseek", "openai")

# Which stage is asking. Only ingest differs today; the constant exists so a call site says what it
# is rather than passing a bare string nobody can grep for.
STAGE_DEFAULT = ""
STAGE_INGEST = "ingest"
#: The station-schedule read. Falls through to ingest, then to the app-wide setting, so naming a
#: reader is optional and an installation that names none behaves exactly as it did.
STAGE_DRAWING = "drawing"
#: The whole-tender orchestrator. Falls through to the app-wide setting (it reads no pages).
STAGE_BRAIN = "brain"

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
            "provider_drawing": store.get_setting(conn, SETTING_PROVIDER_DRAWING, ""),
            "model_drawing": store.get_setting(conn, SETTING_MODEL_DRAWING, ""),
            "provider_brain": store.get_setting(conn, SETTING_PROVIDER_BRAIN, ""),
            "model_brain": store.get_setting(conn, SETTING_MODEL_BRAIN, ""),
        }
    finally:
        conn.close()


def resolve_provider(cfg: dict, stage: str = STAGE_DEFAULT) -> Optional[str]:
    """Which provider a stage should use, or ``None`` for env-driven routing.

    Ingest resolves in its own order — stored ingest setting, then ``EXTRACTION_PROVIDER``, then the
    app-wide setting — so that naming a provider for document reading does not require also changing
    what the reasoning stages use.
    """
    if stage == STAGE_DRAWING:
        stored = (cfg.get("provider_drawing") or "").strip()
        if stored:
            return stored
        # Falls through to ingest deliberately: reading a drawing IS reading the tender, so an
        # installation that has named an ingest provider and not a drawing one gets the sensible
        # answer rather than the app-wide default.
        return resolve_provider(cfg, STAGE_INGEST)
    if stage == STAGE_BRAIN:
        stored = (cfg.get("provider_brain") or "").strip()
        if stored:
            return stored
        # Falls through to the app-wide DEFAULT, not to ingest: the brain reasons over what was
        # already read. Inheriting the document-reading provider would be a category error.
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
    # THE PER-QUESTION OVERRIDE, and it is last so it wins. `model_drawing` names a model rather
    # than a provider, so it applies to whichever provider the drawing read resolved to — which is
    # the whole point: "read the drawing with the strongest thing available" is a statement about
    # this question, not about Anthropic.
    if stage == STAGE_DRAWING and (cfg.get("model_drawing") or "").strip():
        model = cfg["model_drawing"].strip()
    if stage == STAGE_BRAIN and (cfg.get("model_brain") or "").strip():
        model = cfg["model_brain"].strip()
    return LLMClient(provider=provider, model=model)
