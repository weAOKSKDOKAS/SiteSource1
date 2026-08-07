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


def _cover_all_items(sections: list, items: list) -> list:
    """``sections``, extended so EVERY item's section code has a unit to be routed into.

    A package can declare fewer sections than its items span — a merge of two packages where only
    one declared any, or a split whose section metadata did not survive. The splitting loop routes
    an item only if its code matches a declared section, so an uncovered code is a SILENT DROP: the
    items simply never appear in any unit and never reach a firm. Found by the routing tests, on a
    merge that left 117 of 148 items unrouted.

    Declared sections keep their order and their titles; the derived ones are appended, so nothing
    a real split produced is reordered.
    """
    declared = {(s.code or "").strip() for s in sections}
    extra = [s for s in _sections_from_items(items) if s.code not in declared]
    return list(sections) + extra


def _sections_from_items(items: list) -> list:
    """The sections a package's ITEMS declare, in first-seen order, when the package declares none.

    ``annotate_sections`` normally fills ``sections``, but it can come back empty — a scope split
    whose section titles did not survive, or a package assembled by another path. Before this, an
    empty ``sections`` sent a package with 145 items straight down the whole-trade branch: it
    produced a unit with ``package_key = trade`` and ``section = None``, sitting beside its own
    ``trade:2`` .. ``trade:6`` siblings and counting the same items a second time.

    Deriving them here is the same rule ``drafts.plan_for_firms`` already applies for a suffix-less
    package, so a unit that ought to split always can.
    """
    from schemas.models import SectionMeta

    counts: dict[str, int] = {}
    for it in items:
        code = (getattr(it, "section", "") or "").strip()
        if code:
            counts[code] = counts.get(code, 0) + 1
    return [SectionMeta(code=code, title="", item_count=n) for code, n in counts.items()]


def _merge_same_trade(pkgs: list[TradeWorkPackage]) -> TradeWorkPackage:
    """Several packages that normalise to ONE trade, as one package.

    Two packages can carry the same ``trade``: the scope split is an LLM output and it normalises
    through ``rules_engine.taxonomy``, so "Ground Investigation" and "Ground Investigation
    Fieldworks" both land on ``ground_investigation``. Nothing downstream survives that — every
    consumer keys on the trade or the package_key and a duplicate SILENTLY overwrites its twin:

        shortlist.py:69   {pkg.trade: cross_reference(...) for pkg in scope.packages}
        drafts.py:128     {p.trade: p for p in scope.packages}
        api.py:1637       {u["package_key"]: u["package"].sor_items for u in route_units(scope)}

    In each, the LAST wins and the other package's items become invisible. Merging here means the
    routable unit is derived once per TRADE, so a duplicate can no longer produce two units with
    one key — or a whole-trade unit beside its own section units.

    A single-package trade returns that package UNCHANGED (identity preserved), so nothing that
    works today reads differently.
    """
    if len(pkgs) == 1:
        return pkgs[0]
    items = [it for p in pkgs for it in p.sor_items]
    sections: list = []
    seen: set[str] = set()
    for p in pkgs:
        for sec in p.sections:
            if sec.code not in seen:
                seen.add(sec.code)
                sections.append(sec)
    return pkgs[0].model_copy(update={
        "sor_items": items,
        "sections": sections or _sections_from_items(items),
        "source_refs": list(dict.fromkeys(r for p in pkgs for r in p.source_refs)),
    })


def assert_unique_keys(units: list[dict]) -> list[dict]:
    """THE INVARIANT, checked rather than assumed: one ``package_key``, one unit.

    Grouping by trade is what makes a duplicate unreachable, so this is a BACKSTOP — it exists
    because the cost of a duplicate slipping through is invisible rather than loud. Every consumer
    keys on ``package_key``, several through a dict comprehension where the last wins:

        shortlist.py:69   {pkg.trade: cross_reference(...) for pkg in scope.packages}
        drafts.py:128     {p.trade: p for p in scope.packages}
        api.py:1637       {u["package_key"]: u["package"].sor_items for u in route_units(scope)}

    A duplicate there does not fail — it silently drops one unit's items, and the package reaches a
    firm carrying nothing. Failing here names the defect at its source instead.
    """
    keys = [u["package_key"] for u in units]
    if len(keys) != len(set(keys)):
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        raise ValueError(
            f"route_units produced duplicate package_key(s) {dupes}. Every consumer keys on it, so "
            f"a duplicate silently drops one unit's items. This is a defect in route_units, not in "
            f"the scope it was given.")
    return units


