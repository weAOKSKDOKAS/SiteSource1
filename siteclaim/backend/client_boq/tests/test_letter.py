"""Unit tests for ESTIMATE s06 (offer letter): template section order, code-injected price/fields,
and Appendix A sourcing (confirmed departures verbatim + source-tagged; dismissed absent)."""

from __future__ import annotations

from client_boq.estimate.run import assemble_estimate, load_demo_schedule
from client_boq.estimate.s06_offer import build_letter
from client_boq.models import (
    STATUS_CONFIRMED,
    STATUS_DISMISSED,
    DepartureItem,
    DepartureRegister,
    EstimateScope,
    LetterMeta,
    ScopeReviewResult,
)

_CONFIRMED = "Liquidated damages capped at 10% of the Subcontract value"
_DISMISSED = "Delete the fitness-for-purpose warranty entirely"


def _letter():
    estimate = assemble_estimate("demo-windows", 15.0, load_demo_schedule())
    scope = EstimateScope(set_id="demo-windows", draft=ScopeReviewResult(summary="Facade package"),
                          approved=True)
    register = DepartureRegister(set_id="demo-windows", items=[
        DepartureItem(item=1, criterion_id="TP-04", clause_area="LD", proposed_position=_CONFIRMED,
                      status=STATUS_CONFIRMED),
        DepartureItem(item=2, criterion_id="SQD-06", clause_area="Warranties", proposed_position=_DISMISSED,
                      status=STATUS_DISMISSED),
    ])
    meta = LetterMeta(project="Harbour Crest", client_name="Alpha Developments", date="1 July 2026",
                      ref="HC-FACADE-01", validity_days=90)
    return build_letter(scope, estimate, register, meta), estimate


def test_price_string_equals_persisted_price_exactly() -> None:
    letter, estimate = _letter()
    assert letter.price == estimate.totals.price
    assert letter.price_str == f"${estimate.totals.price:,.2f}" == "$6,985,002.25"
    assert letter.price_str in letter.markdown            # the price appears in the rendered letter


def test_template_section_order_preserved() -> None:
    md = _letter()[0].markdown
    markers = [
        "**SiteSource Contracting Ltd**",              # company header
        "REF: HC-FACADE-01",                           # injected REF
        "Dear Alpha Developments,",                    # injected client
        "excluding GST",                               # price line
        "**Inclusions**",
        "**Exclusions**",
        "Additional conditions that apply to our offer are included in Appendix A.",
        "This quotation is valid for 90 days",         # injected validity
        "**Pricing Schedule**",
        "**Detailed Scope Breakdown**",
        "Best Regards,",
        "**Appendix A - Conditions of Offer**",
    ]
    positions = [md.find(m) for m in markers]
    assert all(p >= 0 for p in positions), [m for m, p in zip(markers, positions) if p < 0]
    assert positions == sorted(positions), "template sections are out of order"


def test_pricing_schedule_table_has_activity_totals() -> None:
    letter, estimate = _letter()
    # Injected from the estimate: the direct activities and their totals, plus the offer price row.
    assert "A1" in letter.markdown and "$1,340,600.00" in letter.markdown
    assert {r.item_id for r in letter.pricing_schedule} == {a.item_id for a in estimate.activities}
    assert f"**{letter.price_str}**" in letter.markdown


def test_appendix_confirmed_verbatim_and_source_tagged_dismissed_absent() -> None:
    letter = _letter()[0]
    register_items = [a for a in letter.appendix if a.source == "register"]
    draft_items = [a for a in letter.appendix if a.source == "draft"]
    # Confirmed departure appears verbatim, tagged register, and BEFORE the AI-drafted conditions.
    assert any(a.text == _CONFIRMED for a in register_items)
    assert letter.appendix[0].source == "register" and draft_items
    assert _CONFIRMED in letter.markdown
    # The dismissed item never appears — not in the appendix, not anywhere in the letter.
    assert all(_DISMISSED not in a.text for a in letter.appendix)
    assert _DISMISSED not in letter.markdown
