"""Thin Anthropic SDK wrapper for the SiteClaim pipeline (Layer 2 plumbing).

Responsibilities:

* **DEMO_MODE** (env flag): when on, return canned fixtures from ``backend/fixtures/``
  instead of calling the API. The ``anthropic`` SDK is imported **lazily**, only on
  the live path, so DEMO_MODE never imports it and never opens a socket — the
  offline demo is safe even without the package installed or a key set.
* **Retry on transient errors** (rate limit / 5xx / connection / timeout) with
  exponential backoff, on top of the SDK's own retries.
* **Strict-JSON parsing** into a target Pydantic model: strip ``` fences and parse,
  with one corrective retry ("your previous output was invalid JSON") on failure.

Model: ``claude-sonnet-4-6`` (per the Phase 2 spec), for both extraction and the judge.
Key: read from env ``ANTHROPIC_API_KEY`` (handled by the SDK's default client).
"""

import os
import re
import time
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel, ValidationError

MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 8000
_MAX_RETRIES = 4
_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

T = TypeVar("T", bound=BaseModel)

_TRUTHY = {"1", "true", "yes", "on"}


def demo_mode() -> bool:
    """True when ``DEMO_MODE`` is set — read dynamically so tests can toggle it."""
    return os.getenv("DEMO_MODE", "").strip().lower() in _TRUTHY


_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n```$", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Remove a surrounding ```/```json code fence if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    # Fallback: drop the first fence line and a trailing fence line.
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _text_of(response) -> str:
    """Concatenate the text blocks of an Anthropic Messages response."""
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")


class LLMClient:
    """Wrapper around ``anthropic.Anthropic`` with DEMO_MODE + strict-JSON parsing."""

    def __init__(self, model: str = MODEL) -> None:
        self.model = model
        self._client = None  # lazily constructed on first live call

    # -- public API ---------------------------------------------------------
    def complete_json(
        self,
        *,
        system: str,
        user: str,
        target_model: type[T],
        demo_fixture: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> T:
        """Return an instance of ``target_model`` from the model's JSON output.

        In DEMO_MODE this loads ``demo_fixture`` (a path under ``backend/fixtures/``)
        and never touches the network. Otherwise it calls the API, strips fences,
        and parses — retrying once with a corrective instruction on a parse failure.
        """
        if demo_mode():
            return self._load_fixture(demo_fixture, target_model)
        return self._live_complete_json(
            system=system, user=user, target_model=target_model, max_tokens=max_tokens
        )

    # -- DEMO_MODE ----------------------------------------------------------
    def _load_fixture(self, demo_fixture: Optional[str], target_model: type[T]) -> T:
        if not demo_fixture:
            raise RuntimeError(
                "DEMO_MODE is on but no demo_fixture was provided for this call."
            )
        path = _FIXTURES_DIR / demo_fixture
        if not path.is_file():
            raise FileNotFoundError(f"DEMO_MODE fixture not found: {path}")
        return target_model.model_validate_json(path.read_text(encoding="utf-8"))

    # -- live path (lazy import; never reached in DEMO_MODE) ----------------
    def _anthropic(self):
        if self._client is None:
            import anthropic  # lazy: importing this module must not require the SDK

            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        return self._client

    def _complete_text_with_retry(self, *, system: str, user: str, max_tokens: int) -> str:
        import anthropic  # lazy

        client = self._anthropic()
        transient = (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,
        )
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return _text_of(response)
            except transient as exc:
                last_exc = exc
            except anthropic.APIStatusError as exc:
                if exc.status_code >= 500:
                    last_exc = exc
                else:
                    raise
            time.sleep(min(2**attempt, 16))
        assert last_exc is not None
        raise last_exc

    def _live_complete_json(
        self, *, system: str, user: str, target_model: type[T], max_tokens: int
    ) -> T:
        raw = self._complete_text_with_retry(system=system, user=user, max_tokens=max_tokens)
        try:
            return target_model.model_validate_json(strip_code_fences(raw))
        except (ValidationError, ValueError):
            corrective = (
                user
                + "\n\nYour previous output was invalid JSON for the required schema. "
                "Return ONLY a single valid JSON object that matches the schema — "
                "no prose, no explanation, no code fences."
            )
            raw2 = self._complete_text_with_retry(
                system=system, user=corrective, max_tokens=max_tokens
            )
            return target_model.model_validate_json(strip_code_fences(raw2))
