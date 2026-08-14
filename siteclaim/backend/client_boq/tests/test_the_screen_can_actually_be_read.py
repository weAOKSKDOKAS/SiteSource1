"""Contrast and type size, computed rather than eyeballed.

WHAT WAS MEASURED, 2026-08-14, after the owner said the colours made it hard work to read.

* **32% of every piece of text in the app was under 10px** — 190 instances at 8 and 8.5px, one at
  7px. Uppercase mono at 8px is not a small label, it is a dare.
* **`faint`, the second most-used text colour in the whole frontend (330 uses), sat at 2.3–3.0:1**
  against the surfaces it is printed on. WCAG AA asks 4.5:1 for body text. It failed on every
  single surface, including plain white.
* **`amber` — the WARNING colour — was 2.4:1.** A warning nobody can read is not a warning.
* **177 places had both problems at once**: under 10px AND under 4.5:1.

THE FIX, AND WHY IT IS NOT JUST "DARKEN THE GREYS". Solving each token for AA against its worst
surface drove `faint` and `muted` to within a hair of each other, which would have collapsed the
three-step text hierarchy the whole design depends on. That collapse pointed at the real error: a
10px tracked uppercase label needs MORE contrast than 11px running text, not less, and the palette
had it the other way round. So labels now earn their quietness from case, weight and letter-spacing
— which is what actually makes something read as a label — and not from being too pale to read.

Two tint surfaces were lightened rather than darkening the text on them. `brass-tint` at #f0e2c8
was the surface every marginal token failed against; lightening the DECORATION fixes three tokens
at once and muddies no information. When a colour pair fails, prefer moving the one that carries
nothing.

WHY THIS TEST IS IN THE PYTHON SUITE. There is no frontend test runner here — TypeScript is the
whole net, and `tsc` has nothing to say about whether #8a97a3 on #faf9f6 can be read. Contrast is
arithmetic over two hex strings, so it can be asserted exactly, and a palette regression is
otherwise invisible until somebody complains again.
"""

from __future__ import annotations

import collections
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2].parent / "frontend" / "src" / "client_boq"
TOKENS = FRONTEND / "tokens.css"

#: WCAG 2.1 AA: 4.5:1 for normal text, 3:1 for large text and UI components.
AA_TEXT = 4.5

#: Nothing a person is expected to read goes below this. Uppercase mono labels sit exactly here.
MIN_PX = 10.0

#: The light surfaces text is printed on in this palette. Every one of them is a real background
#: in the app — cards, panels, the desk behind them, and the four semantic tints.
SURFACE_TOKENS = ("page", "surface", "warm", "panel", "desk", "selected", "brass-tint",
                  "negotiated", "ok-tint", "bad-tint", "info", "info-fill")

#: Tokens used as TEXT on those surfaces. `dim`, `disabled` and `on-brass` are excluded by name:
#: they live on the dark app bar or on a brass fill and are checked separately below.
TEXT_TOKENS = ("ink-text", "body", "muted", "faint", "brass-text", "brass-text-light",
               "amber", "ok-dark", "bad-dark", "blue", "navy")

DARK_TOKENS = ("ink", "navy", "ink-active")


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG 2.1 relative contrast. Symmetric, so the argument order does not matter."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@pytest.fixture(scope="module")
def tokens() -> dict[str, str]:
    source = TOKENS.read_text(encoding="utf-8")
    found = dict(re.findall(r"--color-cb-([\w-]+):\s*(#[0-9a-fA-F]{6})", source))
    assert found, "no cb- colour tokens found — has tokens.css moved?"
    return found


class TestTheMathsItself:
    """A contrast test that computes the wrong number would pass forever."""

    def test_black_on_white_is_twenty_one_to_one(self):
        assert contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)

    def test_a_colour_against_itself_is_one(self):
        assert contrast("#bd9a5f", "#bd9a5f") == pytest.approx(1.0, abs=0.001)

    def test_it_is_symmetric(self):
        assert contrast("#112233", "#faf9f6") == pytest.approx(contrast("#faf9f6", "#112233"))

    def test_the_shipped_defect_would_have_been_caught(self):
        """The exact pair that was on screen: `faint` as it was, on the card surface."""
        assert contrast("#8a97a3", "#faf9f6") < AA_TEXT


