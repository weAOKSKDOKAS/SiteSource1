"""Estimate error / omission check (Phase P3d — Layer-1 checking + a Layer-2 read).

Cross-check a drafted estimate and REPORT (never auto-fix):

* **Layer 1 (deterministic)** — against the tender requirements: an ``omission`` (a tendered
  item_ref with no estimate line), a ``unit_mismatch`` (same ref, different unit), and an
  ``unpriced`` estimate line (a completeness check). Pure Python, no model.
* **Rubric (corpus-gated)** — the ``rubric_items`` commonly-missed guidance for the trade:
  a rubric ref not in the estimate is flagged with its evidence-linked guidance. ``rubric_items``
  ships EMPTY, so this lights up only once real evidence exists — the honest empty state.
* **Layer 2 (a read of the scope)** — the model reads the scope-of-works and flags ``scope_gap``
  obligations with no priced line. Purpose ``estimate-check``. DEMO reads a baked fixture; a
  deterministic FALLBACK yields no L2 gaps (the L1 + rubric checks still run).

It reports; it never prices or edits. The person acts on the findings.
"""

from __future__ import annotations

from typing import Optional

from pydantic import ValidationError

from pipeline.llm_client import LLMClient, demo_mode
from schemas.estimate import EstimateCheckDraft

ESTIMATE_CHECK_FIXTURE = "cases/estimate/estimate_check.json"

_SYSTEM = (
    "You review a Hong Kong main contractor's own self-perform estimate against its "
    "scope-of-works and flag SCOPE GAPS — obligations described in the scope that have no "
    "priced line in the estimate (e.g. reinstatement, testing, temporary works). You REPORT "
    "only; you never invent a rate or a quantity. Return JSON: "
    '{"scope_gaps": [{"item_ref": <string, optional>, "message": <string>}]}.'
)


def _prompt(scope_of_works: str, estimate_items: list[dict]) -> str:
    lines = ", ".join(sorted({(i.get("item_ref") or "").strip() for i in estimate_items if i.get("item_ref")}))
    return (
        f"Scope-of-works:\n{(scope_of_works or '').strip()}\n\n"
        f"Priced item refs in the estimate: {lines or '(none)'}\n\n"
        "Flag any scope obligation with no corresponding priced line."
    )


def _l1_findings(estimate_items: list[dict], tender_items: list[dict]) -> list[dict]:
    est_by_ref = {(i.get("item_ref") or "").strip(): i for i in estimate_items if (i.get("item_ref") or "").strip()}
    findings: list[dict] = []
    for t in tender_items:
        ref = (t.get("item_ref") or "").strip()
        if not ref:
            continue
        e = est_by_ref.get(ref)
        if e is None:
            findings.append({"kind": "omission", "severity": "warning", "item_ref": ref, "source": "rules",
                             "message": f"Tender item {ref} ({(t.get('description') or '').strip()}) is not in the estimate."})
        else:
            tu, eu = (t.get("unit") or "").strip(), (e.get("unit") or "").strip()
            if tu and eu and tu.lower() != eu.lower():
                findings.append({"kind": "unit_mismatch", "severity": "warning", "item_ref": ref, "source": "rules",
                                 "message": f"Unit mismatch on {ref}: tender '{tu}' vs estimate '{eu}'."})
    for e in estimate_items:
        if e.get("rate") is None:
            ref = (e.get("item_ref") or "").strip() or "A line"
            findings.append({"kind": "unpriced", "severity": "info", "item_ref": (e.get("item_ref") or "").strip(),
                             "source": "rules", "message": f"{ref} is not yet priced."})
    return findings


def _rubric_findings(estimate_items: list[dict], rubric_rows: list[dict]) -> list[dict]:
    est_refs = {(i.get("item_ref") or "").strip().lower() for i in estimate_items}
    out: list[dict] = []
    for r in rubric_rows:
        ref = (r.get("item_ref") or "").strip()
        if ref and ref.lower() not in est_refs:
            out.append({"kind": "rubric", "severity": "warning", "item_ref": ref, "source": "rubric",
                        "message": (r.get("guidance") or f"Commonly-missed item {ref} is not in the estimate.").strip()})
    return out


def _l2_scope_gaps(scope_of_works: str, estimate_items: list[dict], demo_fixture: Optional[str], client: LLMClient) -> list[dict]:
    if not scope_of_works or not (demo_fixture or not demo_mode()):
        return []
    try:
        drafted = client.complete_json(
            system=_SYSTEM, user=_prompt(scope_of_works, estimate_items),
            target_model=EstimateCheckDraft, demo_fixture=demo_fixture, purpose="estimate-check",
        )
    except (RuntimeError, FileNotFoundError, ValidationError, ValueError):
        return []
    return [{"kind": "scope_gap", "severity": "warning", "item_ref": (g.item_ref or "").strip(),
             "source": "estimate-check", "message": g.message.strip()}
            for g in drafted.scope_gaps if g.message.strip()]


def check_estimate(estimate_items: list[dict], tender_items: list[dict], rubric_rows: list[dict],
                   scope_of_works: str, *, demo_fixture: Optional[str] = None,
                   client: Optional[LLMClient] = None) -> dict:
    """Return ``{findings, tender_checked, rubric_size}``. Reports only — never edits/prices."""
    client = client or LLMClient()
    findings = _l1_findings(estimate_items, tender_items) + _rubric_findings(estimate_items, rubric_rows)
    findings += _l2_scope_gaps(scope_of_works, estimate_items, demo_fixture, client)
    return {"findings": findings, "tender_checked": bool(tender_items), "rubric_size": len(rubric_rows)}
