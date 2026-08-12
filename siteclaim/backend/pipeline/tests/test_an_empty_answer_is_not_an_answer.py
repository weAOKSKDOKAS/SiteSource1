"""An answer that ran out of room is not a malformed answer, and must not arrive as one.

FOUND ON THE FIRST LIVE RUN of the drawing reader, 2026-08-11. Reading a 91-row schedule came back
to the operator as::

    ValidationError: 1 validation error for RawSchedule
      Invalid JSON: EOF while parsing a value at line 1 column 0
      [type=json_invalid, input_value='', input_type=str]

That message is completely true about a string that was never the problem. The model wrote valid
JSON and ran out of room: serialising the reader's own output type for 91 boreholes and 21 trial
pits is 36,885 characters, roughly 9,200-10,250 output tokens, against `DEFAULT_MAX_TOKENS` of
8,000. A nine-row sheet in the same run needed ~991 and read perfectly.

THIS IS TRAP 10, RECURRING ON THE ONE PROVIDER THE FIX NEVER COVERED. The guard was installed on
DeepSeek and on OpenAI. It was not installed on Anthropic — and `_route` forces any request carrying
IMAGES onto a `VISION_CAPABLE` provider, which excludes DeepSeek. So a vision call is routed, by
construction, onto the only path with no guard, and `DEEPSEEK_MIN_MAX_TOKENS` — the 32,000-token
floor that exists for exactly this failure — can never apply to it.

And the corrective retry made it worse rather than better: it re-sent the identical budget, so it
failed identically at double the cost. Trap 10 predicted that in writing.
"""

from __future__ import annotations

import pytest

from pipeline.llm_client import (
    DEFAULT_MAX_TOKENS,
    VISION_CAPABLE,
    VISION_FALLBACK,
    CompletionTruncated,
    _looks_truncated,
)


class TestAVisionCallCannotReachTheExistingFloor:
    """Why the guard that already existed could not have caught this."""

    def test_deepseek_is_not_vision_capable(self):
        assert "deepseek" not in VISION_CAPABLE

    def test_the_vision_fallback_is_the_path_that_had_no_guard(self):
        assert VISION_FALLBACK == "anthropic"
        assert VISION_FALLBACK in VISION_CAPABLE

    def test_the_default_budget_is_smaller_than_the_sheet_that_failed(self):
        """36,885 characters of JSON is ~9,200-10,250 tokens. The default is 8,000."""
        assert DEFAULT_MAX_TOKENS == 8000


class TestTruncationIsRecognisedRatherThanRetried:
    """`_looks_truncated` decides whether the corrective retry is worth making at all."""

    def test_an_answer_that_stops_mid_object_is_truncated(self):
        assert _looks_truncated('{"boreholes":[{"station":"CE19-ABH02","easting":8251' + "8" * 300)

    def test_an_answer_that_stops_mid_array_is_truncated(self):
        assert _looks_truncated('[{"station":"CE19-ABH02"' + "x" * 300)

    def test_a_complete_object_is_not(self):
        assert not _looks_truncated('{"boreholes":[],"trial_pits":[]}')

    def test_prose_is_not_truncation_and_still_gets_its_retry(self):
        """A model that answers in words wrote the wrong SHAPE, which the corrective retry exists
        to fix. Refusing that retry would turn a recoverable call into a failure."""
        assert not _looks_truncated("I am sorry, I cannot read this drawing." + " x" * 200)

    def test_an_empty_answer_is_not_this_check_s_business(self):
        """An empty string never reaches here — the provider guard raises first, with a message
        that names the budget. Treating "" as truncation here would produce a worse sentence."""
        assert not _looks_truncated("")
        assert not _looks_truncated("   ")

    def test_a_short_broken_answer_still_gets_its_retry(self):
        """The check errs toward retrying. A false positive costs a retry that might have worked;
        a false negative costs only the retry we already make."""
        assert not _looks_truncated('{"bore')

    def test_it_needs_the_answer_to_have_opened_like_json(self):
        assert not _looks_truncated("Here is the table you asked for:" + " x" * 200)


class TestTheGuardSaysWhatIsActuallyWrong:

    def test_it_is_not_a_validation_error(self):
        """The whole point. A `ValidationError` about `input_value=''` sends somebody to look at
        the schema; this sends them to the budget."""
        assert issubclass(CompletionTruncated, RuntimeError)
        assert not issubclass(CompletionTruncated, ValueError), (
            "complete_json catches (ValidationError, ValueError) — a truncation must not be "
            "swallowed by the corrective retry it cannot fix")

    def test_the_message_names_the_two_things_that_fix_it(self):
        exc = CompletionTruncated(
            "the answer stopped mid-JSON after 31,997 characters against a 8,000-token budget, so "
            "it is incomplete rather than malformed. Retrying with the same budget would fail the "
            "same way: ask for a bigger budget, or give the model less to answer in one call.")
        assert "bigger budget" in str(exc)
        assert "less to answer in one call" in str(exc)