class TestEveryTextColourCanBeReadOnEverySurface:
    def test_no_pair_falls_below_AA(self, tokens):
        failures: list[str] = []
        for text in TEXT_TOKENS:
            if text not in tokens:
                continue
            for surface in SURFACE_TOKENS:
                if surface not in tokens:
                    continue
                ratio = contrast(tokens[text], tokens[surface])
                if ratio < AA_TEXT:
                    failures.append(
                        f"  {text} ({tokens[text]}) on {surface} ({tokens[surface]}) = "
                        f"{ratio:.2f}:1")
        assert not failures, (
            f"WCAG AA asks {AA_TEXT}:1 for text. These pairs are below it:\n"
            + "\n".join(failures)
            + "\n\nPrefer LIGHTENING the surface when it carries no information — that is how "
              "brass-tint was fixed — over darkening the text until the hierarchy collapses.")

    def test_the_warning_colour_is_readable_because_a_warning_has_to_be(self, tokens):
        """Singled out because it was the worst of them at 2.4:1, and it is the one colour whose
        entire job is to be noticed."""
        worst = min(contrast(tokens["amber"], tokens[s]) for s in SURFACE_TOKENS if s in tokens)
        assert worst >= AA_TEXT, f"amber bottoms out at {worst:.2f}:1"

    def test_the_hierarchy_still_steps(self, tokens):
        """All four passing is not enough — they must still be visibly different, or the design
        has been flattened into one grey in the name of accessibility."""
        steps = [luminance(tokens[k]) for k in ("ink-text", "body", "muted", "faint")]
        assert steps == sorted(steps), "each step must be lighter than the one before it"
        for a, b in zip(steps, steps[1:]):
            assert b - a > 0.015, "two steps are too close to tell apart"

    def test_text_on_the_dark_app_bar_is_readable_too(self, tokens):
        """`dim` is excluded from the sweep above because it belongs on the dark surfaces. It
        still has to pass THERE — being on a different background is not an exemption."""
        for text in ("dim", "on-brass"):
            if text not in tokens:
                continue
            grounds = DARK_TOKENS if text == "dim" else ("brass",)
            worst = min(contrast(tokens[text], tokens[g]) for g in grounds if g in tokens)
            assert worst >= AA_TEXT, f"{text} bottoms out at {worst:.2f}:1 on its own ground"


@pytest.fixture(scope="module")
def sizes() -> collections.Counter:
    """Every explicit font size in the module, and how often each is used."""
    found: collections.Counter = collections.Counter()
    for path in FRONTEND.rglob("*.tsx"):
        for match in re.finditer(r"text-\[([\d.]+)px\]", path.read_text(encoding="utf-8")):
            found[float(match.group(1))] += 1
    assert found, "no explicit font sizes found — has the styling approach changed?"
    return found


class TestNothingIsTooSmallToRead:
    def test_no_utility_is_below_the_floor(self, sizes):
        under = {s: n for s, n in sizes.items() if s < MIN_PX}
        assert not under, (
            f"{sum(under.values())} font-size utilities sit below {MIN_PX:g}px: "
            + ", ".join(f"{s:g}px x{n}" for s, n in sorted(under.items()))
            + ". A label reads as a label because it is uppercase, tracked and mono — not "
              "because it is too small to read.")

    def test_the_floor_is_actually_used_rather_than_the_rule_being_vacuous(self, sizes):
        """If every size drifted up to 12px this test would pass while saying nothing. The floor
        being populated is what makes it a floor."""
        assert sizes[MIN_PX] > 50, f"only {sizes[MIN_PX]} utilities at the {MIN_PX:g}px floor"

    def test_it_reports_the_shape_of_the_scale(self, sizes, capsys):
        total = sum(sizes.values())
        with capsys.disabled():
            print(f"\n  type scale: {total} utilities, floor {min(sizes):g}px, "
                  f"{sum(n for s, n in sizes.items() if s <= 11) / total:.0%} at 11px or under")
