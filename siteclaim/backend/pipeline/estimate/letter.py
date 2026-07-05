"""Letter-of-offer draft (Phase P3e — Layer 2, assist only).

Draft the assumptions and qualifications (a covering body, inclusions, exclusions,
assumptions) for a self-perform estimate, from its scope-of-works and priced schedule.
Purpose tag ``letter-of-offer``. The person owns and issues the final letter — this is a
draft. DEMO reads a baked fixture; a deterministic FALLBACK builds a templated letter from
the estimate (the total is only ever the computable figure the store already rolled up),
so the draft can never hard-fail.
"""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from pipeline.llm_client import LLMClient, demo_mode
from schemas.estimate import LetterOfOffer

LETTER_FIXTURE = "cases/estimate/letter_of_offer.json"

_SYSTEM = (
    "You draft a professional Letter of Offer for a Hong Kong main contractor that will "
    "SELF-PERFORM a work package. From the scope-of-works, the priced schedule, and the total, "
    "produce: a short covering body, a list of inclusions, a list of exclusions, and a list of "
    "assumptions / qualifications. You DRAFT only — the person reviews, owns, and issues the "
    "final letter, and owns every rate. Do not invent a total or a rate. Return JSON: "
    '{"subject": <string>, "body": <string>, "inclusions": [<string>], "exclusions": '
    '[<string>], "assumptions": [<string>]}.'
)


def _fmt_total(total: Optional[float]) -> str:
    return f"HK${total:,.2f}" if total is not None else "the sum stated in the attached priced schedule"


def _prompt(estimate: dict, items: list[dict]) -> str:
    priced = [i for i in items if i.get("rate") is not None]
    trade = (estimate.get("trade") or "the works").replace("_", " ")
    return (
        f"Project: {estimate.get('name') or '(unnamed)'}\n"
        f"Trade: {trade}\n"
        f"Client: {estimate.get('client') or '(not stated)'}\n"
        f"Scope-of-works: {(estimate.get('scope_of_works') or '').strip() or '(not provided)'}\n"
        f"Priced lines: {len(priced)} of {len(items)}; total {_fmt_total(estimate.get('total'))}\n\n"
        "Draft the letter of offer."
    )


def _fallback_letter(estimate: dict, items: list[dict]) -> dict:
    name = estimate.get("name") or "the works"
    trade = (estimate.get("trade") or "the works").replace("_", " ")
    priced = [i for i in items if i.get("rate") is not None]
    body = (
        f"We are pleased to submit our offer to self-perform the {trade} package for {name}. "
        f"Our offer is based on the attached priced schedule of rates, totalling {_fmt_total(estimate.get('total'))}. "
        "This letter and the attached schedule together constitute our offer."
    )
    inclusions = ["The works described in the scope of works and the attached priced schedule."]
    if priced:
        inclusions.append(f"All {len(priced)} priced item(s) in the schedule.")
    return {
        "subject": f"Letter of Offer — {name}",
        "body": body,
        "inclusions": inclusions,
        "exclusions": [
            "Statutory fees and charges.",
            "Any work not described in the scope of works or the attached schedule.",
            "Value Added Tax or equivalent, where applicable.",
        ],
        "assumptions": [
            "Rates hold for 90 days from the date of this letter.",
            "Continuous and unobstructed access to the working areas.",
            "Quantities are subject to remeasurement at the tendered rates.",
        ],
    }


def draft_letter(estimate: dict, items: list[dict], *,
                 demo_fixture: Optional[str] = None, client: Optional[LLMClient] = None) -> dict:
    """Return a letter-of-offer draft (``subject``, ``body``, ``inclusions``, ``exclusions``,
    ``assumptions``). The model drafts (DEMO reads the fixture); a deterministic fallback keeps
    a usable letter. The person owns the final letter."""
    letter = _fallback_letter(estimate, items)
    client = client or LLMClient()
    if demo_fixture or not demo_mode():
        try:
            drafted = client.complete_json(
                system=_SYSTEM, user=_prompt(estimate, items),
                target_model=LetterOfOffer, demo_fixture=demo_fixture, purpose="letter-of-offer",
            )
            letter = {
                "subject": drafted.subject.strip() or letter["subject"],
                "body": drafted.body.strip() or letter["body"],
                "inclusions": [x.strip() for x in drafted.inclusions if x.strip()] or letter["inclusions"],
                "exclusions": [x.strip() for x in drafted.exclusions if x.strip()] or letter["exclusions"],
                "assumptions": [x.strip() for x in drafted.assumptions if x.strip()] or letter["assumptions"],
            }
        except (RuntimeError, FileNotFoundError, ValidationError, ValueError):
            pass
    return letter
