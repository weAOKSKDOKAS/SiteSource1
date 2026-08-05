"""BOQ — the output book: what your company knows, as distinct from what this job needs.

Bucket: **Human**. Nothing here is a fact about a tender and nothing here is derived. It is the set of
norms a company argues about **once** rather than at every bid — how fast a crew drills, how long a
spread is on site either side of the drilling, what share of a project manager one job consumes.

WHY IT IS A SEPARATE THING FROM A TENDER
----------------------------------------
The same division the rate book already draws. ``client_boq_rates`` holds what a drilling crew costs
per hour; it does not hold how many hours *this* hole takes. The book here holds *20 m a day in soil*;
it does not hold that the Saddle Pass group manages 9. A tender **inherits the book and may override
any line** — and the override is always visible, because a number typed for one job and a number the
company stands behind are not the same kind of claim:

    20 m/day  ⟨BOOK⟩       inherited
     9 m/day  ⟨YOURS⟩      typed on this tender, for this group
     0        ⟨MISSING⟩    named something the book has no norm for. Flagged, never defaulted.

:func:`resolve` is the **only** place that decision is made. Every screen showing a source chip reads
it from here; nothing else may decide what is BOOK and what is YOURS, for the same reason
``authorOf`` is written once on the frontend — a provenance mark that two code paths can disagree
about is worse than no mark at all.

THE DEFAULTS ARE THE ENGINE'S OWN CONSTANTS
-------------------------------------------
Every default below is imported from the module that uses it, never retyped. A book that says 33% while
:mod:`client_boq.boq.resources` prices at 30% is a bug nobody would find by reading either file, so
``test_boq_outputs.py`` fails the moment the two drift.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.duration import DEPTH_BAND_M
from client_boq.boq.groups import HoleGroup
from client_boq.boq.resources import DEFAULT_MARKUP_PCT, DEFAULT_MOB_DAYS

# Where a norm sits on the Outputs screen, in the order it is read.
BLOCK_PRODUCTIVITY = "productivity"
BLOCK_ON_SITE = "on_site"
BLOCK_SHARED = "shared"
BLOCK_MARKUP = "markup"
BLOCK_ORDER = (BLOCK_PRODUCTIVITY, BLOCK_ON_SITE, BLOCK_SHARED, BLOCK_MARKUP)

BLOCK_TITLE = {
    BLOCK_PRODUCTIVITY: "Productivity",
    BLOCK_ON_SITE: "On site",
    BLOCK_SHARED: "Shared resources — the share one job consumes",
    BLOCK_MARKUP: "Markup",
}

# Where a value came from.
SOURCE_BOOK = "book"
SOURCE_YOURS = "yours"
SOURCE_MISSING = "missing"


class Norm(BaseModel):
    """The declaration of one norm: what it is called, what it means, and what it defaults to.

    Held as data rather than as pydantic fields on the book so that adding a norm is one entry in one
    tuple — the screen renders :data:`NORMS` directly, and a new row appears without a schema change,
    a migration, or a second list to keep in step.
    """

    key: str
    label: str
    unit: str = ""
    block: str = BLOCK_PRODUCTIVITY
    default: float = 0.0
    note: str = ""          # the `⌞` line under the row; why the number is what it is


NORMS: tuple[Norm, ...] = (
    Norm(key="soil_output", label="Drilling, soil", unit="m/day", block=BLOCK_PRODUCTIVITY,
         default=20.0,
         note="before depth decay — the first twenty metres of an average hole"),
    Norm(key="rock_output", label="Drilling, rock", unit="m/day", block=BLOCK_PRODUCTIVITY,
         default=10.0),
    Norm(key="decay_pct", label=f"Efficiency loss per {DEPTH_BAND_M:g} m of depth", unit="%",
         block=BLOCK_PRODUCTIVITY, default=5.0,
         note="a deeper hole is a slower hole: more rods to trip, more spoil to lift"),
    Norm(key="shift_hours", label="Shift length", unit="hours", block=BLOCK_PRODUCTIVITY,
         default=8.0),

    Norm(key="mob_days", label="Mobilisation and demobilisation", unit="days", block=BLOCK_ON_SITE,
         default=DEFAULT_MOB_DAYS,
         note="plant and staff are on site this much longer than the drilling — "
              "one day in, one to set up, one to dismantle, one out"),

    Norm(key="coef_project_manager", label="Project manager", unit="", block=BLOCK_SHARED,
         default=0.33, note="split across three jobs"),
    Norm(key="coef_geologist", label="Geologist", unit="", block=BLOCK_SHARED, default=0.50),
    Norm(key="coef_site_engineer", label="Site engineer", unit="", block=BLOCK_SHARED, default=1.00),
    Norm(key="coef_plant_oncost", label="Plant on-cost factor", unit="", block=BLOCK_SHARED,
         default=1.23,
         note="fuel, servicing, insurance and standby cover, as a multiple of the bare hire rate"),

    Norm(key="markup_pct", label="Default markup", unit="%", block=BLOCK_MARKUP,
         default=DEFAULT_MARKUP_PCT,
         note="a starting point. Margin is a commercial decision taken per tender, on the Price step"),
)

NORM_INDEX: dict[str, Norm] = {norm.key: norm for norm in NORMS}


class OutputBook(BaseModel):
    """The company's norms. Absent keys fall back to the declared default, never to zero."""

    values: dict[str, float] = Field(default_factory=dict)

    def get(self, key: str) -> Optional[float]:
        """The book's number for ``key``, or ``None`` if the book has no such norm.

        ``None`` and ``0.0`` are different answers and the caller has to be able to tell them apart:
        a decay of zero is a claim that holes do not slow down, which is a thing an estimator might
        genuinely believe. A norm nobody has ever set is not that.
        """
        if key in self.values:
            return float(self.values[key])
        norm = NORM_INDEX.get(key)
        return None if norm is None else norm.default

    # The handful the engine actually reads, named so a caller does not carry string keys around.
    @property
    def soil_output(self) -> float:
        return self.get("soil_output") or 0.0

    @property
    def rock_output(self) -> float:
        return self.get("rock_output") or 0.0

    @property
    def decay(self) -> float:
        """As a fraction, which is what :func:`client_boq.boq.duration.simulate` takes.

        Stored as a percentage because that is how it is said out loud — "five percent per twenty
        metres" — and converted in exactly one place so no caller has to remember which it holds.
        """
        return (self.get("decay_pct") or 0.0) / 100.0

    @property
    def mob_days(self) -> float:
        return self.get("mob_days") or 0.0

    @property
    def markup_pct(self) -> float:
        return self.get("markup_pct") or 0.0

    @property
    def shift_hours(self) -> float:
        return self.get("shift_hours") or 0.0


