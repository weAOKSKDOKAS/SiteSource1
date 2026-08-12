"""LLM plumbing for the SiteClaim pipeline (Layer 2) — provider-swappable.

Responsibilities:

* **DEMO_MODE** (env flag): when on, ``complete_json`` returns canned fixtures from
  ``backend/fixtures/`` and short-circuits BEFORE any provider code runs. No SDK is
  imported and no socket is opened — the offline demo is safe even with
  ``openai`` / ``anthropic`` / ``pymupdf`` all uninstalled.
* **Three providers** — ``anthropic``, ``deepseek`` and ``openai`` — described by two tables rather
  than by branching: :data:`PROVIDER_MODEL_ENV` (which env var names each one's model) and
  :data:`VISION_CAPABLE` (which can be handed a page image). Adding a fourth is entries in those
  tables plus one ``_*_complete`` method. All SDKs are imported **lazily**, only on the live path,
  one client cached per provider.
* **Provider routing by content** (``_route``): a call carrying any image goes to a provider that
  can actually read one — an explicitly configured vision-capable provider keeps its images, and one
  that cannot read them falls back to Anthropic. A **text-only** call goes to an explicitly
  configured provider, else the cheap default: **DeepSeek** when ``DEEPSEEK_API_KEY`` is set
  (OpenAI-compatible API at ``https://api.deepseek.com``), otherwise **Anthropic** in text mode so
  it works with no extra key.
* **Multimodal**: ``complete_json(images=[...base64 PNG...])`` attaches the document
  images to the message (OpenAI ``image_url`` blocks / Anthropic ``image`` blocks).
* **Strict-JSON parsing** into a Pydantic model (strip ``` fences → parse, one
  corrective retry) and retry-on-transient — for every provider.

NOTE on DeepSeek vision: DeepSeek V4's chat API **rejects** ``image_url`` content (confirmed error:
"unknown variant `image_url`, expected `text`"). That is why it is absent from :data:`VISION_CAPABLE`
— a fact about DeepSeek, not a rule that images belong to Anthropic. ``build_openai_messages`` emits
the ``image_url`` data-URL blocks that genuinely vision-capable OpenAI endpoints take, which is why
OpenAI vision needed no new builder.

WHO READS THE DOCUMENTS: ``EXTRACTION_PROVIDER`` names the provider for the ingest stage, and
``client_boq.llm.make_client(stage="ingest")`` passes it through as an explicit provider so it
reaches the live call path. Every other stage is unaffected by it.
"""

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel, ValidationError

ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
DEFAULT_MAX_TOKENS = 8000  # a sane per-chunk ceiling; ingest chunks its input so the output never truncates

# Which env var names the model for each provider, and what it falls back to.
#
# A table rather than a chain of ``if provider == ...`` branches, because the two-way version of
# this had an `else` that silently handed any unrecognised provider the DeepSeek model. A lookup
# raises on an unknown name instead, which is the difference between a typo you find immediately
# and a tender priced by a model nobody chose.
# Several names per provider where more than one is in circulation: the first is canonical, the
# rest are aliases people actually have in their .env.
PROVIDER_MODEL_ENV: dict[str, tuple[tuple[str, ...], str]] = {
    "anthropic": (("ANTHROPIC_MODEL",), ANTHROPIC_MODEL),
    "deepseek": (("DEEPSEEK_MODEL",), DEFAULT_DEEPSEEK_MODEL),
    "openai": (("OPENAI_MODEL", "CHATGPT_MODEL"), DEFAULT_OPENAI_MODEL),
}
PROVIDER_KEY_ENV: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "openai": ("OPENAI_API_KEY", "CHATGPT_API_KEY"),
}
PROVIDERS = tuple(PROVIDER_MODEL_ENV)

