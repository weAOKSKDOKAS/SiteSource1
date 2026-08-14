"""BOQ — how you actually get to one hole. Described by a model, measured by the engine.

Bucket: **AI proposes → a person reads it → the person still decides.** Nothing here is confirmed
into anything; it is a note beside a decision, in the same family as :mod:`client_boq.boq.access`.

WHAT IT IS FOR. The map shows a hole and the nearest mapped road, and the gap between those two
facts is where the money is. Forty metres from a track can be a two-minute walk or a cliff; a hole
that looks roadside can sit behind a stream with no crossing for a kilometre. An estimator classing
ninety-nine holes is doing that reasoning ninety-nine times from the same evidence, and writing the
reasoning down beside each one is exactly the kind of work worth having drafted.

THE SPLIT, AND IT IS THE WHOLE DESIGN.

* **The engine measures.** Distance to the nearest mapped road, which road it is, its OSM id and
  its highway class, the named roads within reach, the bearing. Arithmetic, checkable, and the
  same for two people. See :mod:`client_boq.boq.roads`.
* **The model describes.** Which road to come in on, where to leave the vehicle, what the last
  stretch looks like on the imagery, and — most valuable of all — what it is NOT sure about.
* **The person decides.** The access class, the transport mode, and every number.

SO THE MODEL IS NEVER ASKED FOR A NUMBER OR A CLASS. :class:`RawApproach` has no field for either,
which is the same structural guard :class:`DepartureProposal` and :class:`RawConditionMapping`
carry: a stage with nowhere to write a verdict cannot write one, whatever a prompt says or a
future edit to a prompt might say. The metres on the response come from the measurement and are
attached afterwards, so a model that writes "about 300 m" in its prose cannot contradict the
number on screen — the number was never its to give.

AND IT SAYS WHAT IT CANNOT SEE. ``uncertainties`` is not a politeness field. A route description
written from a road network and a coordinate is exactly the kind of confident-sounding text that
gets believed, and the things it cannot know — a locked gate, a collapsed track, whose land it
crosses — are precisely the things that decide the class. A note with an empty uncertainty list
about a hillside hole is a note nobody should trust.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.models import NullTolerant

DEMO_FIXTURE = "cases/client_boq/approach_note.json"

#: How far around the hole to hand the model road context. Wide enough that the approach is
#: usually in the window, narrow enough that a hundred ways do not drown the one that matters.
CONTEXT_RADIUS_M = 900.0

#: How many roads to name in the prompt. The nearest is always first.
CONTEXT_ROADS = 12

SYSTEM = """You describe how a drilling crew would reach ONE borehole, from mapped road data.

You are given the hole's position, the roads near it (each with its OpenStreetMap id, name,
highway class, and the measured straight-line distance from the hole to that road), and whatever
the site schedule records about the hole.

Answer with JSON only:
{"summary": "<one sentence: how you would get there>",
 "approach_road": "<the name or OSM id of the road you would come in on, or empty>",
 "last_stretch": "<what happens after the vehicle stops, in one or two sentences>",
 "steps": ["<each leg of the route, in order>"],
 "uncertainties": ["<each thing this data cannot tell you that would change the answer>"]}

RULES YOU MUST NOT BREAK:
1. NEVER give a distance, a duration, a cost, or an access class. Not in any field. Those are
   measured or decided elsewhere and a number from you would compete with a real one.
2. Only name a road that appears in the data you were given. Never invent a road, a gate, a
   bridge, a track or a village name.
3. `uncertainties` must not be empty. Straight-line distance is not walkable distance; mapped
   roads are not all roads; nothing here tells you about gradient, vegetation, water crossings,
   locked gates, private land or whether a track is passable. Say which of these actually bear on
   THIS hole rather than listing all of them.
4. If the data does not support a route at all, say so in `summary` and leave `steps` empty. That
   is a correct answer.
