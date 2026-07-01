"""Approval-driven leveling replies: the columns equal the firms approved in dispatch."""

from pipeline.stage_04_level.collect import (
    BENCHMARK_ID,
    build_replies_from_approvals,
    load_sor_templates,
)

_SOR = "cases/scenarios/drainage_sor.json"
GOLD = "gold-ram-engineering-development-limited-9bbd"
DRIL = "driltech-ground-engineering-limited-a721"
KAIWAI = "kai-wai-engineering-survey-and-geophysics-limited-3f7b"
FUGRO = "fugro-geotechnical-services-limited-af2a"
SIXENSE = "sixense-limited-5d2c"


def _ids(replies, trade):
    return [r.firm_id for r in replies if r.trade == trade]


def test_benchmark_is_always_the_first_column_of_a_section():
    sor = load_sor_templates(_SOR)
    replies = build_replies_from_approvals({"field_installations": [KAIWAI, FUGRO]}, sor)
    assert _ids(replies, "field_installations")[0] == BENCHMARK_ID


def test_pinned_firms_get_their_real_offer():
    sor = load_sor_templates(_SOR)
    replies = build_replies_from_approvals(
        {"geophysical_survey": [SIXENSE], "field_installations": [KAIWAI]}, sor
    )
    sixense = next(r for r in replies if r.firm_id == SIXENSE)
    kaiwai = next(r for r in replies if r.firm_id == KAIWAI)
    assert sixense.claimed_total == 240340.0  # Sixense's real J offer
    assert kaiwai.claimed_total == 153450.0  # Kai Wai's real H offer
    # the conductivity probe (H14c) above-benchmark outlier survives the build
    assert next(li.rate for li in kaiwai.line_items if li.item_ref == "H14c") == 30000.0


def test_non_pinned_firms_take_templates_in_approval_order():
    sor = load_sor_templates(_SOR)
    # field testing has no pinned firm: the first approved firm gets the clean template,
    # the second gets the arithmetic-flip template (the column names follow approval).
    a = build_replies_from_approvals({"field_testing": [GOLD, DRIL]}, sor)
    assert {r.firm_id: r.claimed_total for r in a if r.trade == "field_testing"}[GOLD] == 1114790.0
    assert {r.firm_id: r.claimed_total for r in a if r.trade == "field_testing"}[DRIL] == 1107690.0
    # reverse the approval order and the templates follow the order, not the firm
    b = build_replies_from_approvals({"field_testing": [DRIL, GOLD]}, sor)
    assert {r.firm_id: r.claimed_total for r in b if r.trade == "field_testing"}[DRIL] == 1114790.0


def test_section_is_capped_at_benchmark_plus_two_firms():
    sor = load_sor_templates(_SOR)
    replies = build_replies_from_approvals(
        {"field_installations": [KAIWAI, FUGRO, "extra-firm-x", "extra-firm-y"]}, sor
    )
    fi = _ids(replies, "field_installations")
    assert fi[0] == BENCHMARK_ID
    assert len(fi) == 3  # benchmark + exactly two firms


def test_a_section_with_no_approvals_is_skipped():
    sor = load_sor_templates(_SOR)
    replies = build_replies_from_approvals(
        {"field_testing": [GOLD, DRIL], "geophysical_survey": []}, sor
    )
    assert _ids(replies, "geophysical_survey") == []  # nothing approved -> skipped (no lone benchmark)
    assert _ids(replies, "field_testing")  # the approved section is still built


def test_benchmark_id_is_not_counted_as_an_approved_firm():
    sor = load_sor_templates(_SOR)
    # even if the benchmark id leaks into the approvals, it is not double-counted as a firm
    replies = build_replies_from_approvals({"field_testing": [BENCHMARK_ID, GOLD, DRIL]}, sor)
    ft = _ids(replies, "field_testing")
    assert ft[0] == BENCHMARK_ID and ft.count(BENCHMARK_ID) == 1
    assert GOLD in ft and DRIL in ft
