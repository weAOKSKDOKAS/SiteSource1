"""A list where a string was asked for must not throw away the other fields.

THE SAME DEFECT, THREE TIMES, AND THE THIRD ONE WAS MINE.

1. **2026-08-11 — a null.** GI/210 has no TERMINATION column, the reader correctly wrote
   ``"termination": null``, and pydantic discarded **47 boreholes and 21 trial pits** with their
   ground levels and rock splits intact in the response. Fixed by ``NullTolerant``; trap 12.
2. **The first live GPT run — a list.** ``PartContext.notes`` is ``str`` while every other prose
   field on that card is ``list[str]``, so the model picked the neighbouring shape. **93 of 203
   parts** were stored as "not readable", including a 65-page conditions of contract with a
   perfect text layer, plus 120 retries. Fixed with a field validator on that one type.
3. **2026-08-18 — a list again, somewhere else.** The owner switched provider to OpenAI and the
   brain died on::

       1 validation error for RawBriefing
       cannot_assess  Input should be a valid string
       [input_value=['A bid submission deadline ... in the current set [register:14].']]

   The model had read the whole tender. The understanding, the disagreements and every proposed
   action went in the bin because one field arrived wrapped in brackets.

WHY IT KEPT HAPPENING. Fix 2 was applied to the type that failed, not to the class of failure, so
the protection covered exactly one model out of thirty. And the null sweep's own coverage list is
hand-written, so the brain's types — added later — were never in it. Two half-measures that each
looked complete.

So the repair is now on ``NullTolerant`` itself, a string field joins a list with a space (the
separator ``PartContext`` already used, kept so there is one convention and not two), a list field
wraps a bare string, and **the type list below is DERIVED** rather than typed out — a new
model-facing type is swept the day it is written, without anybody remembering to add it.

WHAT STILL REFUSES, on purpose. Numbers and booleans. Turning ``["3"]`` into 3 is a guess about
which element was meant, and this codebase's rule is that a repair may not become a claim.

AND THE PROMPT THAT CAUSED IT. `SYNTH_SYSTEM` was edited on 2026-08-18 to print its JSON keys —
a good change — and printed ``"cannot_assess": ["…"]`` for a field declared ``str``. The model did
exactly as instructed. `TestThePromptAndTheTypeAgree` pins that pair, because a prompt is a
contract with the same standing as the annotation and nothing else checks it.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

from client_boq import brain
from client_boq.models import NullTolerant

#: Numeric and boolean fields that refuse a wrong shape on purpose — the same list the null sweep
#: keeps, and for the same reason: a blank that would be a claim is not tolerable.
ALLOWED_TO_REFUSE = {
    ("PartSpec", "n"), ("PartSpec", "start"), ("PartSpec", "end"), ("PartSpec", "rev"),
    ("PartSpec", "scanned"), ("PartContext", "readable"),
}


def _every_model_facing_type() -> list[type[BaseModel]]:
    """DERIVED, not listed. The hand-written list in the null sweep is what let the brain's own
    types go unswept for the whole of their existence."""
    import client_boq

    for module in pkgutil.walk_packages(client_boq.__path__, "client_boq."):
        if ".tests" in module.name:
            continue
        try:
            importlib.import_module(module.name)
        except Exception:                    # noqa: BLE001 — an optional dep is not the subject
            continue

    def subclasses(cls) -> set:
        found = set()
        for sub in cls.__subclasses__():
            found.add(sub)
            found |= subclasses(sub)
        return found

    return sorted(subclasses(NullTolerant), key=lambda c: c.__name__)


@pytest.fixture(scope="module")
def types() -> list:
    found = _every_model_facing_type()
    assert len(found) >= 25, f"only {len(found)} types discovered — has the import sweep broken?"
    return found


class TestTheDefectThatWasMeasured:
    def test_the_exact_payload_that_killed_the_briefing_now_survives(self):
        """Verbatim from the owner's error, including the sibling fields that were being lost."""
        result = brain.RawBriefing.model_validate({
            "understanding": "the tender is at the price",
            "disagreements": ["the bill counts 91, the schedule counts 90"],
            "cannot_assess": [
                "A bid submission deadline could not be found in the current set [register:14]."],
            "proposed_actions": [{"action_id": "decide_bid", "reasoning": "the terms are read"}],
        })
        assert result.cannot_assess.startswith("A bid submission deadline")
        assert result.understanding == "the tender is at the price", "the sibling survived"
        assert len(result.proposed_actions) == 1, "and so did the actions, which are the point"

    def test_the_part_card_repair_still_behaves_exactly_as_it_did(self):
        """93 parts were bought with that fix; the general rule must not change its answer."""
        from client_boq.models import PartContext

        card = PartContext(summary=["The Additional Conditions of Contract.",
                                    "It amends the NEC ECC HK Edition."])
        assert card.summary == ("The Additional Conditions of Contract. "
                                "It amends the NEC ECC HK Edition.")
        assert card.readable is True

    def test_a_bare_string_where_a_list_was_asked_for_is_wrapped(self):
        """The mirror case, and just as ordinary — one item does not stop being a list."""
        result = brain.RawBriefing.model_validate({"disagreements": "only one thing disagrees"})
        assert result.disagreements == ["only one thing disagrees"]

    def test_an_empty_string_for_a_list_is_an_empty_list_not_a_blank_item(self):
        assert brain.RawBriefing.model_validate({"disagreements": ""}).disagreements == []


