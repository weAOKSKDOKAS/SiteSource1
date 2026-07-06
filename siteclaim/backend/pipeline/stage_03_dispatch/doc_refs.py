"""Reference extraction from Schedule-of-Rates item text (Layer 1, deterministic).

Real HK SoR items cite the documents that govern them in their own description — PS clauses
(``PS 1.13.1``), GS clauses (``GS 25.01``), Preambles (``PB/B11``), standard drawings
(``Standard Drawing C1012B``), sketches, and appendices (``Appendix 7.4.1``). This module
pulls those references out by regex and rolls them up per SoR section, so the dispatch
assembler can slice each firm's document set to what its section actually references. Pure
regex — no LLM, no network.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

# Each kind: (regex with one capturing group for the identifier, normaliser). Order is the
# display order. ``\b`` anchors keep ``PS`` from firing inside ``GPS`` / ``maps``.
_PATTERNS: list[tuple[str, re.Pattern, Callable[[re.Match], str]]] = [
    ("ps", re.compile(r"\bPS\s*(\d+(?:\.\d+)*)", re.I), lambda m: f"PS {m.group(1)}"),
    ("gs", re.compile(r"\bGS\s*(\d+(?:\.\d+)*)", re.I), lambda m: f"GS {m.group(1)}"),
    ("pb", re.compile(r"\bPB\s*/?\s*([A-Za-z]\d*)", re.I), lambda m: f"PB/{m.group(1).upper()}"),
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


def _merge_into(acc: dict[str, list[str]], refs: dict[str, list[str]]) -> None:
    for kind, vals in refs.items():
        lst = acc.setdefault(kind, [])
        for v in vals:
            if v not in lst:
                lst.append(v)


def refs_for_items(items: Iterable) -> dict[str, list[str]]:
    """Union of references across a set of SoR items (each carrying ``.description``)."""
    acc: dict[str, list[str]] = {}
    for it in items:
        _merge_into(acc, extract_refs(getattr(it, "description", "") or ""))
    return acc


def section_refs(items: Iterable) -> dict[str, dict[str, list[str]]]:
    """Per section code (``item.section``) -> {kind -> distinct refs}, rolled up from that
    section's items. Items with no section fall under ``''``."""
    by_section: dict[str, dict[str, list[str]]] = {}
    for it in items:
        refs = extract_refs(getattr(it, "description", "") or "")
        if not refs:
            continue
        _merge_into(by_section.setdefault(getattr(it, "section", "") or "", {}), refs)
    return by_section


def spec_section_of(ref: str) -> str:
    """The spec section number a PS/GS clause belongs to: ``PS 28.2.07`` -> ``28``."""
    m = re.search(r"(\d+)", ref or "")
    return m.group(1) if m else ""


def clause_of(ref: str) -> str:
    """The dotted clause/appendix number: ``PS 7.13.1`` -> ``7.13.1``, ``Appendix 7.4.1`` -> ``7.4.1``."""
    m = re.search(r"(\d+(?:\.\d+)*)", ref or "")
    return m.group(1) if m else ""
