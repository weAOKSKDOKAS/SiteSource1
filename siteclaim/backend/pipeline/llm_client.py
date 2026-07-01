"""LLM plumbing for the SiteClaim pipeline (Layer 2) — provider-swappable.

Responsibilities:

* **DEMO_MODE** (env flag): when on, ``complete_json`` returns canned fixtures from
  ``backend/fixtures/`` and short-circuits BEFORE any provider code runs. No SDK is
  imported and no socket is opened — the offline demo is safe even with
  ``openai`` / ``anthropic`` / ``pymupdf`` all uninstalled.
* **Provider abstraction** (env ``EXTRACTION_PROVIDER``, default ``anthropic``):
    - ``anthropic`` — the **default** Claude path; reads image/PDF blocks natively.
    - ``deepseek`` — the OpenAI-compatible API at ``https://api.deepseek.com`` via the
      ``openai`` SDK; model from ``DEEPSEEK_MODEL``. **Text-only** — DeepSeek V4's chat
      API rejects ``image_url`` input, so document uploads must use ``anthropic``.
  Both SDKs are imported **lazily**, only on the live path.
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

import os
import re
import time
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel, ValidationError

ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_MAX_TOKENS = 8000
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
        self.provider = (provider or extraction_provider()).lower()
        self.model = model or self._default_model()
        self._client = None  # lazily constructed on first live call

    def _default_model(self) -> str:
        if self.provider == "anthropic":
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
    ) -> T:
        """Return ``target_model`` parsed from the model's JSON output.

        DEMO_MODE loads ``demo_fixture`` and never touches the network (no SDK
        import). Otherwise it calls the configured provider — attaching ``images``
        if given — strips fences, and parses, with one corrective JSON retry.
        """
        if demo_mode():
            return self._load_fixture(demo_fixture, target_model)
        raw = self._complete_text(system=system, user=user, images=images, max_tokens=max_tokens)
        try:
            return target_model.model_validate_json(strip_code_fences(raw))
        except (ValidationError, ValueError):
            corrective = (
                user
                + "\n\nYour previous output was invalid JSON for the required schema. "
                "Return ONLY a single valid JSON object that matches the schema — "
                "no prose, no explanation, no code fences."
            )
            raw2 = self._complete_text(system=system, user=corrective, images=images, max_tokens=max_tokens)
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
    def _complete_text(self, *, system: str, user: str, images: Optional[list[str]], max_tokens: int) -> str:
        if self.provider == "anthropic":
            return self._anthropic_complete(system, user, images, max_tokens)
        if self.provider == "deepseek":
            return self._deepseek_complete(system, user, images, max_tokens)
        raise ValueError(f"unknown EXTRACTION_PROVIDER {self.provider!r} (use 'deepseek' or 'anthropic')")

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

    def _deepseek_complete(self, system: str, user: str, images: Optional[list[str]], max_tokens: int) -> str:
        import openai  # lazy: importing this module must not require the SDK

        if self._client is None:
            self._client = openai.OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=os.getenv("DEEPSEEK_API_KEY"))
        transient = (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.InternalServerError,
        )
        messages = build_openai_messages(system, user, images)

        def call() -> str:
            resp = self._client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=max_tokens
            )
            return resp.choices[0].message.content or ""

        return self._retry(call, transient)

    def _anthropic_complete(self, system: str, user: str, images: Optional[list[str]], max_tokens: int) -> str:
        import anthropic  # lazy

        if self._client is None:
            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        transient = (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,
        )
        content = build_anthropic_content(user, images)

        def call() -> str:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": content}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")

        return self._retry(call, transient)