# Which providers can actually be handed a page image.
#
# A physical constraint, not a preference: DeepSeek V4's chat API rejects `image_url` content
# outright ("unknown variant `image_url`, expected `text`"). Written as data so that adding a
# vision-capable provider is one entry here rather than an edit to the routing logic.
VISION_CAPABLE = frozenset({"anthropic", "openai"})

# The provider images fall back to when the configured one cannot read them.
VISION_FALLBACK = "anthropic"

# Some OpenAI models reject `max_tokens` and require `max_completion_tokens` instead. Which one a
# given model wants is discovered on the first call and remembered — see `_openai_complete`.
_OPENAI_TOKEN_PARAM = "max_tokens"

# REASONING MODELS BREAK THE MEANING OF max_tokens.
#
# `DEFAULT_MAX_TOKENS` was written when a completion budget was a budget for the ANSWER. On a
# reasoning model (deepseek-v4-flash, and the -pro default) the same budget must also cover the
# chain of thought, which is charged as completion tokens and is not returned in `content`. A hard
# prompt therefore spends the entire allowance thinking, `content` comes back EMPTY, and the caller
# sees "Invalid JSON: EOF while parsing" — a truthful message about a string that was never the
# real problem.
#
# Measured on 2026-08-01 against deepseek-v4-flash: max_tokens=600 -> 2,175 chars of
# reasoning_content, content='' , finish_reason='length'. Same prompt at 8,000 -> 3,240 completion
# tokens and a correct answer. The split planner needed more than 8,000 and failed twice, retry
# included, because the retry re-sent the same budget.
#
# So the floor below is reasoning headroom, not generosity: it is what makes a documented budget
# mean the same thing on both providers. 32,000 and 65,536 were both accepted by the API.
DEEPSEEK_MIN_MAX_TOKENS = int(os.getenv("DEEPSEEK_MIN_MAX_TOKENS", "32000"))
_MAX_RETRIES = 4
_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Back-compat alias (older imports referenced MODEL).
MODEL = ANTHROPIC_MODEL

def _looks_truncated(raw: str) -> bool:
    """Did this answer stop mid-structure rather than come back malformed?

    Deliberately conservative — the cost of a false positive is refusing a retry that might have
    worked, and the cost of a false negative is only the retry we already do. So: it must open like
    JSON, be substantial, and end somewhere a finished document never ends. A model that returns
    prose, or an apology, or a short broken object is NOT this case and still gets its retry.
    """
    text = (raw or "").strip()
    if len(text) < 200 or not text.startswith(("{", "[")):
        return False
    return not text.endswith(("}", "]"))


class CompletionTruncated(RuntimeError):
    """The model hit its completion ceiling without writing an answer.

    Distinct from a bad answer, and deliberately NOT retried by ``complete_json``'s corrective
    pass: that retry re-sends the same budget, so it would fail identically while costing a second
    call. Surfaced to the operator with the two things that actually fix it.
    """


T = TypeVar("T", bound=BaseModel)

_TRUTHY = {"1", "true", "yes", "on"}


#: The operator's override, or ``None`` for "whatever the environment says".
#:
#: WHY THIS IS NOT A ROW IN A TABLE. `client_boq/store.py:72` chooses WHICH DATABASE to open by
#: calling :func:`demo_mode`, so a flag stored in `client_boq_settings` would be circular — you
#: would have to know the mode to know which database to read the mode from, and the demo DB and
#: the live DB would each hold their own answer. A process variable has no such problem, and every
#: one of the 61 non-test call sites reads `demo_mode()` from inside a function, so a change takes
#: effect on the next call without a restart.
#:
#: IT DOES NOT SURVIVE A RESTART, deliberately. The environment is the deployment's decision and
#: this is the operator's; a process that comes back up returns to what it was deployed as, so a
#: server cannot be left in demo by somebody who forgot. The UI says so rather than implying
#: otherwise.
_demo_override: Optional[bool] = None


