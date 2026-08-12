"""BOQ — a condition somebody wrote down, and the knob it maps onto.

Bucket: **AI proposes → human confirms → deterministic write.** Three steps, and the boundaries
between them are the whole design.

THE PROBLEM. The engine's knobs are the ones the engine has. Real tenders arrive with conditions it
has never heard of — *"no night work through the village section"*, *"the client supplies the
platform at CH2+400"*, *"two of the holes are over water"*. Before this there was nowhere to put
one. It lived in somebody's notebook and reached the price only if they remembered on the right
afternoon.

WHAT THIS MODULE DOES. It takes the sentence, and proposes **which existing input it moves and by
how much**, with its reasoning and what it read to get there. That is all. It does not write the
model, it does not set a status, and it cannot invent a knob: :func:`propose` is handed the model's
own declarations and a proposal naming anything else is refused before it reaches a person, because
a plausible mapping onto a field that does not exist is worse than no mapping at all.

WHAT WRITES THE MODEL. A human confirming, in the router, through the same copy-on-write path every
other model edit uses. There is no second write path and no number that lives only on a register.

WHY THE PROPOSAL CARRIES ITS OWN REFUSAL. ``ConditionProposal.path`` may be empty, and often should
be. *"The client wants the works finished before Chinese New Year"* is a real condition with no
single knob behind it. The honest answer is "I cannot map this — here is why", and the row stays on
the register unmapped and visible. A condition nobody priced is exactly what loses money after
award; a condition mapped to the wrong knob loses more, quietly.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.model import INPUT_SPECS, CostingModel
from client_boq.models import NullTolerant

DEMO_FIXTURE = "cases/client_boq/condition_mapping.json"

SYSTEM = """You map a tender condition onto ONE existing input of a construction costing model.

You are given the model's inputs, each with its key, what it means, its unit and its current value.
You are given one condition somebody wrote down about this tender.

Answer with JSON only:
{"path": "inputs.<key>", "value": <number>, "basis": "<why, in one or two plain sentences>",
 "confidence": "high"|"medium"|"low", "cannot_map": "<empty, or why no single input fits>"}

RULES YOU MUST NOT BREAK:
1. `path` must name an input from the list, or be "". Never invent a key.
2. If no single input honestly carries this condition, set `path` to "" and say why in
   `cannot_map`. That is a correct answer, not a failure. Many real conditions have no knob.
3. `value` is the NEW value for that input, in the same unit as the current one. Never a delta.
4. `basis` states the reasoning a person will check. Do not assert a fact you were not given —
   if the size of the effect is a judgement, say that it is and say what you based it on.
5. You are proposing. A person confirms or rejects. Never write as if the change is made."""


class RawConditionMapping(NullTolerant):
    """EXACTLY what the model is asked for, and nothing else.

    A separate type from :class:`ConditionProposal` on purpose. That one carries ``checked`` — what
    the proposal was validated against — and a target model the LLM fills would let it write its
    own audit trail. The fields it may set are the fields it is asked for.
    """

    path: str = ""
    value: Optional[float] = None
    basis: str = ""
    confidence: str = "low"
    cannot_map: str = ""


class ConditionProposal(BaseModel):
    """What the model thinks a condition moves. A PROPOSAL — see the module docstring.

    There is deliberately no `status` field and no `applied` field. This object structurally cannot
    say that anything has been decided or written, which is the same guard `DepartureProposal` and
    `PlannedSplit` carry: a stage that has no field for a verdict cannot write one.
    """

    path: str = ""                  # "inputs.<key>", or "" for an honest refusal
    value: Optional[float] = None
    basis: str = ""
    confidence: str = "low"
    cannot_map: str = ""
    #: What the proposal was checked against before it was shown to anybody.
    checked: list[str] = Field(default_factory=list)

    @property
    def maps(self) -> bool:
        return bool(self.path) and self.value is not None


def editable_paths(model: CostingModel) -> dict[str, str]:
    """Every path a condition may legally be mapped to → how the input is described.

    Only the declared scalars. The spread's rates and multipliers are real numbers a person edits
    on the costing screen, but a condition that means "the drill rig costs more" is a rate change
    somebody should make deliberately with the rate in front of them — not a number a sentence
    talked a model into.
    """
    return {
        f"inputs.{spec.key}": (
            f"{spec.label} ({spec.unit or 'ratio'}) — currently "
            f"{model.value(spec.key):g}{'  [a fraction: 0.10 means 10%]' if spec.percent else ''}"
            f"{'. ' + spec.note if spec.note else ''}")
        for spec in INPUT_SPECS
    }


def prompt_for(condition: str, model: CostingModel, *, context: str = "") -> str:
    """The user half of the call. The model's OWN inputs, never a hand-typed list."""
    lines = ["THE MODEL'S INPUTS:"]
    lines += [f"  {path} — {described}" for path, described in editable_paths(model).items()]
    if context:
        lines += ["", "WHAT IS KNOWN ABOUT THIS TENDER:", context]
    lines += ["", "THE CONDITION:", condition]
    return "\n".join(lines)


def validate(raw: dict, model: CostingModel) -> ConditionProposal:
    """Turn a model's answer into a proposal, refusing anything it was not allowed to say.

    Every refusal is RECORDED on the proposal rather than raised, because the caller's job is to
    show a person what happened. A proposal that quietly became "cannot map" would look identical
    to the model honestly declining, and those are different events.
    """
    allowed = editable_paths(model)
    checked: list[str] = []
    path = str(raw.get("path") or "").strip()
    cannot = str(raw.get("cannot_map") or "").strip()

    if path and path not in allowed:
        checked.append(
            f"REFUSED: the proposal named {path!r}, which is not an input of this model. A "
            f"plausible mapping onto a field that does not exist is worse than no mapping.")
        path, cannot = "", cannot or f"the model proposed {path!r}, which does not exist"

    value: Optional[float] = None
    if path:
        try:
            value = float(raw.get("value"))
        except (TypeError, ValueError):
            checked.append(
                "REFUSED: a path was proposed with no usable number, so there is nothing to "
                "confirm. Treated as unmapped.")
            path, cannot = "", cannot or "no numeric value was proposed for the input"

    confidence = str(raw.get("confidence") or "low").lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    if path:
        checked.append(f"{path} is a declared input of the model in force")
        current = model.value(path.removeprefix("inputs."))
        if value is not None and current and abs(value - current) / abs(current) > 2.0:
            checked.append(
                f"NOTE: {value:g} is more than three times the current {current:g}. Not refused — "
                f"a condition really can triple a number — but worth reading twice.")

    return ConditionProposal(
        path=path, value=value, basis=str(raw.get("basis") or "").strip(),
        confidence=confidence,
        cannot_map=cannot or ("" if path else "no single input carries this condition"),
        checked=checked)
