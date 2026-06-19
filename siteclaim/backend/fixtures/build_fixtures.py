"""Generate the DEMO_MODE pipeline fixtures (run once; commits the JSON).

Three cases under ``fixtures/cases/<id>/``, each with ``source.json`` (SourceMaterial),
``extracted.json`` (the canned Stage-01 ExtractedFacts) and ``verdict.json`` (the canned
Stage-02 LLM-as-judge JudgeVerdict):

  - ``clean``  : a compliant claim, all high confidence (no review, no fatal)
  - ``messy``  : ambiguous source, several low-confidence fields (triggers review)
  - ``gotcha`` : extracts cleanly (high confidence, no review) but the claim was
                 served on the WRONG legal entity (a near-miss of the contracting
                 party) — notice.correct_party returns FATAL, so the report is INVALID

Reuses ``rules_engine.tests._helpers.make_compliant_facts`` (Phase 1) rather than
duplicating a fixture builder. Run from anywhere:  ``python fixtures/build_fixtures.py``.
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from rules_engine.tests._helpers import ff, make_compliant_facts  # noqa: E402
from schemas.models import (  # noqa: E402
    ExtractedFacts,
    FieldAssessment,
    JudgeVerdict,
    Party,
    ShipmentDocs,
    SourceMaterial,
    UploadedFile,
)

_CASES_DIR = _BACKEND / "fixtures" / "cases"


def _write(case_id: str, source: SourceMaterial, extracted: ExtractedFacts, verdict: JudgeVerdict) -> None:
    out = _CASES_DIR / case_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "source.json").write_text(source.model_dump_json(indent=2), encoding="utf-8")
    (out / "extracted.json").write_text(extracted.model_dump_json(indent=2), encoding="utf-8")
    (out / "verdict.json").write_text(verdict.model_dump_json(indent=2), encoding="utf-8")


def _docs(*names: str) -> ShipmentDocs:
    return ShipmentDocs(files=[UploadedFile(filename=n, content_type="application/pdf") for n in names])


def build_clean() -> None:
    source = SourceMaterial(
        case_id="clean",
        description=(
            "Payment claim for rebar fixing to grid C–F carried out in February 2026 under our "
            "subcontract with BigBuild Main Contractor Ltd (main contract ~HK$8,000,000). "
            "Reference date 28 Feb 2026. We claim HK$1,250,000.00 per the attached invoice and "
            "site diary. The claim was served by hand on BigBuild on 2 Mar 2026; we kept the "
            "signed delivery receipt. BigBuild served a payment response the same day."
        ),
        docs=_docs("invoice_42.pdf", "site_diary_feb.pdf"),
    )
    extracted = make_compliant_facts()  # all confidence 0.95
    verdict = JudgeVerdict(
        summary="Every field is clearly supported by the source; no adjustments.",
        assessments=[
            FieldAssessment(field="claimed_amount", supported=True, adjusted_confidence=0.95, note="Stated as HK$1,250,000.00."),
            FieldAssessment(field="parties.respondent", supported=True, adjusted_confidence=0.95, note="BigBuild named explicitly."),
            FieldAssessment(field="reference_date", supported=True, adjusted_confidence=0.95, note="28 Feb 2026 stated."),
        ],
    )
    _write("clean", source, extracted, verdict)


def build_messy() -> None:
    source = SourceMaterial(
        case_id="messy",
        description=(
            "We did some rebar work around February, think the invoice was about 1.25 million? "
            "Contract is roughly 8 mil I believe. Served the main contractor but I'm not 100% sure "
            "of the exact date — sometime early March. Don't have all the paperwork to hand."
        ),
        docs=_docs("scan_invoice.pdf"),
    )
    extracted = make_compliant_facts()
    # Present values, but uncertain — several below the 0.6 review threshold.
    extracted.contract_sum.confidence = 0.40
    extracted.claimed_amount.confidence = 0.50
    extracted.reference_date.confidence = 0.45
    extracted.work_period.confidence = 0.45
    extracted.claim_served_date.confidence = 0.50
    verdict = JudgeVerdict(
        summary="Source is vague; figures are approximate and the service date is unstated.",
        assessments=[
            FieldAssessment(field="contract_sum", supported=False, adjusted_confidence=0.30, note="'roughly 8 mil' — approximate, not a stated contract sum."),
            FieldAssessment(field="reference_date", supported=False, adjusted_confidence=0.25, note="Only 'around February' — no reference date stated."),
            FieldAssessment(field="claim_served_date", supported=False, adjusted_confidence=0.35, note="'sometime early March' — exact service date unknown."),
        ],
    )
    _write("messy", source, extracted, verdict)


def build_gotcha() -> None:
    source = SourceMaterial(
        case_id="gotcha",
        description=(
            "Payment claim for rebar fixing to grid C–F, February 2026. Our subcontract is with "
            "Dragon Build (Kowloon) Ltd (main contract HK$8,000,000). Reference date 28 Feb 2026, "
            "amount HK$1,250,000.00. We served the claim by hand on 2 Mar 2026 on Dragon Build Ltd "
            "and kept the signed delivery receipt."
        ),
        docs=_docs("invoice_42.pdf", "delivery_receipt.pdf"),
    )
    extracted = make_compliant_facts()
    # Extracts cleanly and is served by a clean method (personal_delivery, INFO).
    # The LEGAL defect: served on a DIFFERENT legal entity than the contracting party
    # (a near-miss) — notice.correct_party returns FATAL in the existing engine.
    extracted.parties.respondent = ff(Party(name="Dragon Build (Kowloon) Ltd", role="main contractor"))
    extracted.service.served_on = ff("Dragon Build Ltd")  # wrong entity — near-miss
    verdict = JudgeVerdict(
        summary="Extraction is well supported by the source; both the contracting party and the served party are stated. (Whether they are the same legal entity is a question of law for the rules engine, not extraction.)",
        assessments=[
            FieldAssessment(field="parties.respondent", supported=True, adjusted_confidence=0.95, note="Source: subcontract is with Dragon Build (Kowloon) Ltd."),
            FieldAssessment(field="service.served_on", supported=True, adjusted_confidence=0.95, note="Source: served on Dragon Build Ltd."),
            FieldAssessment(field="claimed_amount", supported=True, adjusted_confidence=0.95, note="HK$1,250,000.00 stated."),
        ],
    )
    _write("gotcha", source, extracted, verdict)


def main() -> None:
    build_clean()
    build_messy()
    build_gotcha()
    print(f"Wrote fixtures for: clean, messy, gotcha -> {_CASES_DIR}")


if __name__ == "__main__":
    main()
