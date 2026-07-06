"""Section-level routing units (Prompt 2 — Layer 1, deterministic).

The routable unit on a real Schedule of Rates is the SECTION, not the whole trade. A trade
package that spans many sections (the GI=343-item case) is split into one sub-package per
section so the operator can route each independently — self-perform the drilling section,
sublet the landscape/survey sections. A single-section package (every demo package) stays
whole. The parent trade is kept for the coverage signal and shortlist (ingest already grouped
each section under the right trade); the section is the routing/display sub-division.

``package_key`` is the stable identity: ``trade`` (whole) or ``trade:SECTION`` (a sub-package).
Pure Python, no DB, no LLM.
"""

from __future__ import annotations

from schemas.models import ScopePackages, TradeWorkPackage

# Auto-propose a split when a package spans more than this many sections OR carries more than
# this many items — a genuinely multi-section package; a focused package stays whole.
SPLIT_MIN_SECTIONS = 3
SPLIT_MIN_ITEMS = 60


def should_split(pkg: TradeWorkPackage) -> bool:
    """True when a package is big/varied enough that per-section routing is proposed."""
    return len(pkg.sections) > SPLIT_MIN_SECTIONS or len(pkg.sor_items) > SPLIT_MIN_ITEMS


def _summary(code: str, title: str, items: list) -> str:
    head = f"Section {code}" + (f" — {title}" if title else "")
    sample = ", ".join((it.description or it.item_ref) for it in items[:4] if (it.description or it.item_ref))
    return f"{head} ({len(items)} item{'s' if len(items) != 1 else ''})" + (f": {sample}" if sample else "")


def route_units(scope: ScopePackages, *, split_keys: set[str] | None = None) -> list[dict]:
    """The routable units for a scope. Each unit: ``package_key`` (``trade`` or
    ``trade:SECTION``), ``trade`` (the parent, for signal + shortlist), ``section`` /
    ``section_title``, ``scope_summary``, and ``package`` (a section-scoped
    :class:`TradeWorkPackage` — its items only), plus ``auto_split`` (whether the split was
    proposed by the threshold). ``split_keys`` (parent trades) forces a split even below the
    threshold — the human "Split by section" affordance; a trade absent from it stays whole
    unless it crosses the threshold."""
    units: list[dict] = []
    for pkg in scope.packages:
        auto = should_split(pkg)
        forced = split_keys is not None and pkg.trade in split_keys
        if (auto or forced) and pkg.sections:
            for sec in pkg.sections:
                items = [it for it in pkg.sor_items if (it.section or "") == sec.code]
                if not items:
                    continue
                summary = _summary(sec.code, sec.title, items)
                sub = TradeWorkPackage(
                    trade=pkg.trade, scope_summary=summary, sor_items=items,
                    source_refs=pkg.source_refs, sections=[sec],
                )
                units.append({
                    "package_key": f"{pkg.trade}:{sec.code}", "trade": pkg.trade,
                    "section": sec.code, "section_title": sec.title, "scope_summary": summary,
                    "package": sub, "auto_split": auto,
                })
        else:
            sole = pkg.sections[0] if len(pkg.sections) == 1 else None
            units.append({
                "package_key": pkg.trade, "trade": pkg.trade,
                "section": sole.code if sole else None, "section_title": sole.title if sole else "",
                "scope_summary": pkg.scope_summary, "package": pkg, "auto_split": False,
            })
    return units
