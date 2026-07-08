"""Route a subcontractor's returned priced lines to their true SoR section (Layer 1, deterministic).

A reply resolved by its correlation ref fixes the tender + firm — but NOT the section. A firm often
returns items from a different or wider set of sections than the enquiry named (normal in real
tendering), so stamping every returned line with the enquiry's trade buries the real items and
starves the other sections. This matcher instead routes each parsed :class:`BidLineItem` to the
canonical SoR item it answers, and to that item's **section + package key** (``ground_investigation:H``),
grouping the reply into one bid per section the firm actually priced. A line matching no canonical
item is surfaced as an *extra* — never dropped, never folded into a section's totals.

Matching is pure Layer-1 work (the LLM already parsed the raw lines; it must not decide routing):

* **Primary — exact normalized ``item_ref``.** HK SoR codes are stable; the ref is the identity.
* **Secondary — description token-set similarity** (deterministic, no model), used ONLY when the
  ref failed to match (missing / garbled). A high threshold keeps a genuine extra unmatched rather
  than forcing it into a section.

``normalize_ref`` unifies the sub-item forms the documents drift between (``J5(a)`` / ``J5A`` /
``J5.a`` → ``J5A``); each line's group ``package_key`` is the tender's ACTUAL routed unit — the same
``routing.split.route_units`` key dispatch enquired on (the bare ``trade`` for a whole-routed
package, ``trade:SECTION`` only where the tender split that trade) — so replies and enquiries share
one key vocabulary and every downstream join (received counters, leveling, comparison) lines up.
No DB, no network, no model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from schemas.models import BidLineItem, ScopePackages

# Description-similarity acceptance for the secondary match. High on purpose: the token-set ratio
# scores strong lexical overlap ("Rotary drilling in rock" ~ "Rotary drilling, rock") well above
# 0.8, so a clearly-the-same line routes while a genuinely different one stays an extra.
DEFAULT_DESC_THRESHOLD = 0.80

# Sub-item punctuation the equivalent ref forms differ by: J5(a) / J5A / J5.a / "J5 (a)".
_SUBITEM_PUNCT = re.compile(r"[()\[\].\s]")
_WORD = re.compile(r"[a-z0-9]+")


def normalize_ref(ref: str) -> str:
    """Normalize an item_ref for matching: trim, upper-case, and unify sub-item punctuation so the
    forms the documents drift between collapse together — ``J5(a)`` / ``J5A`` / ``J5.a`` /
    ``J5 (a)`` all become ``J5A``. (The benchmark matcher only ``strip()``s refs; sub-item drift is
    specific to returned reply lines, so the extra normalisation lives here.)"""
    return _SUBITEM_PUNCT.sub("", (ref or "").strip().upper())


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall((text or "").lower()))


def token_set_ratio(a: str, b: str) -> float:
    """A deterministic 0..1 description similarity — the Dice coefficient over word-token sets
    (``2·|A∩B| / (|A|+|B|)``). No model; used only for the secondary, ref-less match."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return 2.0 * len(ta & tb) / (len(ta) + len(tb))


def unit_key_map(scope: ScopePackages) -> dict[tuple[str, str], str]:
    """``(trade, section) -> the routed-unit package_key that CONTAINS it``, from
    ``routing.split.route_units`` — the SAME function dispatch used to key each enquiry. A
    whole-routed trade maps all its sections to the bare ``trade``; a split trade maps each section
    to ``trade:SECTION``. So a reply is grouped under the key its enquiry was actually dispatched
    on, never a synthesised ``trade:SECTION`` that was not a routed unit of this tender."""
    from pipeline.routing.split import route_units  # lazy: keep stage-04 import light, no cycle

    mapping: dict[tuple[str, str], str] = {}
    for unit in route_units(scope):
        for it in unit["package"].sor_items:
            mapping.setdefault((unit["trade"], (it.section or "").strip()), unit["package_key"])
    return mapping


@dataclass(frozen=True)
class CanonicalItem:
    """One canonical SoR item from the tender's persisted scope, with its routing target — the
    routed-unit ``package_key`` that contains it, or ``None`` when the item's section belongs to no
    routed unit (a line matching it is surfaced as an extra, never invented into a unit)."""

    item_ref: str
    norm_ref: str
    description: str
    section: str
    package_key: Optional[str]


