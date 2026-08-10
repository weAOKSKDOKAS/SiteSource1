"""BOQ — site photographs, read alongside the ground investigation reports.

Bucket: **AI observes → human decides → the decision becomes a condition.**

WHY PHOTOGRAPHS AT ALL. The tender package says where the holes are and how deep. It does not say
that the track stops 200 m short, that the slope above BH14 is a boulder field, or that the only
standing ground is somebody's vegetable plot. Those cost money — a Class B platform, a longer walk,
a wayleave — and the only record of them is what somebody saw on the site walk, which today lives
in a phone camera roll and reaches the price if they remember.

WHAT THIS MODULE PRODUCES. **Observations**, each naming the photograph it came from and quoting
what in the image it is about. Not classifications, not costs, not verdicts. The distinction is the
same one :mod:`client_boq.boq.access` draws and for the same reason: a machine looking at a picture
of a hillside cannot tell you it is Class B, and if it said so it would be believed.

WHAT AN OBSERVATION IS FOR. A person reads it, decides whether it matters, and turns the ones that
do into **conditions** — which then go through the ordinary propose-and-confirm path in
:mod:`client_boq.boq.conditions` and end up as a number somebody signed for. So the chain is:

    photograph → observation (evidence named) → a person keeps it → condition → proposal →
    a person confirms → the model moves

Six steps, and a human at two of them. Nothing shortcuts it.

THE DEGRADATION RULE, which this module has already been burned by elsewhere. `s02_interpret` once
returned its DEMO fixture *before* checking whether the part was readable, so a scanned page came
back with a confident summary of pages nobody had seen. So: **the images are counted and loaded
first, in every mode.** No photographs means no observations and a stated reason, fixture or not.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

DEMO_FIXTURE = "cases/client_boq/site_photo_read.json"

# What an observation is ABOUT. Declared so a screen can group them, and so that the list of things
# this module is looking for is written down rather than living in a prompt nobody reads.
TOPIC_ACCESS = "access"             # how a rig gets there, or does not
TOPIC_GROUND = "ground"             # what is underfoot: rock outcrop, fill, slope, water
TOPIC_OBSTRUCTION = "obstruction"   # services, structures, crops, trees, boundaries
TOPIC_WORKING_SPACE = "space"       # is there room to stand a rig and lay out rods
TOPIC_HAZARD = "hazard"             # traffic, overhead lines, unstable faces
TOPIC_OTHER = "other"
TOPICS = (TOPIC_ACCESS, TOPIC_GROUND, TOPIC_OBSTRUCTION, TOPIC_WORKING_SPACE, TOPIC_HAZARD,
          TOPIC_OTHER)

SYSTEM = """You look at photographs of a ground investigation site and report WHAT YOU CAN SEE.

You will be given one or more site photographs, and text from the ground investigation reports and
the station schedule for the same site.

Report observations. An observation is a thing visible in a photograph that could plausibly affect
how a drilling rig reaches or stands at a location, or what it will meet in the ground.

Answer with JSON only:
{"observations": [
   {"topic": "access"|"ground"|"obstruction"|"space"|"hazard"|"other",
    "what_i_see": "<what is visibly in the image, in plain words>",
    "why_it_might_matter": "<the cost or programme consequence, stated as a possibility>",
    "photo_refs": ["<the filename or label of each photo this comes from>"],
    "corroboration": "<what in the supplied report text agrees or disagrees, or '' if nothing>",
    "confidence": "high"|"medium"|"low"}],
 "could_not_see": "<what the photographs do not show that a person would want, or ''>"}

RULES YOU MUST NOT BREAK:
1. Never state an access class. A, B and C are a person's decision and you do not have the
   information to make it. If a photograph suggests difficulty, describe the difficulty.
2. Never state a cost, a duration, a quantity or a rate. You have no basis for one.
3. `what_i_see` must be about the IMAGE. If you are inferring rather than seeing, say so in
   `why_it_might_matter` and set confidence low.
4. Every observation names its photographs. An observation you cannot attribute is not one.
5. If the photographs do not support an observation, return fewer. An empty list is a correct
   answer and is better than a plausible one."""


class Observation(BaseModel):
    """One thing visible in a photograph, and why it might cost money.

    NO `access_class`, NO `cost`, NO `status`. The model that fills this in structurally cannot
    classify a hole, price anything, or record that a person agreed with it — the same shape the
    access board and the departure proposals keep.
    """

    topic: str = TOPIC_OTHER
    what_i_see: str = ""
    why_it_might_matter: str = ""
    photo_refs: list[str] = Field(default_factory=list)
    corroboration: str = ""
    confidence: str = "low"


class PhotoRead(BaseModel):
    """What one reading pass produced, and what it could not do."""

    observations: list[Observation] = Field(default_factory=list)
    could_not_see: str = ""
    photos_read: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


def validate(raw: dict, *, available: list[str]) -> PhotoRead:
    """Turn a reading into observations, dropping anything the model was not entitled to say.

    Every drop is REPORTED. An observation that quietly disappeared would look identical to one
    that was never made, and the difference matters when the subject is what somebody saw on site.
    """
    known = {name.lower(): name for name in available}
    out = PhotoRead(photos_read=list(available), could_not_see=str(raw.get("could_not_see") or ""))

    for item in raw.get("observations") or []:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or TOPIC_OTHER).lower()
        if topic not in TOPICS:
            topic = TOPIC_OTHER
        refs = [known[str(r).lower()] for r in (item.get("photo_refs") or [])
                if str(r).lower() in known]
        seen = str(item.get("what_i_see") or "").strip()
        if not seen:
            out.problems.append("an observation arrived with nothing said about the image; dropped")
            continue
        if not refs:
            # Rule 4. An observation nobody can go back and check against a photograph is exactly
            # the kind of confident sentence this product exists to keep out of an estimate.
            out.problems.append(
                f"DROPPED an observation that named no photograph in this set "
                f"({seen[:60]}…) — an observation you cannot attribute is not one")
            continue
        confidence = str(item.get("confidence") or "low").lower()
        out.observations.append(Observation(
            topic=topic, what_i_see=seen,
            why_it_might_matter=str(item.get("why_it_might_matter") or "").strip(),
            photo_refs=refs, corroboration=str(item.get("corroboration") or "").strip(),
            confidence=confidence if confidence in {"high", "medium", "low"} else "low"))
    return out


def as_condition_text(observation: Observation) -> str:
    """The sentence a kept observation becomes, when a person sends it to the register.

    Written so the condition reads as a fact about the site with its evidence attached, because
    that is what it is — and because the mapping call downstream is better at a plain statement
    than at a paragraph of hedging.
    """
    parts = [observation.what_i_see.rstrip(".") + "."]
    if observation.why_it_might_matter:
        parts.append(observation.why_it_might_matter.rstrip(".") + ".")
    parts.append(f"[Seen in {', '.join(observation.photo_refs)}"
                 + (f"; {observation.corroboration}" if observation.corroboration else "")
                 + "]")
    return " ".join(parts)


def prompt_for(*, stations: str = "", reports: str = "", photos: Optional[list[str]] = None) -> str:
    """The text half of the call. The images travel separately."""
    lines = ["THE PHOTOGRAPHS, in the order they are attached:"]
    lines += [f"  {n + 1}. {name}" for n, name in enumerate(photos or [])]
    if stations:
        lines += ["", "THE STATION SCHEDULE FOR THIS SITE:", stations]
    if reports:
        lines += ["", "FROM THE GROUND INVESTIGATION REPORTS:", reports]
    lines += ["", "Report what you can see. Name the photograph for every observation."]
    return "\n".join(lines)