def default_book() -> OutputBook:
    """The book as shipped — every declared norm at its default. What a new company starts from."""
    return OutputBook(values={norm.key: norm.default for norm in NORMS})


class Resolved(BaseModel):
    """One number, and where it came from. What a ``SourceChip`` renders."""

    key: str
    value: float = 0.0
    source: str = SOURCE_BOOK
    book_value: Optional[float] = None      # so the chip can say "⟨BOOK 20⟩" beside your 9
    label: str = ""
    unit: str = ""

    @property
    def overridden(self) -> bool:
        return self.source == SOURCE_YOURS


def resolve(book: OutputBook, override: Optional[dict[str, float]] = None,
            *, keys: Optional[list[str]] = None) -> dict[str, Resolved]:
    """Settle every norm against a tender's overrides. **The only place BOOK/YOURS/MISSING is decided.**

    ``override`` is what this tender typed — a hole group's outputs, say. A key present in it wins and
    is marked ``yours``; a key absent falls through to the book and is marked ``book``; a key in
    neither is ``missing`` and carries 0.0, **flagged rather than quietly priced**, exactly as an
    archived rate resolves on a re-run.

    An override that merely restates the book is still ``yours``: the person typed it, and a number
    somebody chose is a different claim from a number they inherited, even when the digits match.
    """
    typed = {k: float(v) for k, v in (override or {}).items() if v is not None}
    wanted = keys if keys is not None else sorted({*NORM_INDEX, *typed})

    out: dict[str, Resolved] = {}
    for key in wanted:
        norm = NORM_INDEX.get(key)
        booked = book.get(key)
        common = {"key": key, "book_value": booked,
                  "label": norm.label if norm else key, "unit": norm.unit if norm else ""}
        if key in typed:
            out[key] = Resolved(value=typed[key], source=SOURCE_YOURS, **common)
        elif booked is not None:
            out[key] = Resolved(value=booked, source=SOURCE_BOOK, **common)
        else:
            out[key] = Resolved(value=0.0, source=SOURCE_MISSING, **common)
    return out


# The group fields that inherit from the book, and the norm each inherits from.
GROUP_INHERITS = {
    "soil_output": "soil_output",
    "rock_output": "rock_output",
    "decay": "decay_pct",
}


def apply_to_group(group: HoleGroup, book: OutputBook) -> tuple[HoleGroup, dict[str, Resolved]]:
    """Fill a group's un-overridden outputs from the book, and say for each where it came from.

    Reads :attr:`HoleGroup.overrides` — the fields the estimator actually typed — rather than
    inferring intent from the values. A group nobody has touched carries ``decay = 0.05`` because
    that is the field's default, and one where somebody deliberately chose 5% carries the identical
    number; only the recorded act separates them, and that distinction is the whole point of the
    ⟨BOOK⟩/⟨YOURS⟩ chip.

    Returns the filled group and a map keyed by **group field name**, so a screen can put a chip
    beside the input it belongs to without knowing the book's key for it.
    """
    typed: dict[str, float] = {}
    for field, norm_key in GROUP_INHERITS.items():
        if field not in group.overrides:
            continue
        value = float(getattr(group, field))
        # `decay` is a fraction on the group and a percentage in the book.
        typed[norm_key] = value * 100.0 if norm_key == "decay_pct" else value

    settled = resolve(book, typed, keys=list(GROUP_INHERITS.values()))
    filled = group.model_copy(update={
        "soil_output": settled["soil_output"].value,
        "rock_output": settled["rock_output"].value,
        "decay": settled["decay_pct"].value / 100.0,
    })
    return filled, {field: settled[norm_key] for field, norm_key in GROUP_INHERITS.items()}