class TestNoTypeAnywhereDiscardsAPayloadOverAShape:
    def test_no_text_field_rejects_a_list(self, types):
        offenders = []
        for model in types:
            for name, info in model.model_fields.items():
                if info.annotation is not str:
                    continue
                try:
                    model.model_validate({name: ["a sentence.", "and another."]})
                except Exception:            # noqa: BLE001 — collecting, not asserting
                    offenders.append(f"{model.__name__}.{name}")
        assert not offenders, (
            "these fields throw away every sibling when a model wraps one answer in brackets: "
            + ", ".join(sorted(offenders)))

    def test_no_list_field_rejects_a_bare_string(self, types):
        offenders = []
        for model in types:
            for name, info in model.model_fields.items():
                if typing.get_origin(info.annotation) is not list:
                    continue
                args = typing.get_args(info.annotation)
                # A list of OBJECTS is excluded, and the distinction is the whole rule: wrapping a
                # bare string into `list[str]` loses nothing, because one item is still a list.
                # Wrapping it into `list[dict]` would have to invent the keys, and an invention is
                # a claim. `_RawPhotoRead.observations` is `list[dict]` and correctly refuses.
                if args and isinstance(args[0], type) and issubclass(args[0], (BaseModel, dict)):
                    continue
                try:
                    model.model_validate({name: "one item"})
                except Exception:            # noqa: BLE001
                    offenders.append(f"{model.__name__}.{name}")
        assert not offenders, ", ".join(sorted(offenders))

    def test_numbers_and_booleans_still_refuse_because_a_repair_may_not_become_a_claim(self, types):
        """The boundary. Joining text loses nothing; picking an element out of `["3"]` is a guess,
        and this codebase does not let a guess wear the clothes of a reading."""
        from client_boq.models import PartSpec

        for value in ([3], ["3"], [True]):
            with pytest.raises(Exception):
                PartSpec.model_validate({"n": value, "start": 1, "end": 2})

    def test_the_exemptions_are_still_earning_their_place(self, types):
        """An allowance nobody needs is an allowance that hides the next real one."""
        by_name = {m.__name__: m for m in types}
        for cls_name, field in ALLOWED_TO_REFUSE:
            model = by_name.get(cls_name)
            if model is None:
                continue
            with pytest.raises(Exception):
                model.model_validate({field: ["x"]})

    def test_it_reports_what_it_swept(self, types, capsys):
        with capsys.disabled():
            print(f"\n  shape sweep: {len(types)} model-facing types, derived from "
                  f"NullTolerant.__subclasses__ rather than listed")


class TestThePromptAndTheTypeAgree:
    """The half a runtime coercion cannot fix: a prompt that asks for the wrong shape.

    `cannot_assess` was declared `str` while the prompt printed `["…"]` beside it, so the model
    was INSTRUCTED to produce the payload that broke it. The coercion now saves that briefing, but
    an instruction and an annotation that disagree is a defect in its own right — it wastes the
    model's compliance and it will read as a bug to whoever meets it next.
    """

    SOURCE = Path(brain.__file__).read_text(encoding="utf-8")

    def _declared(self, prompt: str) -> dict[str, str]:
        """Every key the prompt prints, and whether its example is an array or a scalar."""
        return {m.group(1): ("list" if m.group(2) == "[" else "str")
                for m in re.finditer(r'"(\w+)":\s*(\[|")', prompt)}

    @pytest.mark.parametrize("prompt_name,model", [
        ("SYNTH_SYSTEM", brain.RawBriefing),
        ("READ_SYSTEM", brain.RawFindings),
    ])
    def test_every_key_the_prompt_prints_matches_the_field_it_is_parsed_into(
            self, prompt_name, model):
        prompt = getattr(brain, prompt_name)
        for key, shape in self._declared(prompt).items():
            info = model.model_fields.get(key)
            if info is None:
                continue                     # a key inside a nested example, checked by its own type
            actual = "list" if typing.get_origin(info.annotation) is list else (
                "str" if info.annotation is str else "other")
            if actual == "other":
                continue
            assert shape == actual, (
                f"{prompt_name} shows {key!r} as a {shape} and {model.__name__}.{key} is a "
                f"{actual}. The model will do as it is told and the payload will be refused — "
                f"which is exactly how the 2026-08-18 briefing was lost.")

    def test_cannot_assess_specifically(self):
        """Named, because a parametrised sweep that stopped matching would pass quietly."""
        assert '"cannot_assess": "' in brain.SYNTH_SYSTEM, "must be shown as prose, not an array"
        assert brain.RawBriefing.model_fields["cannot_assess"].annotation is str