def demo_mode() -> bool:
    """True when demo mode is on — the operator's override if there is one, else ``DEMO_MODE``.

    Read dynamically, never cached, so tests can toggle it and so a mid-session change reaches
    every stage on its next call.
    """
    if _demo_override is not None:
        return _demo_override
    return os.getenv("DEMO_MODE", "").strip().lower() in _TRUTHY


def set_demo_mode(on: Optional[bool]) -> bool:
    """Override the environment for this process. ``None`` clears it. Returns the mode now in force.

    THE ONE WRITER of the override, so there is a single place to look when the mode is not what
    somebody expected. Deliberately takes a tri-state rather than a bool: "the operator has not
    chosen" and "the operator chose demo" are different facts, and collapsing them would make
    clearing the override impossible.
    """
    global _demo_override
    _demo_override = None if on is None else bool(on)
    return demo_mode()


def demo_mode_source() -> str:
    """Where the current mode came from: ``"operator"`` or ``"environment"``.

    On the screen this is the difference between "somebody switched this" and "this is how it was
    deployed", and an operator who opens the app mid-session cannot tell those apart from the mode
    alone.
    """
    return "operator" if _demo_override is not None else "environment"


def extraction_provider() -> str:
    """The provider that reads documents — ``EXTRACTION_PROVIDER``, 'anthropic' by default.

    Named for the extraction stage because that is what it governs: the ingest pass that decides how
    a binder is cut and what each part says. ``client_boq.llm.make_client(stage="ingest")`` passes it
    through as an explicit provider, which is what makes it reach the live call path.
    """
    return configured_extraction_provider() or "anthropic"


def configured_extraction_provider() -> str:
    """``EXTRACTION_PROVIDER`` as actually set, or ``''`` when it is not.

    Distinct from :func:`extraction_provider`, which supplies the default, and the difference
    matters: "nobody configured this" must not become an explicit choice of Anthropic. Passing a
    provider explicitly suppresses the cheap-text routing (``_route``), so defaulting here would
    quietly move every ingest off DeepSeek for anyone who has a DeepSeek key and no opinion about
    extraction.
    """
    return os.getenv("EXTRACTION_PROVIDER", "").strip().lower()


def model_for_provider(provider: str) -> str:
    """The model a provider will use — its env override, else its shipped default."""
    try:
        env_names, fallback = PROVIDER_MODEL_ENV[provider]
    except KeyError:
        raise ValueError(
            f"{provider!r} is not a provider this client knows. There are "
            f"{len(PROVIDERS)}: {', '.join(PROVIDERS)}."
        ) from None
    return _first_env(*env_names, default=fallback)


def provider_key(provider: str) -> str:
    """The API key for a provider, '' when none is set."""
    return _first_env(*PROVIDER_KEY_ENV.get(provider, ()))