5. You are describing evidence for somebody else's decision. Never write as if the class, the
   transport method or the price follows from what you said."""


class RawApproach(NullTolerant):
    """EXACTLY what the model is asked for.

    No distance, no duration, no cost, no access class — not merely unrequested but structurally
    absent, so no prompt change can start collecting one. The measured figures are attached to
    :class:`Approach` by the engine after this comes back.
    """

    summary: str = ""
    approach_road: str = ""
    last_stretch: str = ""
    steps: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class RoadContext(BaseModel):
    """One road near the hole, as the engine measured it."""

    way_id: int = 0
    name: str = ""
    highway: str = ""
    metres: float = 0.0


class Approach(BaseModel):
    """A drafted route note, and the measurements it was drafted from.

    The two are kept apart on the object for the same reason they are kept apart in the pipeline:
    a reader must be able to tell which part is arithmetic anybody can check and which part is a
    description somebody should verify on the ground.
    """

    station: str = ""
    summary: str = ""
    approach_road: str = ""
    last_stretch: str = ""
    steps: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    # --- the engine's half: measured, never the model's ---
    #: Straight line to the nearest mapped road. NOT walking distance, and labelled so everywhere.
    nearest_road_m: Optional[float] = None
    nearest_road_name: str = ""
    nearest_road_way_id: int = 0
    nearest_road_highway: str = ""
    roads_considered: list[RoadContext] = Field(default_factory=list)

    #: Empty when it ran. Otherwise why it did not — no schedule, no coordinates, demo mode, or a
    #: road read that failed. Never confused with "there is no route".
    waiting_on: str = ""
    #: What was stripped before this was shown, and why. Visible rather than silently dropped.
    checked: list[str] = Field(default_factory=list)


def context_for(station: str, roads: list, limit: int = CONTEXT_ROADS,
                radius_m: float = CONTEXT_RADIUS_M) -> list[RoadContext]:
    """The roads worth telling the model about, nearest first. Pure.

    ``roads`` is a list of :class:`client_boq.boq.roads.NearestRoad`-shaped rows for THIS hole.
    Filtering here rather than in the prompt keeps what the model saw reproducible, and it is what
    ``roads_considered`` reports back so the note can be read against its own evidence.
    """
    near = [r for r in roads if r.metres <= radius_m]
    near.sort(key=lambda r: r.metres)
    return [RoadContext(way_id=r.way_id, name=r.name, highway=r.highway,
                        metres=round(r.metres, 1)) for r in near[:limit]]


def prompt_for(station: str, roads: list[RoadContext], *, hole: str = "") -> str:
    """The user half of the call. The measured road list, never a hand-typed one."""
    if roads:
        lines = "\n".join(
            f"- {r.name or '(unnamed)'} · OSM way {r.way_id} · {r.highway or 'road'} · "
            f"{r.metres:g} m from the hole in a straight line"
            for r in roads)
    else:
        lines = "- (no mapped road within reach of this hole)"
    tail = f"\n\nWHAT THE SCHEDULE SAYS ABOUT THIS HOLE:\n{hole}" if hole else ""
    return (f"HOLE: {station}\n\nMAPPED ROADS NEAR IT, nearest first:\n{lines}{tail}\n\n"
            f"Describe how a drilling crew would reach {station}.")


def validate(raw: RawApproach, station: str, roads: list[RoadContext]) -> Approach:
    """Attach the measurements and strip anything the model was not entitled to say.

    TWO THINGS ARE ENFORCED HERE rather than trusted to the prompt.

    A road the model named that is not in the data it was given is dropped from
    ``approach_road`` — an invented road is the single most believable wrong answer this call can
    produce, because it reads exactly like local knowledge.

    An empty ``uncertainties`` is replaced with a statement that the model offered none. Rule 3
    says it must not be empty; a model that returns nothing there has not become certain, and
    printing an empty list would show as "nothing to worry about".
    """
    known_names = {r.name.strip().lower() for r in roads if r.name.strip()}
    known_ids = {str(r.way_id) for r in roads}
    checked: list[str] = []

    road = (raw.approach_road or "").strip()
    if road:
        token = road.lower()
        if not (token in known_names or any(i in road for i in known_ids)
                or any(n and n in token for n in known_names)):
            checked.append(
                f"REFUSED an approach road the road data does not contain: {road!r}. A road name "
                f"that was not measured reads as local knowledge and is not.")
            road = ""

    uncertainties = [u.strip() for u in raw.uncertainties if u.strip()]
    if not uncertainties:
        uncertainties = ["The note came back with nothing it was unsure of, which for a route "
                         "read off a map is itself the thing to be unsure about — straight-line "
                         "distance is not a walk, and gradient, vegetation, water crossings, "
                         "gates and land ownership are not in this data at all."]
        checked.append("SUPPLIED the uncertainty line the model left empty.")

    nearest = roads[0] if roads else None
    return Approach(
        station=station,
        summary=raw.summary.strip(),
        approach_road=road,
        last_stretch=raw.last_stretch.strip(),
        steps=[s.strip() for s in raw.steps if s.strip()],
        uncertainties=uncertainties,
        nearest_road_m=nearest.metres if nearest else None,
        nearest_road_name=nearest.name if nearest else "",
        nearest_road_way_id=nearest.way_id if nearest else 0,
        nearest_road_highway=nearest.highway if nearest else "",
        roads_considered=list(roads),
        checked=checked,
    )
