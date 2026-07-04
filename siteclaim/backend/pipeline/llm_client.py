"""LLM plumbing for the SiteClaim pipeline (Layer 2) — provider-swappable.

Responsibilities:

* **DEMO_MODE** (env flag): when on, ``complete_json`` returns canned fixtures from
  ``backend/fixtures/`` and short-circuits BEFORE any provider code runs. No SDK is
  imported and no socket is opened — the offline demo is safe even with
  ``openai`` / ``anthropic`` / ``pymupdf`` all uninstalled.
* **Provider routing by content** (``_route``): a call carrying any image goes to
  **Anthropic** (Sonnet) vision — DeepSeek V4's chat API rejects ``image_url`` input; a
  **text-only** call goes to the cheap text provider, **DeepSeek** when
  ``DEEPSEEK_API_KEY`` is set (OpenAI-compatible API at ``https://api.deepseek.com``,
  model from ``DEEPSEEK_MODEL``), otherwise **Anthropic** in text mode so it still works
  today with no new key. ``EXTRACTION_PROVIDER`` sets the constructed default; content
  routing overrides it so images never reach DeepSeek and text takes the cheapest path.
  Both SDKs are imported **lazily**, only on the live path, one client cached per provider.
* **Multimodal**: ``complete_json(images=[...base64 PNG...])`` attaches the document
  images to the message (OpenAI ``image_url`` blocks / Anthropic ``image`` blocks).
* **Strict-JSON parsing** into a Pydantic model (strip ``` fences → parse, one
  corrective retry) and retry-on-transient — for both providers.

NOTE on DeepSeek vision: DeepSeek V4's chat API **rejects** ``image_url`` content
(confirmed error: "unknown variant `image_url`, expected `text`"), so it is text-only
here and document uploads default to ``anthropic``, which reads images/PDF natively.
``build_openai_messages`` still emits OpenAI ``image_url`` blocks for genuinely
vision-capable OpenAI-compatible endpoints; only that one builder would change to
wire a different OpenAI-style vision provider.
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
DEFAULT_MAX_TOKENS = 8000  # a sane per-chunk ceiling; ingest chunks its input so the output never truncates
_MAX_RETRIES = 4
_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Back-compat alias (older imports referenced MODEL).
MODEL = ANTHROPIC_MODEL

T = TypeVar("T", bound=BaseModel)

_TRUTHY = {"1", "true", "yes", "on"}


def demo_mode() -> bool:
    """True when ``DEMO_MODE`` is set — read dynamically so tests can toggle it."""
    return os.getenv("DEMO_MODE", "").strip().lower() in _TRUTHY


def extraction_provider() -> str:
    """The configured extraction provider ('anthropic' default, or 'deepseek')."""
    return os.getenv("EXTRACTION_PROVIDER", "anthropic").strip().lower()


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
        self._model_arg = model  # explicit model override, if any
        self.model = model or self._default_model()
        self._clients: dict = {}  # one lazily-built SDK client per provider (routing may switch)
        self._clients_lock = threading.Lock()  # guards lazy construction under concurrent chunk calls

    def _default_model(self) -> str:
        if self.provider == "anthropic":
            return os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODEL)
        return os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)

    # -- provider routing by content ----------------------------------------
    def _route(self, images: Optional[list[str]]) -> str:
        """Pick the provider for a call by its content.

        A call carrying any image → Anthropic (Sonnet) vision — DeepSeek's chat API
        rejects image input. A text-only call → the cheap text provider: DeepSeek when
        ``DEEPSEEK_API_KEY`` is set, otherwise Anthropic in text mode (works today with
        no new key). Content routing overrides the constructed provider so images never
        reach DeepSeek and text takes the cheapest available path.
        """
        if images:
            return "anthropic"
        if os.getenv("DEEPSEEK_API_KEY", "").strip():
            return "deepseek"
        return "anthropic"

    def _model_for(self, provider: str) -> str:
        """The model to use for a routed provider (honours an explicit constructor
        override for the matching provider, else the env default)."""
        if provider == self.provider and self._model_arg:
            return self._model_arg
        if provider == "anthropic":
            return os.getenv("ANTHROPIC_MODEL", ANTHROPIC_MODEL)
        return os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)

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
        provider = self._route(images)  # content routing: images -> anthropic, text -> cheap
        model = self._model_for(provider)
        if provider == "anthropic":
            return self._anthropic_complete(system, user, images, max_tokens, model, purpose)
        return self._deepseek_complete(system, user, images, max_tokens, model, purpose)

    def _log_call(self, provider: str, model: str, purpose: str, ms: float, tokens: dict) -> None:
        """One line per live call to stdout (visibility for the fine-tuning phase), and a
        JSONL record when ``SITESOURCE_LLM_LOG`` names a file. Never raises — logging must
        not break a call. DEMO_MODE never reaches here (it returns a fixture first)."""
        tin, tout = tokens.get("in"), tokens.get("out")
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

        def call() -> str:
            resp = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
            usage = getattr(resp, "usage", None)
            tokens["in"] = getattr(usage, "prompt_tokens", None)
            tokens["out"] = getattr(usage, "completion_tokens", None)
            return resp.choices[0].message.content or ""

        start = time.perf_counter()
        text = self._retry(call, transient)
        self._log_call("deepseek", model, purpose, (time.perf_counter() - start) * 1000, tokens)
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
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")

        start = time.perf_counter()
        text = self._retry(call, transient)
        self._log_call("anthropic", model, purpose, (time.perf_counter() - start) * 1000, tokens)
        return text
