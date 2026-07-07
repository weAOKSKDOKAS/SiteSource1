"""Reference extraction from Schedule-of-Rates items (Layer 1, deterministic).

Real HK SoR rows cite the documents that govern them in a "Clause Ref" column (and often
again in the description) — General Specification clauses (``GS 7.34``), Particular
Specification clauses (``PS 7.34A``, ``PS 7.37A``, ``PS 7.41.(4)S`` — with letter / bracket /
``S`` suffixes), Method-of-Measurement preamble clauses (``PB 71``), plus Preambles
(``PB/B11``), standard drawings, sketches and appendices. This module pulls those references
out by regex from an item's ``clause_refs`` tokens (and, as a backstop, its description) and
rolls them up per SoR section, so the dispatch assembler slices each firm's spec bundle to the
clauses its section actually references. Pure regex — no LLM, no network.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

# A PS/GS clause id: a dotted number with an optional letter suffix, an optional bracketed
# sub-index (the separating dot is optional — real docs write both ``7.41.(4)S`` and ``7.72(6)S``),
# and an optional trailing letter — 7.34, 7.34A, 7.39S, 7.41.(4)S, 7.72(6)S, 28.2.07.
_CLAUSE_ID = r"\d+(?:\.\d+)*[A-Za-z]?(?:\.?\(\d+\))?[A-Za-z]?"


def _norm_pb(m: re.Match) -> str:
    """``PB 71`` -> "PB 71" (an MM preamble clause); ``PB/B11`` / ``PB / c2`` -> "PB/B11" /
    "PB/C2" (a document preamble). The number form and the letter form are both kept, each
    normalised, so an MM ``PB N`` reference matches the MM index and a preamble ref stays legible."""
    g = m.group(1).upper()
    return f"PB {g}" if g[0].isdigit() else f"PB/{g}"


# Each kind: (regex with one capturing group for the identifier, normaliser). Order is the
# display order. ``\b`` anchors keep ``PS`` from firing inside ``GPS`` / ``maps``.
_PATTERNS: list[tuple[str, re.Pattern, Callable[[re.Match], str]]] = [
    ("ps", re.compile(rf"\bPS\s*({_CLAUSE_ID})", re.I), lambda m: f"PS {m.group(1)}"),
    ("gs", re.compile(rf"\bGS\s*({_CLAUSE_ID})", re.I), lambda m: f"GS {m.group(1)}"),
    ("pb", re.compile(r"\bPB\s*/?\s*([A-Za-z]?\d+[A-Za-z]?\d*)", re.I), _norm_pb),
    ("standard_drawing", re.compile(r"\bStandard\s+Drawings?\s*([A-Za-z0-9/]+)", re.I),
     lambda m: f"Standard Drawing {m.group(1).upper()}"),
    ("sketch", re.compile(r"\bSketch(?:es)?\s*([A-Za-z0-9/]+)", re.I),
     lambda m: f"Sketch {m.group(1).upper()}"),
    ("appendix", re.compile(r"\bAppendix\s*(\d+(?:\.\d+)*)", re.I), lambda m: f"Appendix {m.group(1)}"),
]

REF_KINDS = [kind for kind, _, _ in _PATTERNS]


def extract_refs(text: str) -> dict[str, list[str]]:
    """Distinct references in ``text``, grouped by kind (order-stable, only kinds present)."""
    out: dict[str, list[str]] = {}
    for kind, pattern, norm in _PATTERNS:
        found: list[str] = []
        for m in pattern.finditer(text or ""):
            ref = norm(m)
            if ref not in found:
                found.append(ref)
        if found:
            out[kind] = found
    return out


# ``parse_clause_refs`` is the intent-named entry point for parsing a row's Clause Ref text.
parse_clause_refs = extract_refs


def _item_text(item) -> str:
    """An item's reference-bearing text: its ``clause_refs`` tokens (the Clause Ref column) plus
    its description as a backstop."""
    refs = getattr(item, "clause_refs", None) or []
    return " ".join([*refs, getattr(item, "description", "") or ""])


def _merge_into(acc: dict[str, list[str]], refs: dict[str, list[str]]) -> None:
    for kind, vals in refs.items():
        lst = acc.setdefault(kind, [])
        for v in vals:
            if v not in lst:
                lst.append(v)


def refs_for_items(items: Iterable) -> dict[str, list[str]]:
    """Union of references across a set of SoR items — each item's Clause Ref tokens + description."""
    acc: dict[str, list[str]] = {}
    for it in items:
        _merge_into(acc, extract_refs(_item_text(it)))
    return acc


def section_refs(items: Iterable) -> dict[str, dict[str, list[str]]]:
    """Per section code (``item.section``) -> {kind -> distinct refs}, rolled up from that
    section's items. Items with no section fall under ``''``."""
    by_section: dict[str, dict[str, list[str]]] = {}
    for it in items:
        refs = extract_refs(_item_text(it))
        if not refs:
            continue
        _merge_into(by_section.setdefault(getattr(it, "section", "") or "", {}), refs)
    return by_section


def spec_section_of(ref: str) -> str:
    """The spec section number a PS/GS clause belongs to: ``PS 28.2.07`` -> ``28``."""
    m = re.search(r"(\d+)", ref or "")
    return m.group(1) if m else ""


def clause_of(ref: str) -> str:
    """The clause id, suffix kept: ``PS 7.34A`` -> ``7.34A``, ``PS 7.41.(4)S`` -> ``7.41.(4)S``,
    ``PS 28.2.07`` -> ``28.2.07``, ``Appendix 7.4.1`` -> ``7.4.1``."""
    m = re.search(rf"({_CLAUSE_ID})", ref or "")
    return m.group(1) if m else ""


def base_clause(clause_id: str) -> str:
    """The base (GS) clause a suffixed PS clause amends: ``7.34A`` -> ``7.34``, ``7.41.(4)S`` ->
    ``7.41``. Trailing letters / bracketed sub-indices are dropped; a plain number is unchanged."""
    m = re.match(r"(\d+(?:\.\d+)*)", clause_id or "")
    return m.group(1) if m else (clause_id or "")
