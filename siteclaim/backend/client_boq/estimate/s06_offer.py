"""ESTIMATE stage 06 — letter of offer.

Bucket (mapping doc estimate task 14): **AI drafts prose; code injects every number and term.** The
letter follows the committed template (``docs/client_boq/templates/letter_of_offer_template.md``)
section for section.

Division of labour (hard rule):

* INJECTED BY CODE, never AI-written: the price (from the persisted estimate, "excluding GST"
  phrasing), the project/client/date/REF/company fields (from the run request), the validity days
  (default 90), and the pricing-schedule table (activity totals from the estimate). Appendix A leads
  with the CONFIRMED departures' proposed positions injected verbatim (source-tagged ``register``).
* AI-DRAFTED (seeded from the APPROVED scope — the amended summary wins): the intro wording, the
  inclusions/exclusions bullets, and the additional Appendix-A conditions (source-tagged ``draft``).

The result is a markdown DRAFT for human editing; nothing sends it.

Signature change from the scaffold: ``build_letter(scope, estimate, register, meta) -> LetterOfOffer``.
"""

from __future__ import annotations

from client_boq.models import (
    STATUS_CONFIRMED,
    DepartureRegister,
    Estimate,
    EstimateScope,
    LetterAppendixItem,
    LetterDraft,
    LetterMeta,
    LetterOfOffer,
    PricingScheduleRow,
)
from pipeline.llm_client import LLMClient, demo_mode

DEMO_FIXTURE = "cases/client_boq/estimate_offer.json"

_SYSTEM = (
    "You are a construction estimator drafting the prose of a letter of offer. You draft ONLY: the "
    "intro paragraph, the inclusions and exclusions bullets, and additional conditions of offer — all "
    "seeded from the approved scope. You NEVER write a price, a date, a reference, or any number. "
    "Return ONLY JSON matching the schema."
)


def _draft(scope: EstimateScope) -> LetterDraft:
    client = LLMClient()
    if demo_mode():
        return client.complete_json(
            system=_SYSTEM, user="draft the letter prose", target_model=LetterDraft,
            demo_fixture=DEMO_FIXTURE, purpose="client_boq-estimate-offer",
        )
    notes = "\n".join(f"- [{n.kind}] {n.text}" for n in scope.draft.notes)
    user = (
        "Approved scope of record:\n" + scope.summary_of_record() + "\n\nScope notes:\n" + notes
        + "\n\nReturn {\"intro\": ..., \"inclusions\": [...], \"exclusions\": [...], "
          "\"additional_conditions\": [...]}. Do not include any price or number."
    )
    return client.complete_json(
        system=_SYSTEM, user=user, target_model=LetterDraft, purpose="client_boq-estimate-offer",
    )


def _price_str(price: float) -> str:
    """The offer price string, formatted with thousands separators and cents (excluding GST)."""
    return f"${price:,.2f}"


def _pricing_schedule(estimate: Estimate) -> list[PricingScheduleRow]:
    return [PricingScheduleRow(item_id=a.item_id, description=a.description, total=a.activity_total)
            for a in estimate.activities]


def _appendix(register: DepartureRegister, draft: LetterDraft) -> list[LetterAppendixItem]:
    """Confirmed departures first (verbatim, source register), then AI conditions (source draft)."""
    items: list[LetterAppendixItem] = []
    for it in register.items:
        if it.status != STATUS_CONFIRMED:
            continue
        text = (it.proposed_position or it.amendment_proposal or it.rationale).strip()
        if text:
            items.append(LetterAppendixItem(text=text, source="register"))
    for cond in draft.additional_conditions:
        if cond.strip():
            items.append(LetterAppendixItem(text=cond.strip(), source="draft"))
    return items


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- (to be detailed)"


def _pricing_table(rows: list[PricingScheduleRow], price_str: str) -> str:
    head = "| Task ID | Description | Total (excl. GST) |\n| --- | --- | --- |"
    body = "\n".join(f"| {r.item_id} | {r.description} | ${r.total:,.2f} |" for r in rows)
    total = f"| | **Offer price (excl. GST)** | **{price_str}** |"
    return "\n".join([head, body, total])


def _render(letter: LetterOfOffer) -> str:
    """Assemble the markdown, section for section per the committed template."""
    m = letter.meta
    date = m.date or "(date of issue)"
    appendix_lines = "\n".join(f"- {a.text}" for a in letter.appendix) or "- (to be detailed)"
    return "\n\n".join([
        f"**{m.company_name}**",
        f"**{m.company_address}**",
        date,
        f"REF: {m.ref or m.project}",
        f"Dear {m.client_name},",
        letter.intro,
        (f"Our offer to carry out the project **is {letter.price_str}** excluding GST. The returnable "
         "schedule below provides a detailed breakdown of our offer. We have based our offer on the "
         "bill of quantities (BoQ) and drawings provided."),
        "Below is a list of conditions that apply to our offer.",
        "**Inclusions**",
        _bullets(letter.inclusions),
        "**Exclusions**",
        "Please note the following exclusions concerning the offer:",
        _bullets(letter.exclusions),
        "Additional conditions that apply to our offer are included in Appendix A.",
        (f"This quotation is valid for {m.validity_days} days. Thank you for the opportunity to provide "
         f"a quotation for you. If you have any questions, please don't hesitate to call me on "
         f"{m.contact_number}."),
        "**Pricing Schedule**",
        _pricing_table(letter.pricing_schedule, letter.price_str),
        "**Detailed Scope Breakdown**",
        (f"A detailed breakdown of each line item — quantities, rates and the resources used — is "
         f"provided in the accompanying pricing workbook (estimate_{letter.set_id}.xlsx)."),
        "Best Regards,",
        m.contact_name,
        f"**{m.company_name}**",
        f"**{m.company_address}**",
        "**Appendix A - Conditions of Offer**",
        appendix_lines,
    ])


def build_letter(
    scope: EstimateScope, estimate: Estimate, register: DepartureRegister, meta: LetterMeta,
) -> LetterOfOffer:
    """Assemble the offer letter: AI prose from the approved scope + code-injected price, fields,
    pricing schedule, and verbatim confirmed-departure conditions. Returns the letter with rendered
    markdown."""
    draft = _draft(scope)
    price = estimate.totals.price
    letter = LetterOfOffer(
        set_id=estimate.set_id,
        meta=meta,
        intro=draft.intro,
        price=price,
        price_str=_price_str(price),
        inclusions=list(draft.inclusions),
        exclusions=list(draft.exclusions),
        pricing_schedule=_pricing_schedule(estimate),
        appendix=_appendix(register, draft),
    )
    return letter.model_copy(update={"markdown": _render(letter)})