def build_canonical_items(scope: ScopePackages) -> list[CanonicalItem]:
    """The tender's canonical SoR items, each tagged with the routed unit a returned line that
    matches it belongs to (so replies and enquiries share one key vocabulary)."""
    units = unit_key_map(scope)
    items: list[CanonicalItem] = []
    for pkg in scope.packages:
        for it in pkg.sor_items:
            section = (it.section or "").strip()
            items.append(CanonicalItem(
                item_ref=it.item_ref,
                norm_ref=normalize_ref(it.item_ref),
                description=it.description or "",
                section=section,
                package_key=units.get((pkg.trade, section)),  # routed unit; None -> no unit -> extra
            ))
    return items


def section_totals(scope: ScopePackages) -> dict[str, int]:
    """``package_key -> canonical item count`` — the denominator for a reply's unit coverage."""
    totals: dict[str, int] = {}
    for c in build_canonical_items(scope):
        if c.package_key is not None:
            totals[c.package_key] = totals.get(c.package_key, 0) + 1
    return totals


@dataclass(frozen=True)
class RoutedLine:
    """One returned line and where it routed: the canonical item + section/package it matched, or
    ``method == "unmatched"`` (an extra — priced outside the tender)."""

    line: BidLineItem
    canonical_ref: Optional[str]
    section: Optional[str]
    package_key: Optional[str]
    method: str  # "ref" | "description" | "unmatched"


@dataclass(frozen=True)
class RoutingResult:
    """The reply routed by section: matched lines grouped by ``package_key`` (insertion order), the
    per-line detail, and the extras that matched no canonical item."""

    by_key: dict[str, list[BidLineItem]] = field(default_factory=dict)
    routed: list[RoutedLine] = field(default_factory=list)
    extras: list[BidLineItem] = field(default_factory=list)


def route_items(
    lines: list[BidLineItem], scope: ScopePackages, *, desc_threshold: float = DEFAULT_DESC_THRESHOLD,
) -> list[RoutedLine]:
    """Route each parsed line to its canonical item: primary exact-on-normalized-ref, secondary
    description token-set similarity (only when the ref did not match). Deterministic and pure."""
    canon = build_canonical_items(scope)
    by_ref: dict[str, CanonicalItem] = {}
    for c in canon:
        if c.norm_ref:
            by_ref.setdefault(c.norm_ref, c)  # first-wins on a duplicate normalized ref

    out: list[RoutedLine] = []
    for line in lines:
        nr = normalize_ref(line.item_ref)
        hit = by_ref.get(nr) if nr else None
        if hit is not None:
            out.append(RoutedLine(line, hit.item_ref, hit.section, hit.package_key, "ref"))
            continue
        # Secondary: the ref was missing / garbled — fall back to a deterministic description match.
        best: Optional[CanonicalItem] = None
        best_score = 0.0
        desc = line.description or ""
        if desc.strip():
            for c in canon:
                if not c.description.strip():
                    continue
                score = token_set_ratio(desc, c.description)
                if score > best_score:
                    best, best_score = c, score
        if best is not None and best_score >= desc_threshold:
            out.append(RoutedLine(line, best.item_ref, best.section, best.package_key, "description"))
        else:
            out.append(RoutedLine(line, None, None, None, "unmatched"))
    return out


def route_reply_lines(
    lines: list[BidLineItem], scope: ScopePackages, *, desc_threshold: float = DEFAULT_DESC_THRESHOLD,
) -> RoutingResult:
    """Route ``lines`` and group them by canonical ``package_key``; unmatched lines become extras.
    A line is never dropped and an extra never joins a section's group."""
    routed = route_items(lines, scope, desc_threshold=desc_threshold)
    by_key: dict[str, list[BidLineItem]] = {}
    extras: list[BidLineItem] = []
    for r in routed:
        if r.package_key is None:
            extras.append(r.line)
        else:
            by_key.setdefault(r.package_key, []).append(r.line)
    return RoutingResult(by_key=by_key, routed=routed, extras=extras)