def _assert_every_item_routed(units: list[dict], scope: ScopePackages) -> None:
    """No item routed twice, and no item routed nowhere.

    Two units covering the same item means it is enquired twice, or priced twice, or both. An item
    in no unit is scope that silently never reaches a firm — the worse of the two, because it looks
    like a smaller tender rather than a broken one. Both are invisible downstream, so they are
    checked here.
    """
    routed = [it.item_ref for u in units for it in u["package"].sor_items]
    if len(routed) != len(set(routed)):
        dupes = sorted({r for r in routed if routed.count(r) > 1})[:8]
        raise ValueError(f"route_units routed the same item into more than one unit: {dupes}")
    # Only items that HAVE a section code. A SECTION-LESS item is legitimately unroutable in a
    # split tender — there is no section to route it into — and the design surfaces it downstream as
    # an EXTRA rather than inventing a unit for it (`stage_04_level/route_items.py`). What must
    # never happen is an item WITH a code that no unit covers: that is a section the split forgot to
    # declare, and its items vanish.
    available = [it.item_ref for p in scope.packages for it in p.sor_items
                 if (getattr(it, "section", "") or "").strip()]
    missing = sorted(set(available) - set(routed))
    if missing:
        raise ValueError(
            f"route_units left {len(missing)} item(s) with a section in no unit at all: "
            f"{missing[:8]}. Scope that is routed nowhere never reaches a firm, and reads as a "
            f"smaller tender rather than a broken one.")


def route_units(scope: ScopePackages, *, split_keys: set[str] | None = None) -> list[dict]:
    """The routable units for a scope. Each unit: ``package_key`` (``trade`` or
    ``trade:SECTION``), ``trade`` (the parent, for signal + shortlist), ``section`` /
    ``section_title``, ``scope_summary``, and ``package`` (a section-scoped
    :class:`TradeWorkPackage` — its items only), plus ``auto_split`` (whether the split was
    proposed by the threshold). ``split_keys`` (parent trades) forces a split even below the
    threshold — the human "Split by section" affordance; a trade absent from it stays whole
    unless it crosses the threshold."""
    # ONE UNIT SHAPE PER TRADE, and every key distinct. Packages are grouped by trade first, so a
    # trade that appears twice in the split is decided ONCE — it can no longer produce a whole-trade
    # unit beside its own section units, which is what put a keyless card describing "Section 1,
    # 30 items" next to `trade:2 .. trade:6` while reporting the whole trade's 145 bill lines.
    by_trade: dict[str, list[TradeWorkPackage]] = {}
    for pkg in scope.packages:
        by_trade.setdefault(pkg.trade, []).append(pkg)

    units: list[dict] = []
    for trade, group in by_trade.items():
        pkg = _merge_same_trade(group)
        auto = should_split(pkg)
        forced = split_keys is not None and pkg.trade in split_keys
        # Sections are DERIVED when the package declares none, so a package big enough to split
        # always can — `and pkg.sections` used to send it down the whole-trade branch instead — and
        # EXTENDED to cover every item's code, so splitting can never orphan an item.
        sections = (_cover_all_items(pkg.sections, pkg.sor_items)
                    if (auto or forced) else pkg.sections)
        if (auto or forced) and sections:
            for sec in sections:
                if not (sec.code or "").strip():
                    continue  # never route an empty-section unit (the section code is the unit)
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
            sole = sections[0] if len(sections) == 1 else None
            units.append({
                "package_key": pkg.trade, "trade": pkg.trade,
                "section": sole.code if sole else None, "section_title": sole.title if sole else "",
                "scope_summary": pkg.scope_summary, "package": pkg, "auto_split": False,
            })

    assert_unique_keys(units)
    _assert_every_item_routed(units, scope)
    return units