def _first_env(*names: str, default: str = "") -> str:
    """The first of several env vars that is actually set.

    Exists so ``OPENAI_API_KEY`` and ``CHATGPT_API_KEY`` can both work: the first is what the SDK
    and every other tool expects, the second is what people who think of it as "the ChatGPT key"
    write in their .env. Supporting both costs one function and saves a confusing empty-key failure.
    """
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n```$", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Remove a surrounding ```/```json code fence if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Message builders — pure, no SDK import, so they are unit-testable offline.
# `images` is a list of base64-encoded PNG strings (see pipeline.documents).
# ---------------------------------------------------------------------------
def build_openai_messages(system: str, user: str, images: Optional[list[str]] = None) -> list[dict]:
    """OpenAI/DeepSeek chat messages; images become image_url base64 data URLs."""
    if images:
        content: object = [
            {"type": "text", "text": user},
            *(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                for b64 in images
            ),
        ]
    else:
        content = user
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def build_anthropic_content(user: str, images: Optional[list[str]] = None) -> object:
    """Anthropic user content; images become base64 image blocks (text last)."""
    if not images:
        return user
    return [
        *(
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}
            for b64 in images
        ),
        {"type": "text", "text": user},
    ]


class LLMClient:
    """Provider-swappable LLM client with DEMO_MODE + strict-JSON parsing."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None) -> None:
        self.provider = (provider or extraction_provider()).lower()  # constructed default
        # An EXPLICITLY passed provider is remembered separately from the env-derived default,
        # because _route honours it for text calls (see there). Callers that construct bare
        # LLMClient() — every procurement site — leave this None and route exactly as before.
        self._provider_arg = provider.lower().strip() if provider else None
        self._model_arg = model  # explicit model override, if any
        self.model = model or self._default_model()
        self._clients: dict = {}  # one lazily-built SDK client per provider (routing may switch)
        #: One record per LIVE call made through this client — provider, model, ms, in/out tokens.
        #:
        #: Named `call_log` and not `calls`: several test doubles in this repo already keep a
        #: list called `calls` holding the PROMPTS they were asked, and a reader duck-typing on
        #: the name picked those up as telemetry. A name that two things answer to is a name that
        #: reads the wrong one.
        #: Never populated in DEMO (the fixture returns first), which is itself the honest answer:
        #: a demo run cost nothing and took no time worth reporting.
        self.call_log: list[dict] = []
        self._clients_lock = threading.Lock()  # guards lazy construction under concurrent chunk calls

    def _default_model(self) -> str:
        # An unknown provider used to fall through to the DeepSeek model. It now raises, because a
        # provider name nobody recognises is a configuration mistake and pricing a tender with a
        # silently substituted model is the worst possible way to find that out.
        return model_for_provider(self.provider)

    # -- provider routing by content ----------------------------------------
    def _route(self, images: Optional[list[str]]) -> str:
        """Pick the provider for a call by its content.

        A call carrying any image goes to a provider that can actually read one. That is a physical
        constraint (DeepSeek's chat API rejects ``image_url`` outright) rather than a preference, so
        it outranks everything below — but it is a constraint on *DeepSeek*, not a law that images
        belong to Anthropic. An explicitly configured vision-capable provider keeps its images; one
        that cannot read them falls back, because a silent text-only read of a scanned page would
        return a confident summary of nothing.

        A text-only call goes to an EXPLICITLY constructed provider when one was passed
        (``LLMClient(provider=...)`` — how client_boq applies its settings), else the cheap default:
        DeepSeek when ``DEEPSEEK_API_KEY`` is set, otherwise Anthropic in text mode. Bare
        ``LLMClient()`` — every procurement call site — routes exactly as it always has.
        """
        if images:
            chosen = self._provider_arg or VISION_FALLBACK
            return chosen if chosen in VISION_CAPABLE else VISION_FALLBACK
        if self._provider_arg:
            return self._provider_arg
        if provider_key("deepseek"):
            return "deepseek"
        return "anthropic"

    def _model_for(self, provider: str) -> str:
        """The model to use for a routed provider (honours an explicit constructor
        override for the matching provider, else the env default)."""
        if provider == self.provider and self._model_arg:
            return self._model_arg
        return model_for_provider(provider)

    # -- public API ---------------------------------------------------------
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        target_model: type[T],
        demo_fixture: Optional[str] = None,
        images: Optional[list[str]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        purpose: str = "",
    ) -> T:
        """Return ``target_model`` parsed from the model's JSON output.

        DEMO_MODE loads ``demo_fixture`` and never touches the network (no SDK
        import). Otherwise it calls the configured provider — attaching ``images``
        if given — strips fences, and parses, with one corrective JSON retry.
        ``purpose`` labels the call in the per-call log (ingest-chunk / classify / …).
        """
        if demo_mode():
            return self._load_fixture(demo_fixture, target_model)
        raw = self._complete_text(system=system, user=user, images=images, max_tokens=max_tokens, purpose=purpose)
        try:
            return target_model.model_validate_json(strip_code_fences(raw))
        except (ValidationError, ValueError):
            # A TRUNCATED ANSWER IS NOT A BADLY-FORMATTED ONE, and the corrective retry cannot fix
            # it. The prose below asks for valid JSON; the model already wrote valid JSON and ran
            # out of room. Re-sending the identical budget fails identically at double the cost —
            # which is what the live run did — so an answer that looks cut off says so instead.
            if _looks_truncated(raw):
                raise CompletionTruncated(
                    f"the answer stopped mid-JSON after {len(raw):,} characters against a "
                    f"{max_tokens:,}-token budget, so it is incomplete rather than malformed. "
                    f"Retrying with the same budget would fail the same way: ask for a bigger "
                    f"budget, or give the model less to answer in one call."
                ) from None
            corrective = (
                user
                + "\n\nYour previous output was invalid JSON for the required schema. "
                "Return ONLY a single valid JSON object that matches the schema — "
                "no prose, no explanation, no code fences."
            )
            raw2 = self._complete_text(
                system=system, user=corrective, images=images, max_tokens=max_tokens,
                purpose=f"{purpose or 'llm'}-retry",
            )
            return target_model.model_validate_json(strip_code_fences(raw2))

    # -- DEMO_MODE ----------------------------------------------------------
    def _load_fixture(self, demo_fixture: Optional[str], target_model: type[T]) -> T:
        if not demo_fixture:
            raise RuntimeError("DEMO_MODE is on but no demo_fixture was provided for this call.")
        path = _FIXTURES_DIR / demo_fixture
        if not path.is_file():
            raise FileNotFoundError(f"DEMO_MODE fixture not found: {path}")
        return target_model.model_validate_json(path.read_text(encoding="utf-8"))

    # -- live path (lazy imports; never reached in DEMO_MODE) ---------------
    def _complete_text(
        self, *, system: str, user: str, images: Optional[list[str]], max_tokens: int, purpose: str = ""
    ) -> str:
        provider = self._route(images)  # content routing: images -> vision-capable, text -> cheap
        model = self._model_for(provider)
        if provider == "anthropic":
            return self._anthropic_complete(system, user, images, max_tokens, model, purpose)
        if provider == "openai":
            return self._openai_complete(system, user, images, max_tokens, model, purpose)
        return self._deepseek_complete(system, user, images, max_tokens, model, purpose)

    def _log_call(self, provider: str, model: str, purpose: str, ms: float, tokens: dict) -> None:
        """One line per live call to stdout (visibility for the fine-tuning phase), and a
        JSONL record when ``SITESOURCE_LLM_LOG`` names a file. Never raises — logging must
        not break a call. DEMO_MODE never reaches here (it returns a fixture first).

        ALSO KEPT ON THE CLIENT, as ``call_log``. Comparing two providers on one sheet has been done
        twice by hand from row counts and an afternoon each time; the evidence exists at this line
        and simply had nowhere to go. A caller that wants to say what its run cost can now read it
        back instead of parsing stdout.
        """
        tin, tout = tokens.get("in"), tokens.get("out")
        self.call_log.append({"provider": provider, "model": model, "purpose": purpose or "llm",
                           "ms": round(ms), "in": tin, "out": tout})
        line = f"[llm] provider={provider} model={model} purpose={purpose or 'llm'} ms={ms:.0f}"
        if tin is not None or tout is not None:
            line += f" in={tin} out={tout}"
        print(line, flush=True)
        path = os.getenv("SITESOURCE_LLM_LOG", "").strip()
        if path:
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "provider": provider, "model": model, "purpose": purpose or "llm",
                        "ms": round(ms), "in": tin, "out": tout,
                    }) + "\n")
            except OSError:
                pass  # a log write must never fail the pipeline

    def _retry(self, call, transient: tuple):
        """Run ``call`` with exponential backoff on transient/5xx errors."""
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                return call()
            except transient as exc:  # provider-specific transient classes
                last_exc = exc
            except Exception as exc:  # noqa: BLE001 — retry only on 5xx, else re-raise
                code = getattr(exc, "status_code", None)
                if isinstance(code, int) and code >= 500:
                    last_exc = exc
                else:
                    raise
            time.sleep(min(2**attempt, 16))
        assert last_exc is not None
        raise last_exc

    def _deepseek_complete(self, system: str, user: str, images: Optional[list[str]], max_tokens: int, model: str, purpose: str = "") -> str:
        import openai  # lazy: importing this module must not require the SDK

        with self._clients_lock:  # concurrent chunk calls may hit this first-time together
            if "deepseek" not in self._clients:
                self._clients["deepseek"] = openai.OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=os.getenv("DEEPSEEK_API_KEY"))
        client = self._clients["deepseek"]
        transient = (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        )
        messages = build_openai_messages(system, user, images)  # text-only in practice
        tokens: dict = {}
        # Reasoning headroom — see DEEPSEEK_MIN_MAX_TOKENS. Never lowers a caller's explicit ask.
        budget = max(max_tokens, DEEPSEEK_MIN_MAX_TOKENS)

        def call() -> str:
            resp = client.chat.completions.create(model=model, messages=messages, max_tokens=budget)
            usage = getattr(resp, "usage", None)
            tokens["in"] = getattr(usage, "prompt_tokens", None)
            tokens["out"] = getattr(usage, "completion_tokens", None)
            choice = resp.choices[0]
            content = choice.message.content or ""
            # An empty answer that stopped on `length` is a CONFIGURATION fault, not a reply: the
            # model spent the whole budget reasoning and never wrote an answer. Returning "" here
            # sends the caller a JSON parse error about a string that was never the problem, and
            # `complete_json`'s corrective retry then re-sends the identical budget and fails
            # identically. Raised loudly instead — the same rule as OcrEngineUnavailable, and for
            # the same reason: a misconfiguration must not be mistaken for an answer.
            if not content.strip() and getattr(choice, "finish_reason", None) == "length":
                reasoning = getattr(choice.message, "reasoning_content", None) or ""
                # The evidence first, same as the anthropic path — see the long note there. Here it
                # is one number rather than a block map, because DeepSeek puts the whole chain of
                # thought in one field.
                raise CompletionTruncated(
                    f"{model} spent its whole {budget:,}-token budget on "
                    f"[reasoning_content: {len(reasoning):,} chars] and wrote no answer. "
                    f"Raise DEEPSEEK_MIN_MAX_TOKENS, or set DEEPSEEK_MODEL to a non-reasoning "
                    f"model."
                )
            return content

        start = time.perf_counter()
        text = self._retry(call, transient)
        self._log_call("deepseek", model, purpose, (time.perf_counter() - start) * 1000, tokens)
        return text

    def _openai_complete(self, system: str, user: str, images: Optional[list[str]], max_tokens: int, model: str, purpose: str = "") -> str:
        """OpenAI proper — the same SDK DeepSeek borrows, without DeepSeek's two adaptations.

        Deliberately NOT a call into ``_deepseek_complete`` with a different ``base_url``:

        * **No ``DEEPSEEK_MIN_MAX_TOKENS`` floor.** That floor is reasoning headroom for DeepSeek's
          models. Applying it here would send ``max_tokens=32000`` on every OpenAI call, silently
          and expensively, for a reason that has nothing to do with OpenAI.
        * **The token parameter is discovered, not assumed.** Newer OpenAI models reject
          ``max_tokens`` and require ``max_completion_tokens``. Which one this model wants is found
          out on the first call and remembered for the process, so a wrong guess costs one retry
          rather than every ingest failing on a parameter name.

        Images ride along unchanged: ``build_openai_messages`` already emits the ``image_url``
        data-URL blocks, which is why vision needed no new builder.
        """
        import openai  # lazy: importing this module must not require the SDK

        key = provider_key("openai")
        if not key:
            raise RuntimeError(
                "OpenAI is the configured provider but no key is set. Put OPENAI_API_KEY (or "
                "CHATGPT_API_KEY) in backend/.env."
            )
        with self._clients_lock:  # concurrent chunk calls may hit this first-time together
            if "openai" not in self._clients:
                self._clients["openai"] = openai.OpenAI(api_key=key)
        client = self._clients["openai"]
        transient = (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        )
        messages = build_openai_messages(system, user, images)
        tokens: dict = {}
        # An empty tuple never catches, which is the right behaviour for an SDK build that has no
        # such class: the parameter fallback simply does not apply and the original error surfaces.
        bad_request = getattr(openai, "BadRequestError", ())

        def call() -> str:
            global _OPENAI_TOKEN_PARAM
            try:
                resp = client.chat.completions.create(
                    model=model, messages=messages, **{_OPENAI_TOKEN_PARAM: max_tokens})
            except bad_request as bad:
                # The one 400 worth reacting to rather than surfacing: the model wants the other
                # spelling of the same budget. Anything else is a real problem and is re-raised.
                other = ("max_completion_tokens" if _OPENAI_TOKEN_PARAM == "max_tokens"
                         else "max_tokens")
                if other not in str(bad):
                    raise
                _OPENAI_TOKEN_PARAM = other
                resp = client.chat.completions.create(
                    model=model, messages=messages, **{other: max_tokens})

            usage = getattr(resp, "usage", None)
            tokens["in"] = getattr(usage, "prompt_tokens", None)
            tokens["out"] = getattr(usage, "completion_tokens", None)
            choice = resp.choices[0]
            content = choice.message.content or ""
            # Same rule as DeepSeek's: an empty answer that stopped on `length` is a configuration
            # fault, not a reply. Returning "" would reach the caller as a JSON parse error about a
            # string that was never the problem, and the corrective retry would re-send the same
            # budget and fail identically.
            if not content.strip() and getattr(choice, "finish_reason", None) == "length":
                # WHERE THE BUDGET WENT, not an assertion about it. This message named reasoning as
                # the cause without ever looking, which is the same guess the anthropic path was
                # fixed to stop making — and it points at the opposite fix from the other case.
                # OpenAI reports the split under `completion_tokens_details`; when it does not, the
                # message says it does not rather than filling the gap in.
                details = getattr(usage, "completion_tokens_details", None)
                thought = getattr(details, "reasoning_tokens", None)
                spent = tokens.get("out")
                if thought is None:
                    shape = "no reasoning-token split reported"
                elif thought:
                    shape = (f"reasoning: {thought:,} of "
                             f"{f'{spent:,}' if spent is not None else 'an unreported number of'} "
                             f"output tokens")
                else:
                    shape = "reasoning: 0 tokens — the budget went to an answer that was cut off"
                raise CompletionTruncated(
                    f"{model} spent its whole {max_tokens:,}-token budget on [{shape}] and wrote "
                    f"no answer. IF THE REASONING COUNT IS HIGH the model is being paid to think "
                    f"and a bigger budget buys more thinking — set OPENAI_MODEL to a model that "
                    f"does not. IF IT IS ZERO OR UNREPORTED the answer was too big to write, so "
                    f"ask for less or raise the caller's max_tokens."
                )
            return content

        start = time.perf_counter()
        text = self._retry(call, transient)
        self._log_call("openai", model, purpose, (time.perf_counter() - start) * 1000, tokens)
        return text

    def _anthropic_complete(self, system: str, user: str, images: Optional[list[str]], max_tokens: int, model: str, purpose: str = "") -> str:
        import anthropic  # lazy

        with self._clients_lock:  # concurrent chunk calls may hit this first-time together
            if "anthropic" not in self._clients:
                self._clients["anthropic"] = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        client = self._clients["anthropic"]
        transient = (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,
        )
        content = build_anthropic_content(user, images)
        tokens: dict = {}

        def call() -> str:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
            )
            usage = getattr(resp, "usage", None)
            tokens["in"] = getattr(usage, "input_tokens", None)
            tokens["out"] = getattr(usage, "output_tokens", None)
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            # THE SAME RULE AS THE OTHER TWO PROVIDERS, on the one that needed it most.
            #
            # DeepSeek and OpenAI have raised on an empty answer that stopped at the ceiling since
            # trap 10; this path returned whatever it had, whatever `stop_reason` said. And it is
            # the path a VISION call is forced onto — `_route` sends any request carrying images to
            # a VISION_CAPABLE provider, which excludes DeepSeek — so `DEEPSEEK_MIN_MAX_TOKENS`,
            # the floor that exists for exactly this failure, cannot apply here by construction.
            #
            # Measured 2026-08-11 on the real drawing pack: reading a 91-row schedule needs
            # ~9,200-10,250 output tokens and DEFAULT_MAX_TOKENS is 8,000, so the answer was
            # truncated, the corrective retry hit the same ceiling, and an unguarded pydantic parse
            # of "" reached the operator as "Invalid JSON: EOF while parsing" — a completely true
            # statement about a string that was never the problem.
            if not text.strip() and getattr(resp, "stop_reason", None) == "max_tokens":
                # WHERE THE BUDGET WENT, not just that it went. Two different failures produce this
                # same empty answer and they need opposite fixes:
                #
                #   * the answer was too big to write   -> a bigger budget, or a smaller ask
                #   * the budget went somewhere that is not a text block (a chain of thought billed
                #     as completion tokens, the exact shape of trap 10 on DeepSeek) -> a bigger
                #     budget makes it WORSE, and the fix is to stop paying for the thinking
                #
                # Measured 2026-08-11 on the second live run: two slices of one sheet produced this
                # on 16,000 tokens while two other slices of the SAME sheet, same model, same
                # budget, wrote complete JSON. So the answer is demonstrably writable and something
                # else consumed those two. Nothing in the message said which, so the next run could
                # only guess. It says which now.
                blocks: dict[str, int] = {}
                for block in getattr(resp, "content", None) or []:
                    kind = str(getattr(block, "type", "?"))
                    body = getattr(block, "text", None) or getattr(block, "thinking", None) or ""
                    blocks[kind] = blocks.get(kind, 0) + len(str(body))
                shape = (", ".join(f"{k}: {n:,} chars" for k, n in sorted(blocks.items()))
                         or "NO CONTENT BLOCKS AT ALL")
                spent = tokens.get("out")
                # THE BLOCK SHAPE GOES FIRST, and that ordering is the whole point of this string.
                #
                # It was second, after the budget and the token count, and the first time this
                # fired for real the report of it read:
                #
                #     "claude-sonnet-5 used its entire 16000-token completion budget and returned
                #      no answer..."
                #
                # — with the shape inside the ellipsis. The one fragment that decides between the
                # two opposite fixes was the fragment that got trimmed, so the next move could only
                # be a guess, and the obvious guess (raise the ceiling) is the wrong one in one of
                # the two cases. A diagnostic that survives only when quoted in full is a
                # diagnostic that does not survive.
                raise CompletionTruncated(
                    f"{model} spent its whole {max_tokens:,}-token budget on [{shape}] and wrote "
                    f"no answer"
                    f"{f' ({spent:,} output tokens)' if spent is not None else ''}. "
                    f"IF THOSE TOKENS ARE IN A TEXT BLOCK the answer was too big to write, so ask "
                    f"for less or budget more. IF THEY ARE ANYWHERE ELSE — a thinking block, or no "
                    f"block at all — the model is being paid to think, and a bigger budget buys "
                    f"more thinking rather than an answer."
                )
            return text

        start = time.perf_counter()
        text = self._retry(call, transient)
        self._log_call("anthropic", model, purpose, (time.perf_counter() - start) * 1000, tokens)
        return text
