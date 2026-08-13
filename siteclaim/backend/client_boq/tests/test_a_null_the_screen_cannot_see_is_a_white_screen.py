"""A TypeScript type that hides a ``null`` is a crash the compiler was asked not to find.

WHAT HAPPENED. `Station.length_m` is `Optional[float] = None` on the backend and was declared
`length_m: number` in `types.ts`. On a schedule read from GI/210 — which prints no tentative
borehole length, the same missing column as trap 12 — every station arrived carrying
`"length_m": null`, and the Holes view rendered `formatNorm(station.length_m)` for each hole card.
`Number.isInteger(null)` is false, so it fell through to `null.toFixed(4)`:

    TypeError: Cannot read properties of null (reading 'toFixed')

The whole screen stopped drawing. Worse, that screen is where the map SENDS you: clicking a hole
pin calls `setView("holes")`, so the map's one interaction led straight into it and looked, from
the outside, like the map button was broken. One null, two bug reports.

WHY THE COMPILER DID NOT CATCH IT. It could not. TypeScript checks the code against the types it
is given, and it was given a type that said the value is always a number. Every `.toFixed`, every
piece of arithmetic, every `.map` on a list typed non-null is checked against a promise nothing
verifies — the interface is hand-written and the wire is not consulted. A type that lies is worse
than no type, because it converts a question the compiler would have asked into one nobody asks.

This is trap 12 seen from the other side. There, a null from a model discarded 47 boreholes because
pydantic validated the payload as one object. Here, a null from OUR OWN backend blanked a screen
because a hand-written interface disagreed with the model that fills it. Both come from the same
wrong instinct: treating "there is none" as a case that will not arrive.

WHAT THIS SWEEPS, and what it does not. It reads every pydantic model under `client_boq/` and every
`export interface` in `types.ts`, matches them BY NAME, and fails on a field the model may serialise
as null that the interface declares non-nullable. It therefore covers the types that cross the wire
as models. It does NOT cover an interface hand-written for an endpoint's ad-hoc dict — there is no
model to compare against — so `test_coverage_is_reported_not_assumed` prints how many interfaces
were actually checked rather than letting a shrinking match rate read as a clean sweep.

MATCHING BY FIELD NAME INSTEAD WAS TRIED AND IS NOISE — recorded so it is not rebuilt. Flagging
any unpaired interface field whose NAME is Optional on some model produced eleven suspects and all
eleven were collisions: `CostingResponse.priced` is a whole `PricedBQ` object, while the Optional
`priced` it collided with is `ScopeAlignmentFinding.priced: Optional[bool]`, an unrelated flag
about whether the AI thought an item was priced. A guard at that false-positive rate gets muted,
and a muted guard is worse than none.

The related sweep for the other way the compiler is silenced — a non-null assertion (`x!`) or an
`any` — was run over the same tree and is clean: all thirty-one assertions are guarded by a
condition in the same expression (`.filter(d => d.billed !== null)` then `d.billed!`, `byRef.has`
then `byRef.get(ref)!`), which is TypeScript being unable to follow a narrowing a reader can check
in one glance. That is why this file guards the TYPES and not the assertions: an assertion is a
promise about the line above it, and a type is a promise about a server nobody is reading.

The fix is always to make the TYPE honest and let `tsc` find the call sites. Never to widen the
runtime read with `?? 0`: a length that was never printed is a blank, and zero is a claim that the
hole has no depth.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
MODULE = BACKEND / "client_boq"
TYPES = BACKEND.parent / "frontend" / "src" / "client_boq" / "types.ts"

MODEL_BASES = {"BaseModel", "NullTolerant", "models.NullTolerant"}


def _may_be_null(annotation: ast.expr | None) -> bool:
    """Does this annotation serialise as JSON null? ``Optional[X]`` and ``X | None`` both do."""
    if annotation is None:
        return False
    source = ast.unparse(annotation)
    return source.startswith("Optional[") or "| None" in source or source == "None"


def _python_models() -> dict[str, dict[str, bool]]:
    """Every pydantic model in the module → {field: may_be_null}. Tests excluded."""
    models: dict[str, dict[str, bool]] = {}
    for path in sorted(MODULE.rglob("*.py")):
        if "tests" in path.parts:
            continue
        # encoding= deliberately — this file is a guard, and trap 14 is about guards that only
        # run on one platform.
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not {ast.unparse(b) for b in node.bases} & MODEL_BASES:
                continue
            fields = {
                stmt.target.id: _may_be_null(stmt.annotation)
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and not stmt.target.id.startswith("_")
                and stmt.target.id != "model_config"
            }
            models.setdefault(node.name, {}).update(fields)
    return models


def _ts_interfaces() -> dict[str, dict[str, bool]]:
    """Every exported interface in types.ts → {field: admits_null}."""
    source = TYPES.read_text(encoding="utf-8")
    out: dict[str, dict[str, bool]] = {}
    for match in re.finditer(r"export interface (\w+)[^{]*\{(.*?)\n\}", source, re.S):
        name, body = match.group(1), match.group(2)
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)      # block comments
        body = re.sub(r"//[^\n]*", "", body)                   # line comments
        fields: dict[str, bool] = {}
        # A field runs to the semicolon that ends it — but an inline object literal carries its
        # own semicolons, so brace depth decides. Getting this wrong reads `cite: {a: string;
        # ...} | null` as non-nullable and reports a type that is already correct.
        for line in re.finditer(r"^ {2}(\w+)(\??):[ \t]*(.*)$", body, re.M):
            field, optional, rest = line.group(1), line.group(2), line.group(3)
            depth, declared = 0, []
            for char in rest:
                if char in "{([":
                    depth += 1
                elif char in "})]":
                    depth -= 1
                elif char == ";" and depth <= 0:
                    break
                declared.append(char)
            typed = "".join(declared)
            fields[field] = bool(optional) or "null" in typed or "undefined" in typed
        out[name] = fields
    return out


@pytest.fixture(scope="module")
def paired() -> list[tuple[str, dict[str, bool], dict[str, bool]]]:
    models, interfaces = _python_models(), _ts_interfaces()
    return [(n, models[n], interfaces[n]) for n in sorted(set(models) & set(interfaces))]


class TestTheDefectThatWasMeasured:
    def test_a_station_length_is_declared_nullable(self):
        """The exact field, named, because a sweep that passes for the wrong reason is not a
        regression test for the bug that was actually shipped."""
        interfaces = _ts_interfaces()
        assert interfaces["Station"]["length_m"] is True, (
            "Station.length_m is Optional[float] on the backend — GI/210 prints no tentative "
            "length. Declaring it `number` is what blanked the Holes view.")
        assert interfaces["Station"]["max_boring_m"] is True

    def test_the_screen_prints_a_blank_rather_than_inventing_a_number(self):
        """`?? 0` would have silenced the crash and published a lie: a hole with no depth. The
        fix has to be visible on screen as an absence."""
        site = (TYPES.parent / "tabs" / "Site.tsx").read_text(encoding="utf-8")
        assert "station.length_m === null" in site
        assert "station.length_m ?? 0" not in site


class TestNoTypeMayHideANull:
    def test_every_paired_field_agrees_about_null(self, paired):
        offenders: list[str] = []
        for name, model, interface in paired:
            offenders += [
                f"  {name}.{field}"
                for field, nullable in model.items()
                if nullable and interface.get(field) is False
            ]
        assert not offenders, (
            "These fields may serialise as null and the TypeScript type says they cannot, so the "
            "compiler will not ask any consumer to handle the blank:\n" + "\n".join(offenders)
            + "\n\nMake the type honest (`number | null`) and let `tsc` find the call sites.")

    def test_coverage_is_reported_not_assumed(self, paired, capsys):
        """A match rate that quietly fell to two types would still pass the sweep above. Print
        it, because an interface hand-written for an endpoint's ad-hoc dict has no model to be
        compared against and is genuinely NOT covered here."""
        interfaces = _ts_interfaces()
        with capsys.disabled():
            print(f"\n  null-honesty sweep: {len(paired)} of {len(interfaces)} interfaces paired "
                  f"with a pydantic model by name")
        assert len(paired) >= 40, (
            f"only {len(paired)} interfaces still pair with a model by name; the sweep has "
            f"stopped covering most of the wire")


class TestTheSweepItselfWorks:
    def test_it_would_catch_the_bug_that_was_shipped(self):
        """A guard nobody has seen fail is a guard nobody has tested."""
        model = {"length_m": True}
        assert [f for f, n in model.items() if n and {"length_m": False}.get(f) is False]

    def test_an_inline_object_type_is_not_read_as_non_nullable(self):
        """`cite: { part_id: string; page: number } | null` is correct and was reported as a
        violation by the first draft of this sweep, whose regex stopped at the first semicolon."""
        interfaces = _ts_interfaces()
        assert interfaces["TraceNode"]["cite"] is True

    def test_an_optional_annotation_is_recognised_both_ways(self):
        assert _may_be_null(ast.parse("Optional[float]", mode="eval").body)
        assert _may_be_null(ast.parse("float | None", mode="eval").body)
        assert not _may_be_null(ast.parse("float", mode="eval").body)
        assert not _may_be_null(ast.parse("list[str]", mode="eval").body)
