"""Re-routing must be idempotent: route → confirm → RE-route → RE-confirm.

Neither defect appeared on the first pass. The Route screen was correct, and the shortlist held its
packages. What broke involved **state left by the previous run**, so these tests drive the sequence
rather than the end state.

DEFECT 1 — a whole-trade unit coexisting with its own section units. `route_units` has two shapes,
`package_key = trade` or `trade:SECTION`, chosen by an `if/else`. Two things could produce both at
once for one trade, and both are now impossible:

* **Two packages sharing a trade.** The scope split is an LLM output normalised through
  `rules_engine.taxonomy`, so "Ground Investigation" and "Ground Investigation Fieldworks" both land
  on `ground_investigation`. One package could split and the other stay whole. Worse, every consumer
  keys on the trade through a dict comprehension — `shortlist.py:69`, `drafts.py:128`, `api.py:1637`
  — where the LAST wins and the other package's items become invisible.
* **A package with items but no `sections`.** `if (auto or forced) and pkg.sections` sent a
  145-item package down the whole-trade branch, producing a keyless unit counting the same items
  its `trade:2..6` siblings already counted. That matches the live card exactly: it described
  "Section 1 — General and Preliminaries (30 items)" and reported 145 bill lines.

DEFECT 2 — only two of six sublet units reached the shortlist. `write_proposal` replaces
`package_routes` wholesale, but `bridge_route_decisions` is a SEPARATE table and nothing cleared it.
After a re-route that changes the keys, the stale rows survive and the new keys have no decision;
`sublet_packages` is read straight off those rows and the sourcing screen filters the CURRENT
proposal by them, so a stale key matches nothing and a new key is absent.

They are RELATED but not the same defect: defect 1 changes the key shape, which is what leaves
defect 2's decisions orphaned. Either can occur alone — a re-route that changes nothing but the
thresholds also re-keys.
"""

import pytest

from pipeline.routing.split import route_units, should_split
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

# The real bill's shape: nine bills, GI holding 1..6 (145 items) and the rest elsewhere.
SECTION_SIZES = {"1": 30, "2": 28, "3": 14, "4": 28, "5": 4, "6": 41}


def _items(code: str, n: int, start: int = 1) -> list[SorItem]:
    return [SorItem(item_ref=f"{code}.{i}", description=f"item {code}.{i}", section=code)
            for i in range(start, start + n)]


def _gi(sections: dict[str, int] | None = None, *, declare_sections: bool = True,
        trade: str = "ground_investigation", summary: str = "Ground investigation",
        start: int = 1) -> TradeWorkPackage:
    # `start` keeps item refs distinct between two packages that share a section — a real state
    # (the split can put some of a section's items in one package and some in another) and NOT the
    # same thing as two packages holding the identical item, which no split produces.
    sizes = SECTION_SIZES if sections is None else sections
    items = [it for code, n in sizes.items() for it in _items(code, n, start)]
    metas = ([SectionMeta(code=c, title=f"Bill {c}", item_count=n) for c, n in sizes.items()]
             if declare_sections else [])
    return TradeWorkPackage(trade=trade, scope_summary=summary, sor_items=items, sections=metas)


def _scope(*pkgs: TradeWorkPackage) -> ScopePackages:
    return ScopePackages(project_name="Contract No. ND/2025/04", packages=list(pkgs))


def _keys(units) -> list[str]:
    return [u["package_key"] for u in units]


# -- the invariant, stated once ---------------------------------------------------------------------
def _assert_units_are_sane(units, scope):
    """A unit is one shape or the other; keys are unique; items are counted exactly once."""
    keys = _keys(units)
    assert len(keys) == len(set(keys)), f"duplicate package_key: {keys}"

    for trade in {u["trade"] for u in units}:
        mine = [u for u in units if u["trade"] == trade]
        whole = [u for u in mine if u["package_key"] == trade]
        sectioned = [u for u in mine if u["package_key"].startswith(f"{trade}:")]
        assert not (whole and sectioned), (
            f"trade {trade!r} has BOTH a whole-trade unit and section units: {[u['package_key'] for u in mine]}")

    routed = [it.item_ref for u in units for it in u["package"].sor_items]
    assert len(routed) == len(set(routed)), "an item is routed into more than one unit"
    available = {it.item_ref for p in scope.packages for it in p.sor_items}
    assert set(routed) == available, (
        f"items unrouted: {sorted(available - set(routed))[:8]}")


# -- defect 1, both mechanisms ------------------------------------------------------------------------
def test_two_packages_sharing_a_trade_produce_one_shape_and_no_duplicate_keys():
    """The scope split normalises trades, so a collision is a real state, not a hypothetical."""
    scope = _scope(
        _gi({"1": 30}, summary="Section 1 — General and Preliminaries (30 items)"),
        _gi({"2": 28, "3": 14, "4": 28, "5": 4, "6": 41}, summary="Ground Investigation Fieldworks"),
    )
    units = route_units(scope)
    _assert_units_are_sane(units, scope)

    assert "ground_investigation" not in _keys(units), "no keyless whole-trade card"
    assert set(_keys(units)) == {f"ground_investigation:{c}" for c in SECTION_SIZES}


def test_the_live_card_that_described_thirty_items_and_reported_one_hundred_and_forty_five():
    """The exact reported shape: one package's summary left over from a section, the whole trade's
    items, and no sections to split on."""
    pkg = _gi(declare_sections=False, summary="Section 1 — General and Preliminaries (30 items)")
    assert len(pkg.sor_items) == 145 and pkg.sections == []
    assert should_split(pkg) is True, "145 items is well past the threshold"

    units = route_units(_scope(pkg))
    _assert_units_are_sane(units, _scope(pkg))

    assert "ground_investigation" not in _keys(units)
    assert len(units) == 6, "sections derived from the items, one unit each"
    assert all(u["section"] for u in units), "every unit carries its section"


