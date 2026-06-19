"""Stage 02 — self-verification (two distinct jobs, kept separate).

(a) ``verify_extraction`` — **LLM-as-judge** (Layer 2). A SECOND model pass re-reads
    the source + the extracted facts and, per field, asks "is this actually supported
    by the source?" It lowers confidence and records a note where not, and flags every
    field below ``sopo_config.CONFIDENCE_REVIEW_THRESHOLD`` for human review.

(b) ``run_validation`` — the **deterministic Phase 1 engine** (Layer 1). The LLM does
    NOT touch this; it decides the law.

``run_stage_02`` runs the judge, then the engine, and returns ``(facts, ValidityReport)``.
"""

import json
from collections.abc import Iterator
from datetime import date

from rules_engine import sopo_config
from rules_engine.engine import run_validation
from schemas.models import (
    ExtractedFacts,
    FactField,
    FieldAssessment,
    JudgeReview,
    JudgeVerdict,
    ReviewFlag,
    SourceMaterial,
    ValidityReport,
)

from pipeline.llm_client import LLMClient

_client = LLMClient()

# Dotted paths to every FactField-bearing attribute on ExtractedFacts. The judge
# may assess any of these; review-flagging walks the same set.
FACT_FIELD_PATHS: tuple[str, ...] = (
    "contract_sum",
    "contract_type",
    "sector",
    "reference_date",
    "claimed_amount",
    "work_period",
    "contract_date",
    "claim_served_date",
    "claim_in_writing",
    "parties.claimant",
    "parties.respondent",
    "service.method",
    "service.served_on",
    "service.date_served",
    "service.proof_retained",
    "payment_response.served",
    "payment_response.date_served",
    "payment_response.admitted_amount",
    "payment_response.disputes_claim",
)


def _resolve_factfield(facts: ExtractedFacts, path: str) -> FactField | None:
    """Navigate a dotted path and return the FactField at the end, or None."""
    obj: object = facts
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj if isinstance(obj, FactField) else None


def iter_fact_fields(facts: ExtractedFacts) -> Iterator[tuple[str, FactField]]:
    """Yield ``(path, FactField)`` for every resolvable FactField on the facts."""
    for path in FACT_FIELD_PATHS:
        field = _resolve_factfield(facts, path)
        if field is not None:
            yield path, field


def fields_for_review(
    facts: ExtractedFacts, threshold: float = sopo_config.CONFIDENCE_REVIEW_THRESHOLD
) -> list[ReviewFlag]:
    """Flag every PRESENT field whose confidence is below ``threshold``.

    Absent fields (value is None) are not flagged — only extracted-but-uncertain
    values are surfaced for human review.
    """
    flags: list[ReviewFlag] = []
    for path, field in iter_fact_fields(facts):
        if field.value is not None and field.confidence < threshold:
            flags.append(
                ReviewFlag(
                    field=path,
                    confidence=field.confidence,
                    value_repr=str(field.value),
                    reason=f"confidence {field.confidence:.2f} < review threshold {threshold:.2f}",
                )
            )
    return flags


# ---------------------------------------------------------------------------
# (a) LLM-as-judge
# ---------------------------------------------------------------------------
_JUDGE_SYSTEM = """You are the verification stage of SiteClaim — an LLM-as-judge. \
A previous pass extracted structured facts from a subcontractor's source material. \
Your job is to second-guess that extraction, field by field.

For each extracted field that has a value, decide whether the SOURCE MATERIAL actually \
supports it. If a value is unsupported, weakly supported, or contradicted, mark \
`supported`=false and LOWER `adjusted_confidence`, with a short `note` explaining why. \
If a value is well supported, you may confirm it (`supported`=true) and keep or raise its \
confidence. Do not invent new facts; only assess the ones given.

Return STRICT JSON for the JudgeVerdict schema below — no prose, no code fences.

JudgeVerdict JSON schema:
{schema}
"""


def _judge_system_prompt() -> str:
    return _JUDGE_SYSTEM.format(
        schema=json.dumps(JudgeVerdict.model_json_schema(), indent=0)
    )


def _judge_user_prompt(source: SourceMaterial, facts: ExtractedFacts) -> str:
    return (
        "SOURCE MATERIAL\n"
        f"{source.description or '(none provided)'}\n\n"
        "EXTRACTED FACTS (assess each field):\n"
        f"{facts.model_dump_json(indent=2)}\n\n"
        "Return the JudgeVerdict JSON now."
    )


def verify_extraction(source: SourceMaterial, facts: ExtractedFacts) -> JudgeReview:
    """LLM-as-judge: adjust per-field confidence, collect disputes + review flags.

    Returns a :class:`JudgeReview` (the confidence-adjusted facts plus the disputed
    fields and the below-threshold review flags). A superset of the bare adjusted
    ExtractedFacts so the disputed-field list the spec asks for is not lost.
    """
    demo_fixture = f"cases/{source.case_id}/verdict.json" if source.case_id else None
    verdict: JudgeVerdict = _client.complete_json(
        system=_judge_system_prompt(),
        user=_judge_user_prompt(source, facts),
        target_model=JudgeVerdict,
        demo_fixture=demo_fixture,
    )

    adjusted = facts.model_copy(deep=True)
    disputed: list[FieldAssessment] = []
    for assessment in verdict.assessments:
        field = _resolve_factfield(adjusted, assessment.field)
        if field is not None:
            field.confidence = assessment.adjusted_confidence
        if not assessment.supported:
            disputed.append(assessment)

    return JudgeReview(
        facts=adjusted,
        disputed_fields=disputed,
        review_flags=fields_for_review(adjusted),
        summary=verdict.summary,
    )


# ---------------------------------------------------------------------------
# (b) Orchestration: judge, then the deterministic engine
# ---------------------------------------------------------------------------
def run_stage_02(
    source: SourceMaterial, facts: ExtractedFacts, today: date
) -> tuple[ExtractedFacts, ValidityReport]:
    """Run the judge, then the deterministic Phase 1 engine; return both outputs.

    The returned facts are confidence-adjusted by the judge; the ValidityReport
    (with its attached DeadlineSet) is produced purely by Layer 1.
    """
    review = verify_extraction(source, facts)
    report = run_validation(review.facts, today)
    return review.facts, report
