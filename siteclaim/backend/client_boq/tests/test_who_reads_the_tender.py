"""``EXTRACTION_PROVIDER`` names who reads the tender — including the drawing.

THE DEFECT, confirmed on a live run. `ingest/schedule_read.py` built its client with a bare
`make_client()`. `resolve_provider` only consults `EXTRACTION_PROVIDER` on its `STAGE_INGEST`
branch, so the default stage skipped it, and with nothing stored in `client_boq_settings` the
provider came back `None`. `LLMClient._route` then sends an image call with no explicit provider
to `VISION_FALLBACK`:

    if images:
        chosen = self._provider_arg or VISION_FALLBACK

So `.env` said openai, the settings table was empty, and the failure named Anthropic. The one call
in the module that is most obviously the ingest stage — reading a tender drawing — was the one that
did not say so.

`ingest/s03_map_changes.py` had the same omission and is fixed with it: it runs `pdfops.page_text`
over the addendum letter and the head of every replacement, which is reading the tender by any
reading of the word.

The sweep at the bottom is the part that matters more than either fix. Two of four call sites under
`ingest/` were right and nothing enforced it, so the next one to be written is a coin toss. It is a
structural test over the AST rather than a behavioural one, because the thing being defended is a
convention, and a convention that is only tested where somebody remembered to test it is not
defended at all.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from client_boq import llm as llm_mod
from client_boq.ingest import schedule_read as reader

INGEST = pathlib.Path(llm_mod.__file__).parent / "ingest"


class TestTheDrawingReaderAsksAsTheIngestStage:
    def test_it_passes_the_drawing_stage(self, monkeypatch):
        """The line that was wrong, tested at the line that was wrong.

        RE-ANCHORED 2026-08-12, disclosed. It asserted `STAGE_INGEST`; the reader now asks as
        `STAGE_DRAWING`, which RESOLVES THROUGH ingest — so `EXTRACTION_PROVIDER` is still
        honoured, which was the property this test existed for and which the next test pins
        directly. The drawing gets its own stage because it is the one call where the strongest
        model is worth its cost, and saying so must not change who classifies a document.
        """
        seen: dict = {}

        def _spy(*, stage=llm_mod.STAGE_DEFAULT):
            seen["stage"] = stage
            raise RuntimeError("stop here — the client is all this test is about")

        monkeypatch.setattr(llm_mod, "make_client", _spy)
        report = reader.read_sheet(_one_page_pdf(), set_id="t", sheet="GI/210")
        assert seen.get("stage") == llm_mod.STAGE_DRAWING

    def test_the_drawing_stage_still_honours_extraction_provider(self, monkeypatch):
        """The property the re-anchor above must not have given up. A new stage that bypassed
        `EXTRACTION_PROVIDER` would reintroduce the exact live defect this file was written for."""
        monkeypatch.setattr(llm_mod, "current_settings", lambda: {
            "provider": "", "provider_ingest": "", "provider_drawing": "", "model_drawing": "",
            "model_anthropic": "", "model_deepseek": "", "model_openai": ""})
        monkeypatch.setenv("EXTRACTION_PROVIDER", "openai")
        client = llm_mod.make_client(stage=llm_mod.STAGE_DRAWING)
        assert client._route(images=["<base64>"]) == "openai"

    def test_a_client_that_cannot_be_built_is_reported_not_raised(self, monkeypatch):
        """`read_sheet` promises "never raises" in its own docstring, and did.

        Found by the test above: the construction sat OUTSIDE the try, and `make_client` reads
        the settings table — so an unreachable store threw straight past every degrade-not-fail
        path in the function. A docstring states intent; only tracing states behaviour.
        """
        def _spy(*, stage=llm_mod.STAGE_DEFAULT):
            raise RuntimeError("the settings store is unreachable")

        monkeypatch.setattr(llm_mod, "make_client", _spy)
        report = reader.read_sheet(_one_page_pdf(), set_id="t", sheet="GI/210")
        assert report.read is False
        assert "could not be set up" in report.problem
        assert "the settings store is unreachable" in report.problem
        assert "nothing on this drawing has been looked at" in report.problem

    def test_an_explicitly_passed_client_is_still_used_unchanged(self, monkeypatch):
        """A caller supplying its own client must not be re-routed behind its back."""
        def _boom(**_kw):
            raise AssertionError("read_sheet built a client when it was handed one")

        monkeypatch.setattr(llm_mod, "make_client", _boom)
        reader.read_sheet(_one_page_pdf(), set_id="t", sheet="GI/210", client=_StubClient())


class TestExtractionProviderReachesTheImageCall:
    """End to end through the real `resolve_provider` and the real `_route`."""

    @pytest.fixture(autouse=True)
    def _no_stored_settings(self, monkeypatch):
        # The live shape: `.env` set, `client_boq_settings` empty.
        monkeypatch.setattr(llm_mod, "current_settings", lambda: {
            "provider": "", "provider_ingest": "",
            "model_anthropic": "", "model_deepseek": "", "model_openai": ""})

    def test_an_image_call_goes_where_extraction_provider_says(self, monkeypatch):
        monkeypatch.setenv("EXTRACTION_PROVIDER", "openai")
        client = llm_mod.make_client(stage=llm_mod.STAGE_INGEST)
        assert client._route(images=["<base64>"]) == "openai"

    def test_the_default_stage_would_have_ignored_it(self, monkeypatch):
        """The defect, kept as a test so the two paths stay visibly different.

        Not a bug in `make_client` — a call site that did not say which stage it was.
        """
        monkeypatch.setenv("EXTRACTION_PROVIDER", "openai")
        client = llm_mod.make_client()
        assert client._route(images=["<base64>"]) == "anthropic"

    def test_a_text_only_provider_still_cannot_be_given_an_image(self, monkeypatch):
        """The one thing no setting may change. DeepSeek's chat API rejects `image_url`, so a
        drawing sent there would come back as a confident summary of nothing."""
        monkeypatch.setenv("EXTRACTION_PROVIDER", "deepseek")
        client = llm_mod.make_client(stage=llm_mod.STAGE_INGEST)
        assert client._provider_arg == "deepseek", "the setting was not applied at all"
        assert client._route(images=["<base64>"]) == "anthropic"
        # ...and the same client still honours the choice for a text-only call.
        assert client._route(images=None) == "deepseek"

    def test_an_unset_variable_is_not_a_choice(self, monkeypatch):
        monkeypatch.delenv("EXTRACTION_PROVIDER", raising=False)
        client = llm_mod.make_client(stage=llm_mod.STAGE_INGEST)
        assert client._provider_arg is None, (
            "an unset EXTRACTION_PROVIDER became an explicit provider, which would stop every "
            "text-only ingest call using the cheap default")


#: Stage constants a call under `ingest/` may name. RE-ANCHORED 2026-08-12, disclosed: this was
#: the single literal "STAGE_INGEST". `STAGE_DRAWING` is admitted because it RESOLVES THROUGH
#: ingest, and the first test below proves that of each one rather than taking it on trust — so
#: widening this list cannot become a way to smuggle in a stage that skips EXTRACTION_PROVIDER.
STAGES_THAT_REACH_INGEST = ("STAGE_INGEST", "STAGE_DRAWING")


class TestEveryIngestStageSaysSo:
    """The sweep. Two of four call sites were right and nothing made the other two follow."""

    def test_every_named_stage_actually_reaches_extraction_provider(self, monkeypatch):
        """The guard on the list above. A stage may only be admitted if it honours the setting."""
        monkeypatch.setattr(llm_mod, "current_settings", lambda: {
            "provider": "", "provider_ingest": "", "provider_drawing": "", "model_drawing": "",
            "model_anthropic": "", "model_deepseek": "", "model_openai": ""})
        monkeypatch.setenv("EXTRACTION_PROVIDER", "openai")
        for name in STAGES_THAT_REACH_INGEST:
            stage = getattr(llm_mod, name)
            assert llm_mod.make_client(stage=stage)._provider_arg == "openai", (
                f"{name} is on the allowed list but does not honour EXTRACTION_PROVIDER")

    @staticmethod
    def _calls(path: pathlib.Path) -> list[tuple[int, bool]]:
        """Every `make_client(...)` in a module: (line number, does it pass stage=STAGE_INGEST)."""
        tree = ast.parse(path.read_text())
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name != "make_client":
                continue
            passes = any(kw.arg == "stage"
                         and getattr(kw.value, "id", "") in STAGES_THAT_REACH_INGEST
                         for kw in node.keywords)
            found.append((node.lineno, passes))
        return found

    def test_every_call_under_ingest_names_the_ingest_stage(self):
        missing = []
        for path in sorted(INGEST.glob("*.py")):
            for line, passes in self._calls(path):
                if not passes:
                    missing.append(f"{path.name}:{line}")
        assert not missing, (
            "these build an LLM client inside the ingest package without saying so, so "
            "EXTRACTION_PROVIDER is ignored for them and an image call falls back to Anthropic: "
            + ", ".join(missing))

    def test_the_sweep_actually_finds_the_call_sites(self):
        """A sweep that matches nothing passes for the wrong reason."""
        total = sum(len(self._calls(p)) for p in INGEST.glob("*.py"))
        assert total >= 4, f"the AST walk found only {total} make_client call(s) under ingest/"


# ---------------------------------------------------------------------------


def _one_page_pdf() -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page(width=1191, height=842)
    data = doc.tobytes()
    doc.close()
    return data


class _StubClient:
    def complete_json(self, **_kw):
        return reader.RawSchedule()