def test_a_package_with_no_sections_and_few_items_still_stays_whole():
    """The derivation must not turn every small package into a split — the whole-trade shape is
    correct for a focused package and every demo scenario depends on it."""
    small = TradeWorkPackage(trade="joinery_fitting_out", scope_summary="Loose furniture",
                             sor_items=_items("J", 4), sections=[])
    units = route_units(_scope(small))

    assert _keys(units) == ["joinery_fitting_out"]
    assert units[0]["section"] is None


def test_a_single_package_trade_is_returned_unchanged():
    """Identity preserved, so nothing that works today reads differently."""
    pkg = _gi({"2": 5})
    units = route_units(_scope(pkg))
    assert units[0]["package"] is pkg


# -- the sequence -------------------------------------------------------------------------------------
@pytest.mark.parametrize("run", [1, 2, 3])
def test_routing_the_same_scope_repeatedly_gives_the_same_units(run):
    """f(f(x)) == f(x). A re-route reads the persisted scope and re-derives; if the derivation were
    not idempotent the second pass would differ, which is what a re-run defect is."""
    scope = _scope(_gi(), _gi({"9": 12}, trade="builders_work", summary="Builders work"))
    first = route_units(scope)
    for _ in range(run):
        again = route_units(scope)
        assert _keys(again) == _keys(first)
        _assert_units_are_sane(again, scope)


def test_a_forced_split_and_then_an_unforced_reroute_do_not_leave_two_shapes():
    """The operator presses "Split by section", then re-routes without it. Each call must produce
    ONE shape — the danger is a consumer holding units from both."""
    scope = _scope(_gi({"2": 5}))
    forced = route_units(scope, split_keys={"ground_investigation"})
    plain = route_units(scope)

    _assert_units_are_sane(forced, scope)
    _assert_units_are_sane(plain, scope)
    assert _keys(forced) == ["ground_investigation:2"]
    assert _keys(plain) == ["ground_investigation"], "below the threshold, unforced, stays whole"
    assert set(_keys(forced)) & set(_keys(plain)) == set(), (
        "the two shapes share no key — which is exactly why a stale decision cannot be re-used")


def test_every_item_of_the_bill_is_routed_exactly_once():
    """Two units covering the same items means those items are enquired twice, or priced twice."""
    scope = _scope(_gi())
    units = route_units(scope)
    counted = sum(len(u["package"].sor_items) for u in units)

    assert counted == 145 == sum(SECTION_SIZES.values())
    _assert_units_are_sane(units, scope)


def test_duplicate_keys_fail_loudly_at_their_source():
    """The backstop itself.

    Grouping by trade makes a duplicate unreachable through `route_units`, which is why this is
    tested directly rather than provoked: a guard that cannot be reached is still worth having when
    the failure it guards against is INVISIBLE. Every consumer keys on `package_key` through a dict
    comprehension where the last wins, so a duplicate would not raise — it would silently empty one
    package and send a firm an enquiry with no items in it.
    """
    from pipeline.routing.split import assert_unique_keys

    ok = [{"package_key": "a"}, {"package_key": "b"}]
    assert assert_unique_keys(ok) is ok

    with pytest.raises(ValueError, match="duplicate package_key"):
        assert_unique_keys([{"package_key": "a"}, {"package_key": "a"}])


def test_route_units_never_produces_a_duplicate_however_the_scope_is_shaped():
    """The property the backstop backs up, across every shape that has caused trouble."""
    shapes = [
        _scope(_gi(), _gi({"9": 12}, trade="builders_work")),
        _scope(_gi({"1": 30}), _gi({"2": 28, "3": 14}, start=400)),
        _scope(_gi(declare_sections=False), _gi({"2": 3}, start=300)),
        _scope(_gi({"2": 5}), _gi({"2": 5}, start=100)),
        _scope(_gi({"2": 5}), _gi({"2": 5}, start=100), _gi({"2": 5}, start=200)),
    ]
    for scope in shapes:
        units = route_units(scope)
        _assert_units_are_sane(units, scope)


# -- what the shortlist actually receives ----------------------------------------------------------------
def test_every_sublet_unit_reaches_the_shortlist_with_its_own_items():
    """The shortlist keys `per_trade` on `pkg.trade`, and the sourcing screen sets that to the
    unit's `package_key`. Two units sharing a key would collapse into one entry — six sublet units
    arriving as two is exactly that shape."""
    scope = _scope(
        _gi({"1": 30}, summary="Section 1 — General and Preliminaries (30 items)"),
        _gi({"2": 28, "3": 14, "4": 28, "5": 4, "6": 41}),
    )
    units = route_units(scope)
    # What `sourcingScope` builds: one package per sublet unit, keyed by package_key.
    sourcing = ScopePackages(project_name=scope.project_name, packages=[
        TradeWorkPackage(trade=u["package_key"], scope_summary=u["scope_summary"],
                         sor_items=u["package"].sor_items, sections=u["package"].sections)
        for u in units
    ])
    per_trade_keys = {p.trade for p in sourcing.packages}

    assert len(per_trade_keys) == len(sourcing.packages) == 6, "no key collapses"
    assert all(p.sor_items for p in sourcing.packages), "no package arrives empty"
