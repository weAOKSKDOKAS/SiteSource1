"""Run Stage 01 -> Stage 02 on the demo fixtures and pretty-print the results.

Offline by default: this script forces DEMO_MODE on, so the pipeline reads canned
fixtures and makes ZERO network calls. Run from the ``backend/`` directory:

    python pipeline/run_pipeline.py
"""

import os
import sys

os.environ.setdefault("DEMO_MODE", "true")  # force offline before importing the client

from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

# Allow `python pipeline/run_pipeline.py` from backend/ (put backend/ on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rules_engine.deadlines import clock  # noqa: E402
from rules_engine.engine import run_validation  # noqa: E402
from schemas.models import ExtractedFacts, JudgeReview, SourceMaterial, ValidityReport  # noqa: E402

from pipeline.stage_01_extract.extract import extract_facts  # noqa: E402
from pipeline.stage_02_validate.verify import iter_fact_fields, verify_extraction  # noqa: E402

DEMO_TODAY = date(2026, 3, 2)
CASES = ("clean", "messy", "gotcha")
_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "cases"


def _rule(char: str = "─") -> str:
    return char * 78


def _print_facts(facts: ExtractedFacts) -> None:
    print("  Extracted facts (value | confidence | source_span):")
    for path, field in iter_fact_fields(facts):
        if field.value is None:
            continue
        span = f' | "{field.source_span}"' if field.source_span else ""
        print(f"    {path:<28} {str(field.value):<34} conf={field.confidence:.2f}{span}")
    for i, item in enumerate(facts.line_items):
        print(f"    line_items[{i}]               {item.description!r} amount={item.amount} conf={item.confidence:.2f}")


def _print_judge(review: JudgeReview) -> None:
    print(f"  Judge: {review.summary}")
    if review.disputed_fields:
        print("  Judge adjustments (confidence lowered):")
        for a in review.disputed_fields:
            print(f"    - {a.field}: -> {a.adjusted_confidence:.2f}  ({a.note})")
    else:
        print("  Judge adjustments: none")
    if review.review_flags:
        print(f"  ⚑ FLAGGED FOR HUMAN REVIEW ({len(review.review_flags)} field(s) below threshold):")
        for flag in review.review_flags:
            print(f"    - {flag.field}: {flag.value_repr}  ({flag.reason})")
    else:
        print("  ⚑ Human review: none (all present fields above threshold)")


def _print_report(report: ValidityReport, today: date) -> None:
    verdict = "VALID (no fatal checks)" if report.is_valid else "INVALID (fatal check failed)"
    print(f"  ValidityReport: {verdict} — {len(report.checks)} checks (fatal → warning → info):")
    for c in report.checks:
        mark = "✗" if not c.passed else "✓"
        print(f"    [{c.severity.value:<7}] {mark} {c.name}  <{c.sopo_reference}>")
    ds = report.deadlines
    if ds is not None and ds.deadlines:
        clk = clock(ds, today)
        nearest = clk.nearest.name if clk.nearest else "—"
        print(f"  DeadlineSet clock (today={today}): nearest={nearest}, breached={len(clk.breached)}")
        for d in ds.deadlines:
            state = "BREACHED" if d.due_date < today else "ok"
            print(f"    {d.name:<24} due {d.due_date}  ({d.business_days_remaining:+d} business days, {state})  <{d.sopo_reference}>")


def run_case(case_id: str) -> JudgeReview:
    source = SourceMaterial.model_validate_json(
        (_FIXTURES / case_id / "source.json").read_text(encoding="utf-8")
    )
    print(_rule("═"))
    print(f"CASE: {case_id}")
    print(_rule())
    print(f"  Source: {source.description[:120]}{'…' if len(source.description) > 120 else ''}")
    print()

    facts = extract_facts(source)  # Stage 01 (DEMO: canned ExtractedFacts)
    _print_facts(facts)
    print()

    review = verify_extraction(source, facts)  # Stage 02a — LLM-as-judge
    _print_judge(review)
    print()

    report = run_validation(review.facts, DEMO_TODAY)  # Stage 02b — deterministic engine
    _print_report(report, DEMO_TODAY)
    print()
    return review


def main() -> None:
    print(f"SiteClaim pipeline demo (DEMO_MODE={os.environ['DEMO_MODE']}, offline) — today={DEMO_TODAY}\n")
    triggered: list[str] = []
    for case_id in CASES:
        review = run_case(case_id)
        if review.review_flags:
            triggered.append(case_id)
    print(_rule("═"))
    print("SUMMARY")
    print(_rule())
    print(f"  Fixtures that triggered low-confidence review: {triggered or 'none'}")


if __name__ == "__main__":
    main()
