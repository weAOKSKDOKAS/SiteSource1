"""Every text read names its encoding — because a guard that only runs on Linux is not guarding.

WHAT HAPPENED. Three AST sweeps read source with `path.read_text()` and no encoding. Python
then uses the PLATFORM default: UTF-8 on Linux, **cp1252 on Windows**. This repo's source is
written with typographic quotes and em dashes — `”` is `E2 80 9D` in UTF-8, and byte `0x9D` is
undefined in cp1252 — so on the developer's own machine those three guards died with
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d` while passing in CI. A guard that
cannot run where the code is written is a guard nobody runs.

THE CLASS, not the three instances. The same latent platform dependence sits in any text-mode
`open()` or `Path.read_text()`/`write_text()` with no encoding, so this file sweeps for all of
them. Twelve sites were fixed with it; it exists so the thirteenth is caught by a test rather
than by somebody's Windows box.

Three things it deliberately does NOT flag:

* **binary mode** — `open(p, "rb")` has no encoding to name;
* **library opens** — `fitz.open`, `Image.open`, `ZipFile.open` are not the builtin and take no
  encoding at all. They are allow-listed BY OWNER rather than skipped as a class, so a
  `path.open()` added tomorrow (which IS text mode by default) fails this test instead of
  slipping through the same hole in a different shape;
* **files outside the backend tree** — the frontend is TypeScript and Vite reads it as UTF-8.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

#: The backend tree — this file is at backend/client_boq/tests/, so up three.
BACKEND = pathlib.Path(__file__).resolve().parent.parent.parent

#: Owners of a `.open()` that is NOT the builtin and takes no `encoding`. Anything else with an
#: `.open()` is either a Path (text mode by default — must name it) or something unrecognised,
#: and either way a person should look rather than the sweep quietly widening.
NOT_A_TEXT_OPEN = {"fitz", "Image", "pdfplumber", "zipfile", "ZipFile", "tarfile", "gzip", "io",
                   "zf", "archive", "wb"}


def _sources() -> list[pathlib.Path]:
    return [p for p in sorted(BACKEND.rglob("*.py"))
            if not any(part in {"__pycache__", ".venv", "node_modules"} for part in p.parts)]


def _mode_of(node: ast.Call):
    """The `mode` argument as a literal, or None when it is absent or not a constant."""
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        return node.args[1].value
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def _scan(path: pathlib.Path) -> tuple[list[str], list[str], int]:
    """(unencoded text reads, unrecognised `.open()` owners, count of calls that DO name one)."""
    # The encoding this whole file is about. Without it, this guard would carry the very defect
    # it guards against — and would fail on Windows while reporting a clean sweep on Linux.
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    unencoded: list[str] = []
    unknown: list[str] = []
    encoded = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        named = any(keyword.arg == "encoding" for keyword in node.keywords)
        mode = _mode_of(node)
        binary = mode is not None and "b" in str(mode)

        if isinstance(func, ast.Name) and func.id == "open":
            what = "open()"
        elif isinstance(func, ast.Attribute) and func.attr in {"read_text", "write_text"}:
            what = f"{func.attr}()"
        elif isinstance(func, ast.Attribute) and func.attr == "open":
            owner = func.value.id if isinstance(func.value, ast.Name) else ""
            if owner not in NOT_A_TEXT_OPEN and not named and not binary:
                unknown.append(f"{path.relative_to(BACKEND)}:{node.lineno}: {owner or '?'}.open()")
            continue
        else:
            continue

        if named:
            encoded += 1
        elif not binary:
            unencoded.append(f"{path.relative_to(BACKEND)}:{node.lineno}: {what}")
    return unencoded, unknown, encoded


class TestEveryTextReadNamesItsEncoding:
    def test_no_text_open_or_read_text_leaves_it_to_the_platform(self):
        offenders: list[str] = []
        for path in _sources():
            unencoded, _unknown, _encoded = _scan(path)
            offenders.extend(unencoded)
        assert not offenders, (
            "these read or write text without naming an encoding, so they use the platform "
            "default — UTF-8 on Linux, cp1252 on Windows — and this repo's source and fixtures "
            "contain characters cp1252 cannot decode. Pass encoding=\"utf-8\":\n  "
            + "\n  ".join(offenders))

    def test_an_unrecognised_dot_open_is_looked_at_rather_than_assumed(self):
        """`fitz.open` takes no encoding; `path.open()` is text mode and does. The allow-list is
        by OWNER so the second cannot arrive wearing the first's exemption."""
        unknown: list[str] = []
        for path in _sources():
            _unencoded, found, _encoded = _scan(path)
            unknown.extend(found)
        assert not unknown, (
            "an `.open()` whose owner is not a known binary/library opener. If it is a "
            "pathlib.Path, name the encoding; if it is another library that takes none, add its "
            "name to NOT_A_TEXT_OPEN so the exemption is written down:\n  "
            + "\n  ".join(unknown))

    def test_the_sweep_actually_finds_call_sites(self):
        """A sweep that matches nothing passes for the wrong reason — the same trap the
        `demo_mode` sweep names. This one must SEE the calls it is judging."""
        encoded = sum(_scan(path)[2] for path in _sources())
        assert encoded >= 20, (
            f"the AST walk found only {encoded} call(s) naming an encoding, which means it is "
            f"not looking at the reads it claims to guard")


class TestTheFailureModeIsRealNotTheoretical:
    """The empirical half. Asserting "cp1252 would break" is a claim; decoding the tree with it
    and watching it fail is the evidence — and it is what makes the fix above load-bearing
    rather than precautionary."""

    def test_this_repo_genuinely_cannot_be_read_as_cp1252(self):
        undecodable = []
        for path in _sources():
            raw = path.read_bytes()
            try:
                raw.decode("cp1252")
            except UnicodeDecodeError:
                undecodable.append(path.relative_to(BACKEND))
        assert undecodable, (
            "no source file fails to decode as cp1252, which would mean the Windows failure "
            "this guard exists for cannot happen — check the sweep before deleting the guard")

    def test_the_sweeps_that_broke_can_now_read_the_whole_tree(self):
        """The three that failed did exactly this: `ast.parse(path.read_text(...))` over the
        tree. With the encoding named it succeeds on every file, on any platform."""
        for path in _sources():
            ast.parse(path.read_text(encoding="utf-8"))

    def test_a_guard_that_reads_source_without_an_encoding_would_fail_here(self, tmp_path):
        """The bug, reproduced in miniature: a file holding a typographic quote, read the way
        the three sweeps read it, under the codec Windows would have chosen."""
        offender = tmp_path / "quoted.py"
        offender.write_text('X = "the client’s “bill”"  # — as written\n',
                            encoding="utf-8")
        with pytest.raises(UnicodeDecodeError):
            offender.read_bytes().decode("cp1252")
        # And with the encoding named, the same bytes parse.
        assert ast.parse(offender.read_text(encoding="utf-8"))
