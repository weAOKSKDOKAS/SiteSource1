"""BOQ — asking a question about one tender, and getting an answer that can be checked.

Bucket: **AI reads, cites, and proposes. It never computes and it never decides.**

THE PROBLEM A CHAT BOX CREATES. The moment there is a text box, somebody will type *"what should we
price the rock drilling at?"* — and a language model will answer, fluently, with a number it made
up. That number would be wrong in a way nothing on the screen contradicts, and it would arrive in
the same typeface as the ones the engine computed. Everything else in this product is built to keep
model-authored numbers out of the estimate; a chat box is the front door.

SO THE ANSWER IS CONSTRAINED BY ITS SHAPE, not by asking nicely. :class:`Answer` has:

* ``answer`` — prose, which may quote the FIGURES IT WAS GIVEN and may not invent new ones;
* ``citations`` — every claim's source, validated against the ground actually supplied. A citation
  naming something that was not in the context is stripped and the strip is reported;
* ``computed_by_the_engine`` — the figures quoted, each one lifted from the context by key rather
  than retyped, so a reader can see which numbers in the prose came from the model in force;
* ``proposes`` — the ONE thing it may suggest doing, and only as a condition for the ordinary
  propose-and-confirm path.

There is no field for a rate, a duration, a class, or a verdict. There is nowhere for the model to
put an answer of that kind, which is a stronger guarantee than a paragraph of instructions.

WHAT IT IS GROUNDED IN. The tender's own documents (the review register's clauses and their
citations), the costing model in force and what it derived, the access board's location evidence,
and any site photographs that have been read. If a question cannot be answered from those, the
honest answer is that it cannot — and :attr:`Answer.not_grounded_in_anything` says so rather than
the model reaching for training data.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

DEMO_FIXTURE = "cases/client_boq/tender_answer.json"

SYSTEM = """You answer a question about ONE construction tender, using ONLY the ground supplied.

Answer with JSON only:
{"answer": "<plain prose, 1-4 sentences>",
 "citations": [{"source": "<the exact source label from the ground below>",
                "quote": "<the words you are relying on>"}],
 "figures_used": ["<the exact key of each supplied figure you quoted>"],
 "proposes": "<a condition to record about this tender, or ''>",
 "cannot_answer": "<why the ground does not answer this, or ''>"}

RULES YOU MUST NOT BREAK:
1. NEVER state a rate, a price, a duration, a quantity or an access class that is not already in
   the ground below. You have no basis for one and the estimate will not accept it.
2. You may quote a figure that IS supplied. When you do, put its key in `figures_used` so the
   reader can see which number you meant.
3. Every claim about the tender documents carries a citation naming a source from the ground.
   A citation you cannot make is a claim you should not state.
4. If the ground does not answer the question, say so in `cannot_answer` and leave `answer` short.
   That is a correct response. Reaching for general knowledge about construction is not.
5. `proposes` is for a condition somebody should record about this job. It is a suggestion for a
   person to accept or ignore — never write as though it has been recorded."""


class Citation(BaseModel):
    """Where a claim came from. Validated against the ground actually supplied."""

    source: str = ""
    quote: str = ""


class Answer(BaseModel):
    """A grounded answer. Deliberately has no field for a rate, a verdict or a decision."""

    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    #: Keys of the supplied figures the prose quoted, so a reader can see which numbers are the
    #: engine's. A key that was never supplied is stripped — see :func:`validate`.
    figures_used: list[str] = Field(default_factory=list)
    #: A condition to record, for the ordinary propose-and-confirm path. A SUGGESTION.
    proposes: str = ""
    cannot_answer: str = ""
    #: What was dropped on the way through, and why. Never silent.
    stripped: list[str] = Field(default_factory=list)

    @property
    def not_grounded_in_anything(self) -> bool:
        return bool(self.cannot_answer) or not self.citations


class RawAnswer(BaseModel):
    """Exactly the fields the model is asked for — it does not get to write `stripped`."""

    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    figures_used: list[str] = Field(default_factory=list)
    proposes: str = ""
    cannot_answer: str = ""


class Ground(BaseModel):
    """Everything the answer is allowed to rest on, assembled deterministically."""

    #: label → the text under it. The label is what a citation must name.
    sources: dict[str, str] = Field(default_factory=dict)
    #: key → (what it is, the value). Computed by the engine; the model may quote, never derive.
    figures: dict[str, str] = Field(default_factory=dict)

    def as_prompt(self) -> str:
        lines: list[str] = []
        if self.figures:
            lines.append("FIGURES THE ENGINE COMPUTED (quote these; never invent another):")
            lines += [f"  [{key}] {described}" for key, described in self.figures.items()]
            lines.append("")
        lines.append("THE GROUND. Cite by the source label in brackets:")
        for label, text in self.sources.items():
            body = text if len(text) <= 2000 else text[:2000] + " …"
            lines.append(f"  [{label}] {body}")
        return "\n".join(lines)


def validate(raw: dict, ground: Ground) -> Answer:
    """Strip anything the answer was not entitled to say, and report every strip.

    A citation naming a source that was not supplied is the failure mode that matters: it reads
    exactly like a real one, and it is how a model's own knowledge gets laundered into a tender
    file. It goes, and the reader is told it went.
    """
    known_sources = {label.lower(): label for label in ground.sources}
    out = Answer(
        answer=str(raw.get("answer") or "").strip(),
        proposes=str(raw.get("proposes") or "").strip(),
        cannot_answer=str(raw.get("cannot_answer") or "").strip(),
    )

    for item in raw.get("citations") or []:
        source = str((item or {}).get("source") or "").strip()
        if source.lower() not in known_sources:
            out.stripped.append(
                f"STRIPPED a citation to {source!r}, which is not one of the sources this answer "
                f"was given. A citation to something that was never supplied reads exactly like a "
                f"real one.")
            continue
        out.citations.append(Citation(source=known_sources[source.lower()],
                                      quote=str((item or {}).get("quote") or "").strip()))

    for key in raw.get("figures_used") or []:
        name = str(key).strip()
        if name in ground.figures:
            out.figures_used.append(name)
        else:
            out.stripped.append(
                f"STRIPPED a reference to figure {name!r}, which the engine did not compute. Any "
                f"number in the prose that came from it is the model's, not this tender's.")

    if not out.citations and not out.cannot_answer:
        out.cannot_answer = ("nothing in this answer is cited to the tender, so treat the prose as "
                             "a suggestion rather than a finding")
    return out