class TestTheAnthropicPathNowRaises:
    """The provider call itself, with the SDK stubbed — the guard is three lines and it is the
    difference between a diagnosis and a pydantic internals string."""

    @staticmethod
    def _resp(text: str, stop_reason: str):
        class _Block:
            type = "text"

            def __init__(self, value):
                self.text = value

        class _Resp:
            content = [_Block(text)] if text else []
            usage = None

        _Resp.stop_reason = stop_reason
        return _Resp()

    def _call(self, monkeypatch, resp):
        import pipeline.llm_client as mod

        client = mod.LLMClient(provider="anthropic")

        class _Messages:
            def create(self, **_kw):
                return resp

        class _Anthropic:
            messages = _Messages()

        client._clients["anthropic"] = _Anthropic()
        return client._anthropic_complete(
            system="s", user="u", images=None, max_tokens=8000, model="claude-sonnet-4-6")

    def test_an_empty_answer_that_hit_the_ceiling_raises(self, monkeypatch):
        with pytest.raises(CompletionTruncated) as caught:
            self._call(monkeypatch, self._resp("", "max_tokens"))
        # RE-ANCHORED 2026-08-12, disclosed: the budget is thousands-separated now, so this reads
        # "8,000-token budget". The subject of the test is that the ceiling is quoted at all.
        assert "8,000-token budget" in str(caught.value)

    def test_it_reports_where_the_budget_actually_went(self, monkeypatch):
        """RE-ANCHORED 2026-08-11, disclosed. The message said the answer was "absent" and stopped
        there — true, and not enough to act on. Two failures produce the same empty answer and need
        OPPOSITE fixes: an answer too big to write wants a bigger budget, and a budget spent on a
        chain of thought billed as completion tokens gets WORSE with one. The second live run hit
        the second kind and the message could not say so, so the next step would have been a guess.
        """
        with pytest.raises(CompletionTruncated) as caught:
            self._call(monkeypatch, self._resp("", "max_tokens"))
        message = str(caught.value).lower()
        assert "no content blocks at all" in message
        assert "in a text block" in message
        assert "buys more thinking" in message

    def test_the_evidence_comes_before_the_advice(self, monkeypatch):
        """RE-ANCHORED 2026-08-12, disclosed, and this is the assertion that replaces three
        literals with the property they were standing in for.

        The message carried the right evidence and carried it SECOND. Quoted in a report of the
        second live run it came out as:

            "claude-sonnet-5 used its entire 16000-token completion budget and returned no
             answer..."

        — the ellipsis swallowing the one fragment that chooses between the two opposite fixes. So
        the block shape now leads, and what is pinned here is the ORDER rather than the wording:
        a future rewrite may say it differently, but not later.
        """
        class _Thinking:
            type = "thinking"
            thinking = "x" * 4096

        class _Resp:
            content = [_Thinking()]
            usage = None
            stop_reason = "max_tokens"

        message = ""
        with pytest.raises(CompletionTruncated) as caught:
            self._call(monkeypatch, _Resp())
        message = str(caught.value)

        evidence = message.index("thinking: 4,096 chars")
        assert evidence < 80, (
            f"the block shape starts {evidence} characters in — far enough back that a quoted "
            f"first line loses it, which is exactly how this went missing before")
        assert evidence < message.lower().index("bigger budget"), (
            "the advice is printed before the evidence that chooses between the two halves of it")

    def test_the_shape_survives_being_cut_to_one_line(self, monkeypatch):
        """The real test of a diagnostic: truncate it the way a person quoting it would."""
        class _Thinking:
            type = "thinking"
            thinking = "x" * 4096

        class _Resp:
            content = [_Thinking()]
            usage = None
            stop_reason = "max_tokens"

        with pytest.raises(CompletionTruncated) as caught:
            self._call(monkeypatch, _Resp())
        assert "thinking" in str(caught.value)[:100]

    def test_a_thinking_block_is_named_and_sized(self, monkeypatch):
        """The distinguishing evidence. If the tokens are here, raising max_tokens is the wrong
        move and the message says so rather than leaving somebody to find out."""
        class _Thinking:
            type = "thinking"
            thinking = "x" * 4096

        class _Resp:
            content = [_Thinking()]
            usage = None
            stop_reason = "max_tokens"

        with pytest.raises(CompletionTruncated) as caught:
            self._call(monkeypatch, _Resp())
        assert "thinking: 4,096 chars" in str(caught.value)

    def test_an_empty_answer_that_stopped_normally_does_not(self, monkeypatch):
        """A model that legitimately answers with nothing is a different problem, and inventing a
        budget diagnosis for it would send somebody to the wrong place."""
        assert self._call(monkeypatch, self._resp("", "end_turn")) == ""

    def test_a_real_answer_is_returned_whatever_the_stop_reason(self, monkeypatch):
        """A truncated answer that DID write something is not this guard's business — the caller's
        `_looks_truncated` handles it, with the partial text in hand to say how far it got."""
        assert self._call(monkeypatch, self._resp('{"a":1}', "max_tokens")) == '{"a":1}'
        assert self._call(monkeypatch, self._resp('{"a":1}', "end_turn")) == '{"a":1}'
