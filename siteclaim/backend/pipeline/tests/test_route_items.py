"""The deterministic reply-line → SoR-section matcher (leveling fix, Commit 2). Pure Layer 1 —
no DB, no model, no tesseract."""

from pipeline.stage_04_level.route_items import (
    normalize_ref,
    route_items,
    route_reply_lines,
    section_totals,
    token_set_ratio,
)
from schemas.models import BidLineItem, ScopePackages, SectionMeta, SorItem, TradeWorkPackage


def _scope() -> ScopePackages:
    # One GI trade spanning FOUR sections (> 3) so route_units splits it — the multi-section shape
    # behind the 70-item bug; each section is its own routed/dispatched unit.
    return ScopePackages(
        project_name="GE/2026/14",
        packages=[
            TradeWorkPackage(
                trade="ground_investigation", scope_summary="GI",
                sor_items=[
                    SorItem(item_ref="G4", description="Trial pit excavation in soil", section="G"),
                    SorItem(item_ref="H12", description="Field vane shear test in soft clay", section="H"),
                    SorItem(item_ref="I3", description="Borehole log record", section="I"),
                    SorItem(item_ref="J1", description="Install standpipe piezometer", section="J"),
                    SorItem(item_ref="J5(a)", description="Standpipe reading, weekly", section="J"),
                ],
                sections=[SectionMeta(code=c, item_count=n) for c, n in [("G", 1), ("H", 1), ("I", 1), ("J", 2)]],
            )
        ],
    )


def _line(item_ref, description="", rate=None):
    return BidLineItem(item_ref=item_ref, description=description, rate=rate)


def test_normalize_ref_unifies_subitem_forms():
    assert normalize_ref("J5(a)") == normalize_ref("J5A") == normalize_ref("J5.a") == "J5A"
    assert normalize_ref(" h12 ") == "H12"


def test_refs_route_to_their_own_sections():
    routed = route_items([_line("G4"), _line("H12"), _line("J1")], _scope())
    got = {r.line.item_ref: (r.section, r.package_key, r.method) for r in routed}
    assert got["G4"] == ("G", "ground_investigation:G", "ref")
    assert got["H12"] == ("H", "ground_investigation:H", "ref")
    assert got["J1"] == ("J", "ground_investigation:J", "ref")


def test_subitem_ref_form_still_matches_its_canonical_item():
    (routed,) = route_items([_line("J5A")], _scope())  # returned as J5A; canonical is J5(a)
    assert routed.package_key == "ground_investigation:J" and routed.canonical_ref == "J5(a)"


def test_garbled_ref_matches_by_description_above_threshold():
    # The ref is unreadable but the description clearly names canonical H12.
    (routed,) = route_items([_line("H1Z", description="Field vane shear test, soft clay")], _scope())
    assert routed.method == "description"
    assert routed.package_key == "ground_investigation:H" and routed.canonical_ref == "H12"


def test_unknown_ref_with_unrelated_description_is_an_extra():
    (routed,) = route_items([_line("X9", description="Site office cleaning and welfare")], _scope())
    assert routed.method == "unmatched" and routed.package_key is None


def test_route_reply_lines_groups_by_section_and_flags_extras():
    lines = [_line("G4"), _line("H12"), _line("J1"), _line("X9", description="totally unrelated")]
    result = route_reply_lines(lines, _scope())
    assert set(result.by_key) == {"ground_investigation:G", "ground_investigation:H", "ground_investigation:J"}
    assert [li.item_ref for li in result.by_key["ground_investigation:G"]] == ["G4"]
    assert [li.item_ref for li in result.extras] == ["X9"]  # surfaced, not folded into a section


def test_section_totals_counts_canonical_items_per_key():
    assert section_totals(_scope()) == {
        "ground_investigation:G": 1, "ground_investigation:H": 1,
        "ground_investigation:I": 1, "ground_investigation:J": 2,
    }


def test_keys_match_the_tenders_routed_units_whole_vs_split():
    # A single-section trade routes WHOLE, so its reply groups under the bare trade key its enquiry
    # was dispatched on (field_installations) — never a synthesised field_installations:H.
    whole = ScopePackages(packages=[TradeWorkPackage(
        trade="field_installations", scope_summary="FI",
        sor_items=[SorItem(item_ref=f"H{n}", section="H") for n in range(1, 6)],
        sections=[SectionMeta(code="H", item_count=5)])])
    result = route_reply_lines([_line(f"H{n}") for n in range(1, 6)], whole)
    assert set(result.by_key) == {"field_installations"}  # bare trade — the routed/dispatched unit
    # The four-section GI trade splits, so its reply groups per section unit.
    assert set(route_reply_lines([_line("G4"), _line("H12"), _line("J1")], _scope()).by_key) == {
        "ground_investigation:G", "ground_investigation:H", "ground_investigation:J",
    }


def test_a_section_outside_every_routed_unit_becomes_an_extra():
    # In a SPLIT tender a canonical item whose section is in NO routed unit (a section-less stray)
    # routes nowhere -> surfaced as an extra, never invented into a unit.
    scope = ScopePackages(project_name="P", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sor_items=[
            SorItem(item_ref="G4", section="G"), SorItem(item_ref="H12", section="H"),
            SorItem(item_ref="I3", section="I"), SorItem(item_ref="J1", section="J"),
            SorItem(item_ref="ZZ9", section=""),  # a stray with no section -> no split unit contains it
        ],
        sections=[SectionMeta(code=c, item_count=1) for c in ("G", "H", "I", "J")])])
    result = route_reply_lines([_line("H12"), _line("ZZ9")], scope)
    assert set(result.by_key) == {"ground_investigation:H"}  # H12 routes to its section unit
    assert [li.item_ref for li in result.extras] == ["ZZ9"]  # the section-less item has no unit


def test_token_set_ratio_is_deterministic_and_bounded():
    assert token_set_ratio("Rotary drilling in rock", "Rotary drilling, rock") >= 0.8
    assert token_set_ratio("", "anything") == 0.0
    assert token_set_ratio("site office", "rotary drilling") == 0.0


def test_reply_groups_into_corrected_sections_with_no_phantom_hs():
    # After the section repair, the canonical items all carry section H, so a reply spanning the
    # corrupted refs collapses into the single field_installations:H bucket — no :HS, no empty key.
    from pipeline.stage_01_ingest.ingest import annotate_sections

    raw = ScopePackages(packages=[TradeWorkPackage(
        trade="field_installations", scope_summary="Field Installations",
        sor_items=[SorItem(item_ref=r) for r in ["1(a)", "H4", "HS", "H6"]])])
    scope = annotate_sections(raw, "SECTION H : FIELD INSTALLATIONS")
    result = route_reply_lines([_line(r) for r in ["1(a)", "H4", "HS", "H6"]], scope)
    # A single-section trade routes WHOLE, so the aligned key is the bare trade (its dispatched key)
    # — no :HS, no empty, and no synthesised :H.
    assert set(result.by_key) == {"field_installations"}
    assert [li.item_ref for li in result.by_key["field_installations"]] == ["1(a)", "H4", "HS", "H6"]
    assert result.extras == []  # every line matched a canonical item; none dropped
